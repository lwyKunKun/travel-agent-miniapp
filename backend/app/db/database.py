"""SQLAlchemy 数据库配置 (SQLite)"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 数据库文件路径: 默认 backend/data/trip_planner.db;
# 可用环境变量 TRIP_DB_PATH 覆盖 (测试用独立临时库, 不污染开发数据)
_default_db_path = Path(__file__).resolve().parents[2] / "data" / "trip_planner.db"
DB_PATH = Path(os.environ.get("TRIP_DB_PATH", str(_default_db_path)))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False: FastAPI 会把同步端点放到线程池执行,
# 不同线程可能复用同一个会话, 需要关闭 SQLite 的同线程检查。
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

# autocommit=False: 事务需显式 commit, 便于依赖注入统一管理
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """ORM 模型基类"""


def get_db():
    """FastAPI 依赖: 请求级数据库会话 (用完自动归还/关闭)"""
    ensure_tables()  # 兜底: 首次使用时自动建表, 不依赖 lifespan
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_tables_ready = False


def _migrate_schema() -> None:
    """轻量迁移 (幂等): 给已存在的旧表补新增列

    背景: create_all 只建缺失的表, 不会给已存在的表加列。
    老库的 trip_records 没有 user_id 列 (微信登录功能新增),
    用 SQLite 的 ALTER TABLE ADD COLUMN 补齐; 新库建表时已含该列, 检查后跳过。
    不引入 Alembic: 项目定位单机可跑, 列级增量迁移用原生 SQL 足够。
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "trip_records" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("trip_records")}
        if "user_id" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE trip_records ADD COLUMN user_id INTEGER"))
                conn.execute(
                    text("CREATE INDEX IF NOT EXISTS ix_trip_records_user_id ON trip_records (user_id)")
                )


def ensure_tables() -> None:
    """幂等建表 + 轻量迁移 (只执行一次)"""
    global _tables_ready
    if _tables_ready:
        return
    from . import models  # noqa: F401  确保模型注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    _migrate_schema()
    _tables_ready = True


def init_db() -> None:
    """显式初始化数据库 (应用启动时调用, 语义清晰)"""
    ensure_tables()
