"""认证路由: 微信小程序登录

POST /api/auth/login  { code } → { token, user_id, is_new_user, mock_mode }
GET  /api/auth/me     (需登录)  → 当前用户信息
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.database import get_db
from ...db.models import User
from ..deps import get_current_user
from ...services import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])

logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    """微信登录请求"""
    code: str = Field(..., min_length=1, description="wx.login 返回的临时登录凭证")


class LoginResponse(BaseModel):
    """登录响应"""
    success: bool = True
    token: str = Field(..., description="JWT, 后续请求放 Authorization: Bearer <token>")
    expires_in: int = Field(..., description="token 有效期(秒)")
    user_id: int
    is_new_user: bool = Field(..., description="是否新注册用户")
    mock_mode: bool = Field(default=False, description="是否 mock 登录模式(未配置 WX_APPID)")


class UserInfoResponse(BaseModel):
    """当前用户信息"""
    success: bool = True
    user_id: int
    nickname: str
    avatar_url: str
    created_at: str


@router.post("/login", response_model=LoginResponse, summary="微信登录")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """小程序静默登录: code → openid → 建/查用户 → 签发 JWT

    前端在 App onLaunch 时调用 (uni.login 拿 code), token 存本地,
    之后所有请求自动带 Authorization 头。
    """
    openid = auth_service.code2session(body.code)
    user, is_new = auth_service.get_or_create_user(db, openid)
    token, expires_in = auth_service.create_token(user)
    logger.info(f"🔐 登录成功: user_id={user.id}, 新用户={is_new}, mock={auth_service.is_mock_mode()}")
    return LoginResponse(
        token=token,
        expires_in=expires_in,
        user_id=user.id,
        is_new_user=is_new,
        mock_mode=auth_service.is_mock_mode(),
    )


@router.get("/me", response_model=UserInfoResponse, summary="当前用户信息")
def me(user: User = Depends(get_current_user)):
    """校验 token 有效性并返回用户信息 (前端可用于启动时检查登录态)"""
    return UserInfoResponse(
        user_id=user.id,
        nickname=user.nickname or f"旅行者{user.id}",
        avatar_url=user.avatar_url,
        created_at=user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )
