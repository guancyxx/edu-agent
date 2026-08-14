"""Auth router — user registration, login, and token refresh."""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.utils.auth import hash_password, verify_password, create_access_token, decode_access_token

logger = logging.getLogger("edu-agent.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


# ── Request/Response Models ────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    email: Optional[str] = None
    role: str = Field(default="student", pattern="^(student|parent|teacher)$")
    grade: int = Field(default=7, ge=1, le=12)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: str
    username: str
    email: Optional[str]
    role: str
    grade: int
    display_name: Optional[str]

    model_config = {"from_attributes": True}


# ── Endpoints ──────────────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user."""
    # Check if username exists
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already registered")

    user = User(
        id=uuid.uuid4(),
        username=req.username,
        email=req.email,
        password_hash=hash_password(req.password),
        role=req.role,
        grade=req.grade,
        display_name=req.display_name or req.username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(str(user.id))
    logger.info("User registered: %s (role=%s)", user.username, user.role)

    return AuthResponse(
        access_token=token,
        user=UserOut(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role,
            grade=user.grade,
            display_name=user.display_name,
        ),
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with username + password."""
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.is_disabled:
        raise HTTPException(status_code=403, detail="Account disabled")

    token = create_access_token(str(user.id))
    logger.info("User logged in: %s", user.username)

    return AuthResponse(
        access_token=token,
        user=UserOut(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role,
            grade=user.grade,
            display_name=user.display_name,
        ),
    )


# ── Dependency: get current user ───────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that extracts and validates the JWT bearer token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
