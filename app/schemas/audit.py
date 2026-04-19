"""
Audit log schemas for comprehensive audit trail.
Aligns with schema.sql audit_logs table - supports Audit logging workflow.
"""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime
from typing import Any, Optional
import uuid


# ======================================
# AUDIT LOG (Audit logging)
# ======================================

class AuditLogCreate(BaseModel):
    """Schema for creating audit log entry - used by audit logging middleware/services."""
    user_id: Optional[uuid.UUID] = None
    action: str = Field(..., max_length=100)
    entity_type: Optional[str] = Field(None, max_length=50)
    entity_id: Optional[uuid.UUID] = None
    old_values: Optional[dict[str, Any]] = None
    new_values: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None


class AuditLogResponse(BaseModel):
    """Schema for returning audit log data."""
    id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[uuid.UUID] = None
    old_values: Optional[dict[str, Any]] = None
    new_values: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: bool
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """Paginated list of audit logs."""
    items: list[AuditLogResponse] = Field(default_factory=list)
    total: int
    # Legacy compatibility for clients expecting "logs".
    logs: list[AuditLogResponse] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_legacy_fields(self):
        if self.items and not self.logs:
            self.logs = list(self.items)
        elif self.logs and not self.items:
            self.items = list(self.logs)
        return self
