"""JWT token handler for access and refresh tokens."""

from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import jwt
except ImportError:
    raise ImportError(
        "PyJWT is required for JWT handling. "
        "Install it with: pip install PyJWT"
    )

from ..core.config import settings
from ..core.errors import ConfigError

# Default expiration times
DEFAULT_ACCESS_EXPIRE_MINUTES = 30
DEFAULT_REFRESH_EXPIRE_DAYS = 7


def _get_jwt_secret() -> str:
    """Get JWT secret from settings, raise ConfigError if missing."""
    secret = getattr(settings, "jwt_secret", None)
    if not secret:
        raise ConfigError(
            "JWT_SECRET is not configured. "
            "Set the JWT_SECRET environment variable."
        )
    return secret


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    创建 JWT access_token。

    Args:
        data (dict): 包含 user_id, company_id, role 等
        expires_delta (timedelta, optional): 过期时间，默认 30 分钟

    Returns:
        str: JWT token 字符串

    Raises:
        ValueError: jwt_secret 未配置时
    """
    secret = _get_jwt_secret()
    algorithm = getattr(settings, "jwt_algorithm", "HS256")
    expire_minutes = getattr(settings, "jwt_access_token_expire_minutes", DEFAULT_ACCESS_EXPIRE_MINUTES)

    if expires_delta is None:
        expires_delta = timedelta(minutes=expire_minutes)

    expire = datetime.now(timezone.utc) + expires_delta

    payload = {
        **data,
        "exp": expire,
        "type": "access",
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token


def create_refresh_token(data: dict) -> str:
    """
    创建 JWT refresh_token。

    Args:
        data (dict): 包含 user_id, token_id 等

    Returns:
        str: JWT refresh_token 字符串（7天有效期）
    """
    secret = _get_jwt_secret()
    algorithm = getattr(settings, "jwt_algorithm", "HS256")
    expire_days = getattr(settings, "jwt_refresh_token_expire_days", DEFAULT_REFRESH_EXPIRE_DAYS)

    expire = datetime.now(timezone.utc) + timedelta(days=expire_days)

    payload = {
        **data,
        "exp": expire,
        "type": "refresh",
    }

    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token


def verify_token(token: str) -> dict:
    """
    验证 JWT token 并返回 payload。

    Args:
        token (str): JWT token 字符串

    Returns:
        dict: token payload

    Raises:
        JWTError: token 无效或过期
    """
    secret = _get_jwt_secret()
    algorithm = getattr(settings, "jwt_algorithm", "HS256")

    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        raise jwt.InvalidTokenError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise jwt.InvalidTokenError(f"Invalid token: {e}")


def decode_token(token: str) -> Optional[dict]:
    """
    解码 token（不验证），用于获取 payload 而不抛异常。

    Args:
        token (str): JWT token 字符串

    Returns:
        dict | None: payload 或 None
    """
    try:
        # Decode without verification - only for reading payload
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except jwt.InvalidTokenError:
        return None