"""旅行请求日期与天数校验测试。"""

import pytest
from pydantic import ValidationError

from app.models.schemas import TripRequest


BASE_REQUEST = {
    "city": "北京",
    "start_date": "2026-08-01",
    "end_date": "2026-08-03",
    "travel_days": 3,
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["历史文化"],
    "free_text_input": "",
}


def make_request(**updates) -> TripRequest:
    return TripRequest(**{**BASE_REQUEST, **updates})


@pytest.mark.parametrize(
    ("start_date", "end_date", "travel_days"),
    [
        ("2026-08-01", "2026-08-01", 1),
        ("2026-08-30", "2026-09-02", 4),
        ("2028-02-28", "2028-03-01", 3),
        ("2026-08-01", "2026-08-30", 30),
    ],
)
def test_trip_request_accepts_valid_date_ranges(start_date, end_date, travel_days):
    request = make_request(
        start_date=start_date,
        end_date=end_date,
        travel_days=travel_days,
    )
    assert request.travel_days == travel_days


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"start_date": "2026-8-01"}, "start_date 必须为 YYYY-MM-DD 格式"),
        ({"end_date": "2026/08/03"}, "end_date 必须为 YYYY-MM-DD 格式"),
        ({"end_date": "2026-02-30"}, "end_date 必须为有效的 YYYY-MM-DD 日期"),
        (
            {"start_date": "2026-08-04", "end_date": "2026-08-03"},
            "end_date 不能早于 start_date",
        ),
        ({"travel_days": 2}, "travel_days 必须与起止日期包含的自然日天数一致"),
        ({"travel_days": 4}, "travel_days 必须与起止日期包含的自然日天数一致"),
    ],
)
def test_trip_request_rejects_invalid_date_ranges(updates, message):
    with pytest.raises(ValidationError, match=message):
        make_request(**updates)


@pytest.mark.parametrize("travel_days", [0, 31])
def test_trip_request_rejects_out_of_range_days(travel_days):
    with pytest.raises(ValidationError):
        make_request(travel_days=travel_days)
