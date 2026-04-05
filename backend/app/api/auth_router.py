from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status

from app.api.auth import get_current_user
from app.api.auth_schemas import (
    ForgotPasswordRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SignInRequest,
    SignOutRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserProfileResponse,
    VerifyEmailRequest,
)
from app.api.dependencies import get_auth_service
from app.db.models import User
from app.services.auth import (
    AuthService,
    InvalidCredentialsError,
    InvalidTokenError,
    UserBlockedError,
    UserNotVerifiedError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(tags=["users"])
profile_router = APIRouter(tags=["profile"])


def _refresh_token_from_request(request: Request, body_token: str | None) -> str | None:
    return body_token or request.cookies.get("refresh_token")


def _set_refresh_cookie(response: Response, token: str, request: Request) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key="refresh_token",
        path="/api/auth",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/register", response_model=MessageResponse)
async def register(
    payload: RegisterRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    detail = await auth_service.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    return MessageResponse(detail=detail)


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    try:
        await auth_service.verify_email(token=payload.token)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return MessageResponse(detail="Email verified successfully.")


@router.post("/sign-in", response_model=TokenResponse)
async def sign_in(
    request: Request,
    response: Response,
    payload: SignInRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    try:
        token_pair = await auth_service.sign_in(
            email=payload.email,
            password=payload.password,
            device_info=request.headers.get("user-agent"),
        )
    except InvalidCredentialsError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except (UserNotVerifiedError, UserBlockedError) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error

    _set_refresh_cookie(response, token_pair.refresh_token, request)
    return TokenResponse(access_token=token_pair.access_token, token_type=token_pair.token_type)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    payload: RefreshRequest | None = Body(default=None),
) -> TokenResponse:
    refresh_token = _refresh_token_from_request(request, payload.refresh_token if payload else None)
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    try:
        token_pair = await auth_service.refresh(
            refresh_token=refresh_token,
            device_info=request.headers.get("user-agent"),
        )
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error

    _set_refresh_cookie(response, token_pair.refresh_token, request)
    return TokenResponse(access_token=token_pair.access_token, token_type=token_pair.token_type)


@router.post("/sign-out", response_model=MessageResponse)
async def sign_out(
    request: Request,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    payload: SignOutRequest | None = Body(default=None),
) -> MessageResponse:
    await auth_service.sign_out(
        refresh_token=_refresh_token_from_request(
            request,
            payload.refresh_token if payload else None,
        )
    )
    _clear_refresh_cookie(response, request)
    return MessageResponse(detail="Signed out successfully.")


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    detail = await auth_service.forgot_password(email=payload.email)
    return MessageResponse(detail=detail)


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> MessageResponse:
    try:
        await auth_service.reset_password(token=payload.token, new_password=payload.new_password)
    except InvalidTokenError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return MessageResponse(detail="Password reset successfully.")


@users_router.get("/api/users/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    user, profile = await auth_service.get_user_with_profile(user_id=current_user.id)
    return UserProfileResponse.from_models(user, profile)


@profile_router.patch("/api/profile", response_model=UserProfileResponse)
async def patch_current_user_profile(
    payload: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserProfileResponse:
    user, profile = await auth_service.update_profile(
        user_id=current_user.id,
        display_name=payload.display_name,
        avatar_url=payload.avatar_url,
        update_display_name="display_name" in payload.model_fields_set,
        update_avatar_url="avatar_url" in payload.model_fields_set,
    )
    return UserProfileResponse.from_models(user, profile)
