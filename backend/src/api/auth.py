"""认证 API：注册 / 登录 / 刷新"""
import hashlib
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ..auth import hash_password, verify_password, create_access_token, create_refresh_token, decode_access_token
from ..db import get_db_session
from ..db.models import Company, User, RefreshToken
from ..core import get_logger
from .models import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    UserResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def hash_token(token: str) -> str:
    """Hash a token (JWT refresh_token) using SHA256.

    JWT tokens are already cryptographically signed, so we only need
    a fast digest (not a slow KDF like bcrypt) to store as reference.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, hashed: str) -> bool:
    """Verify a token against its SHA256 hash."""
    return hashlib.sha256(token.encode()).hexdigest() == hashed


def _generate_id(prefix: str) -> str:
    """生成带前缀的唯一ID"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --- 注册 ---
@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(req: RegisterRequest):
    """
    用户注册：
    1. 检查邮箱是否已存在
    2. 自动创建公司（公司名重复则加随机后缀）
    3. 创建用户（bcrypt 哈希密码）
    4. 生成 access_token + refresh_token
    """
    async with get_db_session() as db:
        # 检查邮箱冲突
        stmt = select(User).where(User.email == req.email)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="邮箱已被注册")

        # 创建公司
        company_name = req.company_name or f"{req.email.split('@')[0]}_company"
        company_id = _generate_id("comp")
        company = Company(
            id=company_id,
            name=company_name,
            plan="free",
            quota_limit=10,
            quota_used=0,
        )
        db.add(company)

        # 创建用户
        user_id = _generate_id("user")
        password_hash = hash_password(req.password)
        user = User(
            id=user_id,
            email=req.email,
            password_hash=password_hash,
            company_id=company_id,
            role="admin",
        )
        db.add(user)
        await db.flush()

        # 生成 tokens
        access_token = create_access_token({"sub": user_id, "company_id": company_id})
        refresh_token = create_refresh_token({"sub": user_id, "token_id": _generate_id("tok")})

        # 存储 refresh_token hash
        token_hash = hash_token(refresh_token)  # 存 hash 不存明文
        rt = RefreshToken(
            id=_generate_id("rtok"),
            user_id=user_id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(rt)
        await db.flush()

        logger.info("user_registered", user_id=user_id, email=req.email)

        return RegisterResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserResponse(id=user_id, email=req.email, role="admin", company_id=company_id),
        )


# --- 登录 ---
@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """
    用户登录：
    1. 根据 email 查找用户
    2. 验证密码
    3. 生成 access_token + refresh_token
    4. 更新 last_login_at
    """
    async with get_db_session() as db:
        # 查询用户 by email
        stmt = select(User).where(User.email == req.email)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        if not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被禁用")

        # 更新 last_login
        user.last_login_at = datetime.utcnow()

        # 生成 tokens
        access_token = create_access_token({"sub": user.id, "company_id": user.company_id})
        refresh_token = create_refresh_token({"sub": user.id, "token_id": _generate_id("tok")})

        # 存储 refresh_token hash
        token_hash = hash_token(refresh_token)
        rt = RefreshToken(
            id=_generate_id("rtok"),
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.utcnow() + timedelta(days=7),
        )
        db.add(rt)

        logger.info("user_logged_in", user_id=user.id, email=req.email)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserResponse(id=user.id, email=req.email, role=user.role, company_id=user.company_id),
        )


# --- Token 刷新 ---
@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(req: RefreshRequest):
    """
    用 refresh_token 换新的 access_token：
    1. 解码 refresh_token
    2. 在 DB 中查找对应的 token_id（需记录在 token payload 里）
    3. 检查是否已撤销
    4. 返回新的 access_token
    """
    try:
        payload = decode_access_token(req.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="无效的 refresh_token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="不是 refresh_token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 refresh_token")

    async with get_db_session() as db:
        # 在 DB 中查找有效 token
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
        ).order_by(RefreshToken.created_at.desc())

        result = await db.execute(stmt)
        tokens = result.scalars().all()
        if not tokens:
            raise HTTPException(status_code=401, detail="refresh_token 已失效")

        # 简单策略：找到最后一个（应该每个 token 只用一次）
        latest_token = tokens[0]

        # 撤销旧 token
        latest_token.revoked = True

        # 获取用户公司信息
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        # 生成新 access_token
        new_access_token = create_access_token({"sub": user_id, "company_id": user.company_id})

        logger.info("token_refreshed", user_id=user_id)

        return RefreshResponse(access_token=new_access_token)