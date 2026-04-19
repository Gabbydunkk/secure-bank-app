"""
User self-service router.

Endpoints:
  PATCH  /users/me                  -> update own profile
  GET    /users/me/devices          -> list known devices for current user
  DELETE /users/me/devices/{id}     -> remove known device for current user
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.models.database import get_db
from app.models.user import User
from app.schemas.user import (
    KnownDeviceListResponse,
    KnownDeviceResponse,
    UserProfileUpdate,
    UserResponse,
)
from app.services import auth_service, device_service


router = APIRouter(prefix="/users", tags=["users"])


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update current user's profile",
)
def update_me(
    body: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    user = auth_service.update_profile(
        db,
        current_user,
        first_name=body.first_name,
        last_name=body.last_name,
        phone_number=body.phone_number,
        date_of_birth=body.date_of_birth,
    )
    return UserResponse.model_validate(user, from_attributes=True)


@router.get(
    "/me/devices",
    response_model=KnownDeviceListResponse,
    status_code=status.HTTP_200_OK,
    summary="List known devices for current user",
)
def list_my_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnownDeviceListResponse:
    devices = device_service.get_known_devices(db, current_user.id)
    rows = [KnownDeviceResponse.model_validate(d, from_attributes=True) for d in devices]
    return KnownDeviceListResponse(items=rows, devices=rows, total=len(rows))


@router.delete(
    "/me/devices/{device_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove one known device for current user",
)
def remove_my_device(
    device_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    removed = device_service.remove_device(db, current_user.id, device_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return {"message": "Device removed successfully"}
