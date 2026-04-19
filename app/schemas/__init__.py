"""
Pydantic schemas for Secure Banking API.
Import schemas from this module for clean usage in endpoints.
"""
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserLogin,
    UserResponse,
    AccountStatus,
)
from app.schemas.auth import (
    Token,
    TokenPayload,
    TokenType,
    LoginResponse,
    MFACodeVerify,
    RefreshTokenRequest,
    SCOPE_READ_ONLY,
    SCOPE_TRANSFER_AUTHORIZED,
    SCOPE_MFA_ELEVATED,
)
from app.schemas.transaction import (
    TransactionCreate,
    TransactionResponse,
    TransactionListResponse,
    TransactionType,
    TransactionStatus,
    FraudCheckStatus,
)
from app.schemas.fraud import (
    FraudAlertCreate,
    FraudAlertResponse,
    FraudRuleInput,
    AlertType,
    FraudSeverity,
    FraudAlertStatus,
)
from app.schemas.audit import (
    AuditLogCreate,
    AuditLogResponse,
    AuditLogListResponse,
)

__all__ = [
    # User
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "AccountStatus",
    # Auth
    "Token",
    "TokenPayload",
    "TokenType",
    "LoginResponse",
    "MFACodeVerify",
    "RefreshTokenRequest",
    "SCOPE_READ_ONLY",
    "SCOPE_TRANSFER_AUTHORIZED",
    "SCOPE_MFA_ELEVATED",
    # Transaction
    "TransactionCreate",
    "TransactionResponse",
    "TransactionListResponse",
    "TransactionType",
    "TransactionStatus",
    "FraudCheckStatus",
    # Fraud
    "FraudAlertCreate",
    "FraudAlertResponse",
    "FraudRuleInput",
    "AlertType",
    "FraudSeverity",
    "FraudAlertStatus",
    # Audit
    "AuditLogCreate",
    "AuditLogResponse",
    "AuditLogListResponse",
]
