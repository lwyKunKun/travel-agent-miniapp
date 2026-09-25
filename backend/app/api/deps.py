"""FastAPI 认证依赖: 从 Authorization 头解析 JWT 得到当前用户

用法:
    @router.get("/xxx")
    def xxx(user: User = Depends(get_current_user)):  # 必须登录
    def yyy(user: Optional[User] = Depends(get_optional_user)):  # 可选登录
"""

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..core.exceptions import BizException
from ..db.database import get_db
from ..db.models import User
from ..services import auth_service


def _extract_token(request: Request) -> Optional[str]:
    """从 Authorization: Bearer <token> 头提取 token"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return token or None
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """必须登录: 无 token / token 无效 / 用户不存在 → 401"""
    token = _extract_token(request)
    if not token:
        raise BizException("未登录: 缺少 Authorization 头", status_code=401)

    payload = auth_service.decode_token(token)
    user = auth_service.get_user_by_id(db, int(payload["sub"]))
    if user is None:
        raise BizException("用户不存在, 请重新登录", status_code=401)
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """可选登录: 带合法 token 返回用户, 否则 None (不抛异常)

    用于旅行规划接口: Web 端匿名可用, 小程序端带 token 时把历史记录挂到用户名下。
    """
    token = _extract_token(request)
    if not token:
        return None
    try:
        payload = auth_service.decode_token(token)
        return auth_service.get_user_by_id(db, int(payload["sub"]))
    except BizException:
        # token 过期/无效不阻断匿名流程
        return None
