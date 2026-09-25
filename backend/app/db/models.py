"""ORM 数据模型"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    """微信用户

    小程序静默登录: wx.login code → code2session 拿 openid → 建/查用户 → 签发 JWT。
    openid 是微信用户在当前小程序下的唯一标识, 天然适合做用户主键关联。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 昵称/头像需要用户授权才拿得到, 静默登录拿不到, 预留字段
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_url: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TripRecord(Base):
    """旅行计划历史记录

    每次成功生成行程后自动保存一份, 供历史查询 + RAG 知识库使用。
    user_id 为空表示 Web 端匿名生成 (历史数据/未登录场景), 小程序端登录后必填。
    """

    __tablename__ = "trip_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 归属用户 (可空: 兼容 Web 端匿名与旧数据; 小程序端查询按此字段隔离)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, default=None)
    city: Mapped[str] = mapped_column(String(64), index=True)
    start_date: Mapped[str] = mapped_column(String(16))
    end_date: Mapped[str] = mapped_column(String(16))
    travel_days: Mapped[int] = mapped_column(Integer, default=1)
    transportation: Mapped[str] = mapped_column(String(32), default="")
    accommodation: Mapped[str] = mapped_column(String(32), default="")
    preferences: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组字符串
    free_text_input: Mapped[str] = mapped_column(Text, default="")
    plan_json: Mapped[str] = mapped_column(Text)  # 完整行程计划 JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )
