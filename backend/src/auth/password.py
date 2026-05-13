"""Password hashing utilities using bcrypt."""

from typing import Optional

try:
    import bcrypt
except ImportError:
    raise ImportError(
        "bcrypt is required for password hashing. "
        "Install it with: pip install bcrypt"
    )

# bcrypt rounds for balance between security and performance
_ROUNDS = 12


def hash_password(password: str) -> str:
    """
    使用 bcrypt 对密码进行哈希。

    Args:
        password (str): 明文密码

    Returns:
        str: bcrypt 哈希后的密码字符串

    Raises:
        ValueError: 密码为空时
    """
    if not password:
        raise ValueError("Password cannot be empty")

    salt = bcrypt.gensalt(rounds=_ROUNDS)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    验证密码是否匹配。

    Args:
        password (str): 明文密码
        password_hash (str): bcrypt 哈希

    Returns:
        bool: 匹配返回 True，否则 False
    """
    if not password or not password_hash:
        return False

    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        # Invalid hash format
        return False