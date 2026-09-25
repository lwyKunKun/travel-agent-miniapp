"""认证与用户隔离测试: mock 登录模式 (conftest 未配置 WX_APPID), 不调真实微信接口

覆盖:
- POST /api/auth/login 登录签发 JWT (新用户/老用户)
- GET /api/auth/me token 校验
- /api/history 未登录 401
- 历史记录按用户隔离 (A 看不到 B 的记录, 越权访问 404)
- 异步任务携带登录态 → 历史记录挂到用户名下
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.models.schemas import TripPlan, DayPlan


def make_fake_plan(city: str = "深圳") -> TripPlan:
    """构造合法行程 (测试固定数据)"""
    return TripPlan(
        city=city,
        start_date="2026-10-01",
        end_date="2026-10-02",
        days=[
            DayPlan(
                date="2026-10-01",
                day_index=0,
                description="测试",
                transportation="地铁",
                accommodation="酒店",
            )
        ],
        overall_suggestions="测试",
    )


VALID_REQUEST = {
    "city": "深圳",
    "start_date": "2026-10-01",
    "end_date": "2026-10-02",
    "travel_days": 2,
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": [],
    "free_text_input": "",
}


def login(client: TestClient, code: str) -> dict:
    """登录并返回响应体"""
    resp = client.post("/api/auth/login", json={"code": code})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] and body["token"]
    return body


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============ 登录 ============

def test_login_new_and_existing_user(client: TestClient):
    """首次登录 is_new_user=True, 同 code 再登录为同一用户且 is_new_user=False"""
    body1 = login(client, "test_code_new_user")
    assert body1["is_new_user"] is True
    assert body1["mock_mode"] is True  # conftest 未配置 WX_APPID
    assert body1["expires_in"] > 0

    body2 = login(client, "test_code_new_user")
    assert body2["is_new_user"] is False
    assert body2["user_id"] == body1["user_id"]


def test_login_empty_code_rejected(client: TestClient):
    """空 code 应被拒绝 (Pydantic min_length=1 → 422)"""
    resp = client.post("/api/auth/login", json={"code": ""})
    assert resp.status_code == 422


def test_me_with_and_without_token(client: TestClient):
    """/api/auth/me: 带合法 token 返回用户信息, 无 token 401"""
    body = login(client, "test_code_me")
    resp = client.get("/api/auth/me", headers=auth_header(body["token"]))
    assert resp.status_code == 200
    info = resp.json()
    assert info["user_id"] == body["user_id"]
    assert info["nickname"]

    resp = client.get("/api/auth/me")
    assert resp.status_code == 401

    resp = client.get("/api/auth/me", headers=auth_header("invalid.token.here"))
    assert resp.status_code == 401


# ============ 历史记录鉴权与隔离 ============

def test_history_requires_auth(client: TestClient):
    """历史接口未登录一律 401"""
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/history/1").status_code == 401
    assert client.delete("/api/history/1").status_code == 401


def test_history_user_isolation(client: TestClient):
    """用户 A 生成的历史, 用户 B 看不到也删不掉 (越权返回 404)"""
    user_a = login(client, "test_code_isolation_a")
    user_b = login(client, "test_code_isolation_b")

    fake_agent = MagicMock()
    fake_agent.plan_trip.return_value = make_fake_plan()

    # A 通过异步任务生成一条历史 (登录态 → 记录挂 A 名下)
    import time

    with patch(
        "app.agents.trip_planner_agent.get_trip_planner_agent", return_value=fake_agent
    ), patch("app.services.rag_service.get_rag_service"):
        resp = client.post(
            "/api/trip/tasks", json=VALID_REQUEST, headers=auth_header(user_a["token"])
        )
        task_id = resp.json()["task_id"]
        # 等任务完成 (历史保存发生在完成时)
        for _ in range(50):
            s = client.get(f"/api/trip/tasks/{task_id}").json()
            if s["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert s["status"] == "completed", s

    # A 能看到自己的记录
    list_a = client.get("/api/history", headers=auth_header(user_a["token"])).json()
    assert list_a["success"]
    my_records = [r for r in list_a["data"] if r["city"] == "深圳"]
    assert len(my_records) >= 1
    record_id = my_records[0]["id"]

    # A 能查详情
    detail = client.get(
        f"/api/history/{record_id}", headers=auth_header(user_a["token"])
    )
    assert detail.status_code == 200

    # B 查同一条 → 404 (防越权探测, 不暴露记录存在性)
    detail_b = client.get(
        f"/api/history/{record_id}", headers=auth_header(user_b["token"])
    )
    assert detail_b.status_code == 404

    # B 删同一条 → 404, 记录仍在
    del_b = client.delete(
        f"/api/history/{record_id}", headers=auth_header(user_b["token"])
    )
    assert del_b.status_code == 404
    assert (
        client.get(f"/api/history/{record_id}", headers=auth_header(user_a["token"])).status_code
        == 200
    )

    # A 自己删除 → 成功
    del_a = client.delete(
        f"/api/history/{record_id}", headers=auth_header(user_a["token"])
    )
    assert del_a.status_code == 200
    assert del_a.json()["success"]


def test_anonymous_task_record_not_in_user_history(client: TestClient):
    """匿名创建的任务记录 (user_id=None) 不会出现在任何登录用户的历史里"""
    import time

    user = login(client, "test_code_anon_check")
    fake_agent = MagicMock()
    fake_agent.plan_trip.return_value = make_fake_plan("广州")

    with patch(
        "app.agents.trip_planner_agent.get_trip_planner_agent", return_value=fake_agent
    ), patch("app.services.rag_service.get_rag_service"):
        resp = client.post("/api/trip/tasks", json={**VALID_REQUEST, "city": "广州"})
        task_id = resp.json()["task_id"]
        for _ in range(50):
            s = client.get(f"/api/trip/tasks/{task_id}").json()
            if s["status"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert s["status"] == "completed", s

    history = client.get("/api/history", headers=auth_header(user["token"])).json()
    assert all(r["city"] != "广州" for r in history["data"])
