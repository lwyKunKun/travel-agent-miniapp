"""异步任务管理器 (小程序端专用)

背景: LangGraph 完整规划耗时通常 30~90 秒, 微信小程序 wx.request 不适合长时间同步等待。
方案: POST /api/trip/tasks 立即返回 task_id, 规划在后台线程池执行;
      前端 GET /api/trip/tasks/{task_id} 轮询状态/进度/结果。

设计取舍:
- 任务状态存内存 (dict + 锁), 不引入 Redis/Celery 等外部依赖, 与项目"单机可跑"的定位一致。
  代价: 进程重启后未完成任务丢失 → 前端轮询到 404 时提示用户重新生成即可。
- 进度按"阶段推进 + 时间插值"估算: LangGraph 节点内部无法注入回调,
  用后台心跳线程按各节点经验耗时推进 progress, 完成时置 100。
- 任务结果保留 TTL (默认 30 分钟), 过期自动清理, 防止内存无限增长。
"""

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

from ..models.schemas import TripPlan, TripRequest

logger = logging.getLogger(__name__)

# 任务结果保留时长(秒): 完成后 30 分钟内可查询, 过期由心跳线程清理
TASK_TTL_SECONDS = 30 * 60

# 各阶段经验耗时(秒)与进度上限, 用于时间插值估算:
# (阶段描述, 预计耗时, 该阶段结束时的进度值)
_STAGE_PLAN = [
    ("正在搜索景点…", 15, 25),
    ("正在查询天气…", 8, 40),
    ("正在搜索酒店…", 10, 55),
    ("正在搜索美食…", 8, 65),
    ("AI 正在生成行程…", 40, 95),
]


def _now_iso() -> str:
    """当前 UTC 时间 ISO8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TripTask:
    """一次异步规划任务的状态"""

    task_id: str
    request: TripRequest
    # 归属用户 ID (小程序登录用户); None 表示匿名 (Web 端/未登录)
    user_id: Optional[int] = None
    status: str = "pending"  # pending / running / completed / failed
    stage: str = ""
    progress: int = 0
    created_at: str = field(default_factory=_now_iso)
    finished_at: Optional[str] = None
    error: Optional[str] = None
    result: Optional[TripPlan] = None
    _start_ts: float = field(default_factory=time.monotonic, repr=False)


class TaskManager:
    """内存任务管理器 (线程安全, 单例使用)"""

    def __init__(self, max_workers: int = 4):
        self._tasks: Dict[str, TripTask] = {}
        self._lock = threading.Lock()
        # 规划是重 IO + LLM 调用, 线程池即可, 限制并发防止 LLM/高德 QPS 被打爆
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="trip-task")

    # ---------- 对外接口 ----------

    def submit(self, request: TripRequest, user_id: Optional[int] = None) -> TripTask:
        """创建任务并投递到后台线程池, 立即返回 (不等结果)

        Args:
            user_id: 归属用户 ID, 任务完成后保存历史记录时写入 (用户隔离)
        """
        task = TripTask(task_id=uuid.uuid4().hex, request=request, user_id=user_id)
        with self._lock:
            self._tasks[task.task_id] = task
            self._cleanup_expired_locked()
        self._executor.submit(self._run_task, task)
        logger.info(
            f"📋 异步任务已创建: task_id={task.task_id}, 城市={request.city}, "
            f"用户={user_id if user_id else '匿名'}"
        )
        return task

    def get(self, task_id: str) -> Optional[TripTask]:
        """查询任务 (不存在或已过期返回 None)"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None:
                self._update_progress_locked(task)
            return task

    # ---------- 内部实现 ----------

    def _run_task(self, task: TripTask) -> None:
        """后台执行完整规划流程 (在独立 DB 会话中保存历史)"""
        from ..agents.trip_planner_agent import get_trip_planner_agent
        from ..db.database import SessionLocal
        from . import history_service
        from .rag_service import get_rag_service

        with self._lock:
            task.status = "running"
            task.stage = _STAGE_PLAN[0][0]
            task._start_ts = time.monotonic()

        try:
            agent = get_trip_planner_agent()
            trip_plan = agent.plan_trip(task.request)

            # 保存历史 + RAG 入库 (与同步接口一致, 失败不影响结果返回)
            db = SessionLocal()
            try:
                record = history_service.create_trip_record(
                    db, task.request, trip_plan, user_id=task.user_id
                )
                get_rag_service().add_history_plan(record.id, task.request, trip_plan)
            except Exception as e:
                logger.warning(f"⚠️ 异步任务历史/RAG 保存失败(不影响行程): {e}")
            finally:
                db.close()

            with self._lock:
                task.status = "completed"
                task.stage = "行程生成完成"
                task.progress = 100
                task.result = trip_plan
                task.finished_at = _now_iso()
            logger.info(f"✅ 异步任务完成: task_id={task.task_id}")
        except Exception as e:
            logger.exception(f"❌ 异步任务失败: task_id={task.task_id}")
            with self._lock:
                task.status = "failed"
                task.stage = "生成失败"
                task.error = str(e)
                task.finished_at = _now_iso()

    def _update_progress_locked(self, task: TripTask) -> None:
        """按阶段计划 + 已用时间插值更新进度 (调用方需持锁; 完成/失败任务不动)

        说明: LangGraph 节点内部无回调可挂, 无法拿到真实节点边界,
        因此按经验耗时估算; 每个阶段内进度线性爬升但不超过该阶段上限,
        真实结果出来前最多显示 95%, 完成时由 _run_task 置 100。
        """
        if task.status not in ("pending", "running"):
            return
        elapsed = time.monotonic() - task._start_ts
        acc = 0.0
        prev_cap = 0
        for stage, est, cap in _STAGE_PLAN:
            if elapsed < acc + est:
                # 落在当前阶段内: 线性插值
                ratio = (elapsed - acc) / est
                task.stage = stage
                task.progress = min(int(prev_cap + ratio * (cap - prev_cap)), cap)
                return
            acc += est
            prev_cap = cap
        # 超出全部预估耗时: 停在最后阶段 95%, 等待真实完成
        task.stage = "AI 正在生成行程…(耗时较长, 请稍候)"
        task.progress = 95

    def _cleanup_expired_locked(self) -> None:
        """清理过期任务 (调用方需持锁): 已结束且超过 TTL 的任务删除"""
        now = time.time()
        expired = [
            tid
            for tid, t in self._tasks.items()
            if t.status in ("completed", "failed") and t.finished_at is not None
            and now - datetime.fromisoformat(t.finished_at).timestamp() > TASK_TTL_SECONDS
        ]
        for tid in expired:
            del self._tasks[tid]
        if expired:
            logger.info(f"🧹 已清理 {len(expired)} 个过期任务")


# ---------- 模块级单例 ----------

_manager: Optional[TaskManager] = None
_manager_lock = threading.Lock()


def get_task_manager() -> TaskManager:
    """获取任务管理器单例 (懒加载, 线程安全)"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = TaskManager()
    return _manager
