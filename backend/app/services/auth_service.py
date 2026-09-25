"""认证服务: 微信登录 (code2session) + JWT 签发/校验 + 用户管理

设计要点:
- wx_appid 未配置时进入 mock 登录模式: code2session 不调微信接口,
  用 code 直接派生一个稳定的假 openid (同一 code 得到同一用户),
  方便本地开发/微信开发者工具未绑定 AppID 时联调, 与项目"优雅降级"风格一致。
- JWT 用 PyJWT HS256 签发, payload 含 user_id/openid/exp。
- jwt_secret 未配置时启动生成随机密钥并告警: 单机开发可用,
  但进程重启后旧 token 全部失效, 生产环境必须显式配置。
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.exceptions import BizException
from ..db.models import User

logger = logging.getLogger(__name__)

# 微信 code2session 接口
WX_CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"

_JWT_ALGORITHM = "HS256"

# jwt_secret 未配置时的随机密钥 (进程级, 重启即换)
_random_secret: Optional[str] = None


def _get_jwt_secret() -> str:
    """获取 JWT 签名密钥: 优先 .env 配置, 否则用进程级随机密钥"""
    global _random_secret
    secret = get_settings().jwt_secret
    if secret:
        return secret
    if _random_secret is None:
        _random_secret = secrets.token_hex(32)
        logger.warning(
            "⚠️ JWT_SECRET 未配置, 已生成随机密钥 (进程重启后旧 token 失效; 生产环境请在 .env 显式配置)"
        )
    return _random_secret


def is_mock_mode() -> bool:
    """是否为 mock 登录模式 (未配置微信 AppID)"""
    return not get_settings().wx_appid


# ============ 微信 code2session ============

def code2session(code: str) -> str:
    """用 wx.login 的临时凭证 code 换取 openid

    Returns:
        openid: 微信用户在当前小程序下的唯一标识

    Raises:
        BizException: 微信接口报错 / mock 模式下 code 为空
    """
    settings = get_settings()

    # mock 模式: 不调微信接口, 用 code 派生稳定假 openid (同 code 同用户)
    if is_mock_mode():
        if not code:
            raise BizException("登录凭证 code 不能为空", status_code=400)
        fake_openid = "mock_" + hashlib.sha256(code.encode()).hexdigest()[:24]
        logger.info(f"🧪 mock 登录模式 (未配置 WX_APPID): openid={fake_openid[:16]}...")
        return fake_openid

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                WX_CODE2SESSION_URL,
                params={
                    "appid": settings.wx_appid,
                    "secret": settings.wx_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
    except Exception as e:
        logger.error(f"❌ 调用微信 code2session 失败: {e}")
        raise BizException("微信登录服务暂不可用, 请稍后重试", status_code=502)

    # 微信错误码: 40029=code无效, 45011=频率限制, -1=系统繁忙 等
    if "openid" not in data:
        errcode = data.get("errcode")
        errmsg = data.get("errmsg", "未知错误")
        logger.warning(f"⚠️ code2session 返回错误: errcode={errcode}, errmsg={errmsg}")
        raise BizException(f"微信登录失败: {errmsg} (errcode={errcode})", status_code=401)

    return data["openid"]


# ============ 用户管理 ============

def get_or_create_user(db: Session, openid: str) -> Tuple[User, bool]:
    """按 openid 查用户, 不存在则创建

    Returns:
        (user, is_new): 用户对象与是否新注册
    """
    user = db.scalar(select(User).where(User.openid == openid))
    if user is not None:
        # 刷新最后登录时间
        user.last_login_at = datetime.now()
        db.commit()
        return user, False

    user = User(openid=openid)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"👤 新用户注册: id={user.id}, openid={openid[:12]}...")
    return user, True


# ============ JWT ============

def create_token(user: User) -> Tuple[str, int]:
    """签发 JWT

    Returns:
        (token, expires_in_seconds)
    """
    settings = get_settings()
    expires_seconds = settings.jwt_expire_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "openid": user.openid,
        "iat": now,
        "exp": now + timedelta(seconds=expires_seconds),
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)
    return token, expires_seconds


def decode_token(token: str) -> dict:
    """校验并解析 JWT, 失败抛 401 业务异常"""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise BizException("登录已过期, 请重新登录", status_code=401)
    except jwt.InvalidTokenError as e:
        raise BizException(f"无效的登录凭证: {e}", status_code=401)


def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
    """按 ID 查用户"""
    return db.get(User, user_id)
