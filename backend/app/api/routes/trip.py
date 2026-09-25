"""旅行规划API路由"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...models.schemas import (
    TripRequest,
    TripPlanResponse,
    TaskCreatedResponse,
    TaskStatusResponse,
)
from ...agents.trip_planner_agent import get_trip_planner_agent
from ...core.exceptions import BizException
from ...db.database import get_db
from ...services import history_service
from ...services.rag_service import get_rag_service
from ...services.task_service import get_task_manager

router = APIRouter(prefix="/trip", tags=["旅行规划"])

logger = logging.getLogger(__name__)


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求,生成详细的旅行计划",
)
def plan_trip(request: TripRequest, db: Session = Depends(get_db)):
    """
    生成旅行计划

    注意: 本接口不声明 async。内部是同步的 LLM+高德调用(可能耗时30秒+),
    由 FastAPI 自动放到线程池执行, 避免阻塞事件循环拖慢其他接口。

    生成成功后自动:
    1. 保存历史记录到 SQLite (供 /api/history 查询)
    2. 写入 RAG 向量库 (供下次规划时检索参考)
    (以上两步失败不影响行程返回)

    Args:
        request: 旅行请求参数
        db: 数据库会话

    Returns:
        旅行计划响应
    """
    logger.info(
        f"收到旅行规划请求: 城市={request.city}, "
        f"日期={request.start_date}~{request.end_date}, 天数={request.travel_days}"
    )

    # 获取Agent实例并生成旅行计划 (异常由全局异常处理器统一兜底)
    agent = get_trip_planner_agent()
    trip_plan = agent.plan_trip(request)

    # 生成成功 → 保存历史 + RAG 入库 (失败仅告警, 不影响主流程)
    try:
        record = history_service.create_trip_record(db, request, trip_plan)
        get_rag_service().add_history_plan(record.id, request, trip_plan)
    except Exception as e:
        logger.warning(f"⚠️ 历史记录/RAG 保存失败(不影响行程): {e}")

    return TripPlanResponse(
        success=True,
        # 降级模式明确告知调用方, 不再把兜底数据伪装成正常的LLM生成结果(旧版bug)
        message=(
            "旅行计划生成成功(降级模式: LLM生成失败, 已用高德真实POI数据兜底)"
            if trip_plan.is_fallback
            else "旅行计划生成成功"
        ),
        data=trip_plan,
    )


@router.post(
    "/tasks",
    response_model=TaskCreatedResponse,
    summary="创建异步规划任务(小程序端推荐)",
    description=(
        "立即返回 task_id, 规划在后台执行 (完整流程通常 30~90 秒)。"
        "前端用 GET /api/trip/tasks/{task_id} 轮询进度与结果。"
        "任务结果保留 30 分钟, 过期后返回 404, 需重新创建任务。"
    ),
)
def create_trip_task(request: TripRequest):
    """创建异步规划任务

    与同步 /plan 接口的区别: 不阻塞等待 LLM 生成, 适合小程序等
    对请求超时有严格限制的客户端。生成成功后同样会保存历史 + RAG 入库。
    """
    task = get_task_manager().submit(request)
    return TaskCreatedResponse(success=True, task_id=task.task_id, status=task.status)


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    summary="查询异步任务状态/结果",
    description=(
        "轮询本接口获取任务进度。status=completed 时 data 返回完整行程; "
        "status=failed 时 error 返回失败原因; 任务不存在或已过期返回 404。"
    ),
)
def get_trip_task(task_id: str):
    """查询任务状态 (建议前端每 2 秒轮询一次)"""
    task = get_task_manager().get(task_id)
    if task is None:
        raise BizException(f"任务不存在或已过期: {task_id}", status_code=404)
    return TaskStatusResponse(
        success=True,
        task_id=task.task_id,
        status=task.status,
        stage=task.stage,
        progress=task.progress,
        created_at=task.created_at,
        finished_at=task.finished_at,
        error=task.error,
        data=task.result,
    )


@router.get(
    "/health",
    summary="健康检查",
    description="检查旅行规划服务是否正常",
)
async def health_check():
    """健康检查"""
    try:
        agent = get_trip_planner_agent()
        info = agent.get_agent_info()

        return {
            "status": "healthy",
            "service": "trip-planner",
            "agent_name": info["name"],
            "framework": info["framework"],
            "nodes_count": len(info["nodes"]),
        }
    except Exception as e:
        raise BizException(f"服务不可用: {str(e)}", status_code=503)
