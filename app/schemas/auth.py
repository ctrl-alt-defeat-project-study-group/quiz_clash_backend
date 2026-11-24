"""
Pydantic schemas for authentication and user profile endpoints.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)


class RegisterPendingResponse(BaseModel):
    message: str
    email: EmailStr
    display_name: str
    verification_required: bool = True


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=128)
    email: Optional[EmailStr] = None


class EmailRequest(BaseModel):
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: Optional[str] = Field(default=None, max_length=128)
    new_password: str = Field(..., min_length=1, max_length=128)


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    avatar_url: Optional[str] = None
    role: Literal["user", "admin"]
    is_active: bool
    email_verified_at: Optional[datetime] = None
    has_password: bool = True
    oauth_providers: List[str] = Field(default_factory=list)


class OAuthProvidersResponse(BaseModel):
    providers: List[str]


class MessageResponse(BaseModel):
    message: str
