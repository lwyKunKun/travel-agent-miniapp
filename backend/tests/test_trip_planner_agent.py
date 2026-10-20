"""长行程分块、校验、局部重试与局部兜底测试。"""

import json
from types import SimpleNamespace

import pytest

from app.agents.trip_planner_agent import MultiAgentTripPlanner
from app.models.schemas import (
    Attraction,
    DayPlan,
    Location,
    Meal,
    POIInfo,
    TripPlan,
    TripRequest,
    WeatherInfo,
)


def make_request(days: int) -> TripRequest:
    from datetime import date, timedelta

    start = date(2026, 8, 1)
    end = start + timedelta(days=days - 1)
    return TripRequest(
        city="北京",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        travel_days=days,
        transportation="公共交通",
        accommodation="经济型酒店",
        preferences=["历史文化"],
        free_text_input="",
    )


def make_plan(request, dates, start_index=0, prefix="AI") -> TripPlan:
    days = []
    for offset, current_date in enumerate(dates):
        index = start_index + offset
        days.append(
            DayPlan(
                date=current_date,
                day_index=index,
                description=f"{prefix}第{index + 1}天",
                transportation=request.transportation,
                accommodation=request.accommodation,
                attractions=[
                    Attraction(
                        name=f"{prefix}景点{index}-1",
                        address="测试地址",
                        location=Location(longitude=116.3, latitude=39.9),
                        visit_duration=120,
                        description="测试景点",
                    ),
                    Attraction(
                        name=f"{prefix}景点{index}-2",
                        address="测试地址",
                        location=Location(longitude=116.4, latitude=39.8),
                        visit_duration=120,
                        description="测试景点",
                    ),
                ],
                meals=[
                    Meal(type="breakfast", name=f"{prefix}早餐{index}"),
                    Meal(type="lunch", name=f"{prefix}午餐{index}"),
                    Meal(type="dinner", name=f"{prefix}晚餐{index}"),
                ],
            )
        )
    return TripPlan(
        city=request.city,
        start_date=dates[0],
        end_date=dates[-1],
        days=days,
        weather_info=[],
        overall_suggestions=f"{prefix}分块建议",
    )


class FakeAmapService:
    @staticmethod
    def geocode(city):
        return [{"location": "116.3,39.9"}]

    @staticmethod
    def _parse_location(value):
        longitude, latitude = value.split(",")
        return Location(longitude=float(longitude), latitude=float(latitude))

    @staticmethod
    def search_poi(keywords, city):
        return []


def make_agent() -> MultiAgentTripPlanner:
    agent = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    agent.amap_service = FakeAmapService()
    return agent


def make_pois(prefix, count):
    return [
        POIInfo(
            id=str(index),
            name=f"{prefix}{index}",
            type="景点" if prefix == "景点" else "餐饮",
            address="测试地址",
            location=Location(longitude=116.3 + index / 100, latitude=39.9),
        )
        for index in range(count)
    ]


@pytest.mark.parametrize(
    ("days", "sizes"),
    [(1, [1]), (5, [5]), (6, [5, 1]), (10, [5, 5]), (11, [5, 5, 1]), (30, [5] * 6)],
)
def test_split_date_chunks(days, sizes):
    chunks = make_agent()._split_date_chunks(make_request(days))
    assert [len(chunk) for chunk in chunks] == sizes
    assert [day for chunk in chunks for day in chunk][0] == "2026-08-01"


def test_build_query_limits_dates_and_carries_used_names(monkeypatch):
    agent = make_agent()
    request = make_request(6)
    fake_rag = SimpleNamespace(build_rag_context=lambda request: "")
    monkeypatch.setattr("app.services.rag_service.get_rag_service", lambda: fake_rag)
    state = {
        "attraction_pois": make_pois("景点", 2),
        "hotel_pois": [],
        "meal_pois": make_pois("餐厅", 3),
        "weather_info": [
            WeatherInfo(date="2026-08-01", day_weather="晴"),
            WeatherInfo(date="2026-08-06", day_weather="雨"),
        ],
    }

    query = agent._build_planner_query(
        request,
        state,
        chunk_dates=["2026-08-06"],
        chunk_start_index=5,
        used_attractions=["故宫博物院"],
        used_meals=["护国寺小吃"],
    )

    assert "只生成 2026-08-06 至 2026-08-06" in query
    assert "2026-08-06，day_index=5" in query
    assert "故宫博物院" in query
    assert "护国寺小吃" in query
    assert "2026-08-06: 白天雨" in query
    assert "2026-08-01: 白天晴" not in query


def test_generate_chunk_retries_only_current_chunk(monkeypatch):
    agent = make_agent()
    request = make_request(1)
    plan = make_plan(request, ["2026-08-01"])
    responses = iter(["不是JSON", plan.model_dump_json()])
    monkeypatch.setattr(agent, "_invoke_planner", lambda query: next(responses))
    monkeypatch.setattr(agent, "_build_planner_query", lambda *args, **kwargs: "分块需求")

    result = agent._generate_chunk(
        request,
        {},
        ["2026-08-01"],
        0,
        [],
        [],
    )

    assert len(result.days) == 1
    assert result.days[0].day_index == 0


def test_validate_chunk_rejects_reset_day_index():
    request = make_request(6)
    plan = make_plan(request, ["2026-08-06"], start_index=0)

    with pytest.raises(ValueError, match="day_index应为5"):
        MultiAgentTripPlanner._validate_chunk_plan(
            plan, request, ["2026-08-06"], 5
        )


def test_failed_chunk_uses_local_fallback_and_keeps_successful_chunk(monkeypatch):
    agent = make_agent()
    request = make_request(6)
    chunks = agent._split_date_chunks(request)
    first_plan = make_plan(request, chunks[0], prefix="成功")
    responses = iter([first_plan.model_dump_json(), "错误", "仍然错误"])
    calls = []

    def invoke(query):
        calls.append(query)
        return next(responses)

    monkeypatch.setattr(agent, "_invoke_planner", invoke)
    monkeypatch.setattr(agent, "_build_planner_query", lambda *args, **kwargs: "分块需求")
    state = {
        "request": request,
        "attraction_pois": make_pois("景点", 10),
        "hotel_pois": [],
        "meal_pois": make_pois("餐厅", 10),
        "weather_info": [],
    }

    result = agent._generate_trip_plan(state)
    plan = result["trip_plan"]

    assert result["error"] is False
    assert len(calls) == 3
    assert len(plan.days) == 6
    assert plan.days[0].description.startswith("成功")
    assert plan.days[5].day_index == 5
    # 兜底块描述需与全局第几天一致， 不能与 day_index 自相矛盾
    assert plan.days[5].description.startswith("第6天")
    assert plan.is_fallback is True
    assert "第2/2块" in plan.fallback_reason
    assert plan.budget is None


def test_merge_preserves_order_and_recalculates_top_level_fields():
    request = make_request(6)
    chunks = MultiAgentTripPlanner._split_date_chunks(request)
    first = make_plan(request, chunks[0], 0, "一")
    second = make_plan(request, chunks[1], 5, "二")

    merged = MultiAgentTripPlanner._merge_chunk_plans(request, [first, second])
    MultiAgentTripPlanner._validate_merged_plan(merged, request)

    assert [day.day_index for day in merged.days] == list(range(6))
    assert merged.start_date == request.start_date
    assert merged.end_date == request.end_date
    assert merged.weather_info == []
    assert merged.budget is None
    assert "一分块建议" in merged.overall_suggestions
    assert "二分块建议" in merged.overall_suggestions


def test_parse_json_response_accepts_code_fence():
    request = make_request(1)
    plan = make_plan(request, ["2026-08-01"])
    content = f"```json\n{json.dumps(plan.model_dump(), ensure_ascii=False)}\n```"

    parsed = MultiAgentTripPlanner._parse_json_response(content)

    assert parsed.city == "北京"
