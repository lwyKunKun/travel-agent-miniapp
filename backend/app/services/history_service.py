"""历史行程记录服务: 保存/查询/删除用户的历史旅行计划"""

import json
import logging
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..db.models import TripRecord
from ..models.schemas import TripPlan, TripRequest

logger = logging.getLogger(__name__)


def create_trip_record(
    db: Session, request: TripRequest, trip_plan: TripPlan, user_id: Optional[int] = None
) -> TripRecord:
    """保存一条旅行计划历史记录 (行程生成成功后调用)

    Args:
        user_id: 归属用户 ID (小程序登录用户); None 表示匿名 (Web 端)
    """
    record = TripRecord(
        user_id=user_id,
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        travel_days=request.travel_days,
        transportation=request.transportation,
        accommodation=request.accommodation,
        preferences=json.dumps(request.preferences, ensure_ascii=False),
        free_text_input=request.free_text_input or "",
        plan_json=trip_plan.model_dump_json(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(f"💾 历史记录已保存: id={record.id}, 城市={record.city}")
    return record


def list_trip_records(
    db: Session,
    page: int = 1,
    page_size: int = 10,
    city: Optional[str] = None,
    user_id: Optional[int] = None,
):
    """分页查询历史记录 (按创建时间倒序)

    Args:
        user_id: 指定时只返回该用户的记录 (小程序端用户隔离);
                 None 时返回全部 (兼容旧行为, 仅供内部/测试用)

    Returns:
        (records, total): 记录列表与总条数
    """
    query = select(TripRecord)
    if user_id is not None:
        query = query.where(TripRecord.user_id == user_id)
    if city:
        query = query.where(TripRecord.city.contains(city))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = db.scalars(
        query.order_by(desc(TripRecord.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(records), total


def get_trip_record(
    db: Session, record_id: int, user_id: Optional[int] = None
) -> Optional[TripRecord]:
    """按 id 查询历史记录

    Args:
        user_id: 指定时校验归属 (不是该用户的记录视为不存在, 防越权访问)
    """
    record = db.get(TripRecord, record_id)
    if record is None:
        return None
    if user_id is not None and record.user_id != user_id:
        return None
    return record


def update_trip_record(
    db: Session, record_id: int, trip_plan: TripPlan, user_id: Optional[int] = None
) -> Optional[TripRecord]:
    """更新历史记录的行程计划 (前端编辑保存后持久化; user_id 指定时校验归属)"""
    record = get_trip_record(db, record_id, user_id)
    if record is None:
        return None
    record.plan_json = trip_plan.model_dump_json()
    db.commit()
    db.refresh(record)
    logger.info(f"✏️  历史记录已更新: id={record_id}")
    return record


def delete_trip_record(db: Session, record_id: int, user_id: Optional[int] = None) -> bool:
    """删除历史记录 (user_id 指定时校验归属), 返回是否删除成功"""
    record = get_trip_record(db, record_id, user_id)
    if record is None:
        return False
    db.delete(record)
    db.commit()
    logger.info(f"🗑️  历史记录已删除: id={record_id}")
    return True


def trip_record_to_summary(record: TripRecord) -> dict:
    """转列表摘要 (不含完整行程, 减少传输量)"""
    try:
        plan = json.loads(record.plan_json)
    except json.JSONDecodeError:
        plan = {}

    return {
        "id": record.id,
        "city": record.city,
        "start_date": record.start_date,
        "end_date": record.end_date,
        "travel_days": record.travel_days,
        "transportation": record.transportation,
        "accommodation": record.accommodation,
        "preferences": json.loads(record.preferences or "[]"),
        "created_at": record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "attraction_count": sum(
            len(day.get("attractions", [])) for day in plan.get("days", [])
        ),
        "budget_total": (plan.get("budget") or {}).get("total", 0),
    }
