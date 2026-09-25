"""异步任务接口测试: mock Agent, 不调用真实 LLM/高德

覆盖小程序端核心链路: 创建任务 → 轮询进度 → 完成取结果 → 404 兜底
"""

import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.models.schemas import TripPlan, DayPlan


VALID_REQUEST = {
    "city": "深圳",
    "start_date": "2026-10-01",
    "end_date": "2026-10-02",
    "travel_days": 2,
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["美食"],
    "free_text_input": "",
}


def make_fake_plan() -> TripPlan:
    """构造一个合法的旅行计划 (测试用固定数据)"""
    return TripPlan(
        city="深圳",
        start_date="2026-10-01",
        end_date="2026-10-02",
        days=[
            DayPlan(
                date="2026-10-01",
                day_index=0,
                description="测试行程",
                transportation="地铁",
                accommodation="经济型酒店",
            )
        ],
        overall_suggestions="测试建议",
    )


def wait_until_finished(client: TestClient, task_id: str, timeout: float = 10.0) -> dict:
    """轮询任务直到结束 (completed/failed) 或超时"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/trip/tasks/{task_id}").json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.2)
    raise TimeoutError(f"任务 {task_id} 在 {timeout}s 内未结束")


def test_task_lifecycle(client: TestClient):
    """完整生命周期: 创建 → 运行中 → 完成 (progress=100 + 行程数据)"""
    fake_agent = MagicMock()
    fake_agent.plan_trip.return_value = make_fake_plan()

    with patch(
        "app.agents.trip_planner_agent.get_trip_planner_agent",
        return_value=fake_agent,
    ), patch("app.services.history_service.create_trip_record") as m_hist, patch(
        "app.services.rag_service.get_rag_service"
    ):
        m_hist.return_value.id = 1

        # 1. 创建任务: 立即返回 task_id, 不阻塞
        # (mock 的 plan_trip 瞬间完成, 后台线程可能抢在响应序列化前置为 completed, 属正常)
        resp = client.post("/api/trip/tasks", json=VALID_REQUEST)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["task_id"]
        assert body["status"] in ("pending", "running", "completed")
        task_id = body["task_id"]

        # 2. 轮询到结束
        final = wait_until_finished(client, task_id)
        assert final["status"] == "completed"
        assert final["progress"] == 100
        assert final["finished_at"]
        assert final["error"] is None
        assert final["data"]["city"] == "深圳"
        assert len(final["data"]["days"]) == 1

        # 3. 生成成功后应保存历史记录
        assert m_hist.called


def test_task_not_found(client: TestClient):
    """不存在的 task_id 返回 404 (含过期任务场景)"""
    resp = client.get("/api/trip/tasks/nonexistent_task_id")
    assert resp.status_code == 404


def test_task_failed(client: TestClient):
    """Agent 抛异常时任务置为 failed, error 返回原因, 不影响服务可用性"""
    fake_agent = MagicMock()
    fake_agent.plan_trip.side_effect = RuntimeError("模拟 LLM 调用失败")

    with patch(
        "app.agents.trip_planner_agent.get_trip_planner_agent",
        return_value=fake_agent,
    ):
        resp = client.post("/api/trip/tasks", json=VALID_REQUEST)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        final = wait_until_finished(client, task_id)
        assert final["status"] == "failed"
        assert "模拟 LLM 调用失败" in final["error"]
        assert final["data"] is None


def test_task_request_validation(client: TestClient):
    """非法请求体 (缺字段/天数越界) 应返回 422, 不创建任务"""
    bad = {**VALID_REQUEST, "travel_days": 99}
    resp = client.post("/api/trip/tasks", json=bad)
    assert resp.status_code == 422
