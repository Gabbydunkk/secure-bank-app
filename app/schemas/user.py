"""
User Pydantic schemas for registration, login, and API responses.
Aligns with schema.sql and SQLAlchemy User model.
"""
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from datetime import datetime, date
from typing import Literal, Optional
import re
import uuid

# ======================================
# BASE SCHEMA FOR USER
# ======================================

class UserBase(BaseModel):
    """Shared user fields for create/update/response."""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone_number: Optional[str] = Field(None, max_length=20)
    date_of_birth: Optional[date] = None


# ======================================
# REGISTRATION SCHEMA (Registration endpoint)
# ======================================

# Valid roles — mirrors the DB CHECK constraint in User model.
# Defined once here so UserCreate and UserResponse share the same type.
UserRole = Literal["user", "analyst", "admin"]


class UserCreate(UserBase):
    """
    Schema for user registration with secure password validation.

    role defaults to "user" so normal self-service registration always
    produces a least-privilege account. Elevated roles ("analyst", "admin")
    must be assigned explicitly — typically by an admin endpoint or a
    DB seed script, never by the public registration form.
    """
    password: str = Field(..., min_length=12)
    role: UserRole = "user"

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def verify_age(cls, v: Optional[date]) -> Optional[date]:
        if v:
            today = date.today()
            age = today.year - v.year - (
                (today.month, today.day) < (v.month, v.day)
            )
            if age < 18:
                raise ValueError("Users must be at least 18 years old")
        return v


# ======================================
# LOGIN SCHEMA (Login endpoint)
# ======================================

class UserLogin(BaseModel):
    """Schema for login - email OR username + password."""
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    password: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def check_identifier_provided(self):
        if not self.email and not self.username:
            raise ValueError("Either email or username must be provided")
        return self


# ======================================
# RESPONSE SCHEMA
# ======================================

AccountStatus = Literal["active", "suspended", "locked", "closed"]


class UserResponse(UserBase):
    """
    Schema for returning user data — excludes password_hash.

    role is included so the client can render role-appropriate UI
    (e.g. show the analyst dashboard, hide admin controls for regular users).
    """
    id: uuid.UUID
    role: UserRole
    account_status: AccountStatus
    mfa_enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserProfileUpdate(BaseModel):
    """Self-service profile update payload (PATCH /users/me)."""
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone_number: Optional[str] = Field(None, max_length=20)
    date_of_birth: Optional[date] = None

    @model_validator(mode="after")
    def require_any_field(self):
        if (
            self.first_name is None
            and self.last_name is None
            and self.phone_number is None
            and self.date_of_birth is None
        ):
            raise ValueError("At least one profile field must be provided")
        return self


class KnownDeviceResponse(BaseModel):
    """Known device visible to the authenticated user."""
    id: uuid.UUID
    device_fingerprint: str
    device_name: Optional[str] = None
    device_type: Optional[str] = None
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    is_trusted: bool
    trust_expires_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class KnownDeviceListResponse(BaseModel):
    """Paginated-like list shape for known devices."""
    items: list[KnownDeviceResponse]
    total: int
    # Legacy compatibility for clients expecting "devices".
    devices: list[KnownDeviceResponse]
    
