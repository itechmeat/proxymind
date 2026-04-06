from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus
from app.persona.loader import PersonaContext
from app.services.conversation_memory import ConversationMemoryService
from app.services.promotions import PromotionsService

TEST_JWT_SECRET = SecretStr("test-jwt-secret-key-with-32-plus-chars")


@dataclass(slots=True)
class DeliveredEmail:
    html_body: str
    subject: str
    to: str


class CapturingEmailSender:
    def __init__(self) -> None:
        self.deliveries: list[DeliveredEmail] = []

    async def send(self, *, to: str, subject: str, html_body: str) -> None:
        self.deliveries.append(DeliveredEmail(to=to, subject=subject, html_body=html_body))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _extract_token(delivery: DeliveredEmail, *, route_path: str) -> str:
    start = delivery.html_body.index('href="') + len('href="')
    end = delivery.html_body.index('"', start)
    url = delivery.html_body[start:end]
    parsed = urlparse(url)
    assert parsed.path == route_path
    token = parse_qs(parsed.query).get("token", [None])[0]
    assert token is not None
    return token


async def _create_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SnapshotStatus,
) -> KnowledgeSnapshot:
    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name=f"Snapshot {status.value}",
            status=status,
        )
        session.add(snapshot)
        await session.commit()
        await session.refresh(snapshot)
        return snapshot


@pytest.fixture
def capturing_email_sender() -> CapturingEmailSender:
    return CapturingEmailSender()


@pytest.fixture
def auth_chat_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service: SimpleNamespace,
    mock_llm_service: SimpleNamespace,
    mock_rewrite_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
    capturing_email_sender: CapturingEmailSender,
) -> FastAPI:
    from app.api.auth_router import (
        profile_router,
        router as auth_router,
        users_router,
    )
    from app.api.chat import router as chat_router

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(profile_router)
    app.include_router(chat_router)
    app.state.settings = SimpleNamespace(
        cookie_secure=False,
        email_from="noreply@example.com",
        frontend_url="http://frontend.test",
        jwt_access_token_expire_minutes=15,
        jwt_refresh_token_expire_days=30,
        jwt_secret_key=TEST_JWT_SECRET,
        max_citations_per_response=5,
        max_promotions_per_response=1,
        min_retrieved_chunks=1,
        retrieval_context_budget=4096,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
    )
    app.state.arq_pool = mock_arq_pool
    app.state.conversation_memory_service = ConversationMemoryService(
        budget=4096,
        summary_ratio=0.3,
    )
    app.state.email_sender = capturing_email_sender
    app.state.llm_service = mock_llm_service
    app.state.persona_context = PersonaContext(
        identity="Test twin identity",
        soul="Test twin soul",
        behavior="Test twin behavior",
        config_commit_hash="test-commit-sha",
        config_content_hash="test-content-hash",
    )
    app.state.promotions_service = PromotionsService(promotions_text="")
    app.state.query_rewrite_service = mock_rewrite_service
    app.state.retrieval_service = mock_retrieval_service
    app.state.session_factory = session_factory
    return app


@pytest_asyncio.fixture
async def auth_chat_client(auth_chat_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=auth_chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_end_user_auth_flow_covers_register_verify_chat_refresh_sign_out_and_reset(
    auth_chat_client: httpx.AsyncClient,
    capturing_email_sender: CapturingEmailSender,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    email = "flow@example.com"
    password = "Start123!"
    new_password = "Updated123!"

    register_response = await auth_chat_client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "display_name": "Flow User",
        },
    )
    assert register_response.status_code == 200
    assert register_response.json()["detail"] == "Check your email to verify your account."
    assert len(capturing_email_sender.deliveries) == 1

    verify_token = _extract_token(
        capturing_email_sender.deliveries[-1],
        route_path="/auth/verify-email",
    )
    verify_response = await auth_chat_client.post(
        "/api/auth/verify-email",
        json={"token": verify_token},
    )
    assert verify_response.status_code == 200

    sign_in_response = await auth_chat_client.post(
        "/api/auth/sign-in",
        json={"email": email, "password": password},
    )
    assert sign_in_response.status_code == 200
    access_token = sign_in_response.json()["access_token"]
    assert auth_chat_client.cookies.get("refresh_token") is not None

    me_response = await auth_chat_client.get("/api/users/me", headers=_bearer(access_token))
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email
    assert me_response.json()["status"] == "active"
    assert me_response.json()["profile"]["display_name"] == "Flow User"

    patch_profile_response = await auth_chat_client.patch(
        "/api/profile",
        headers=_bearer(access_token),
        json={"display_name": "Flow User Updated"},
    )
    assert patch_profile_response.status_code == 200
    assert patch_profile_response.json()["profile"]["display_name"] == "Flow User Updated"

    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)

    create_session_response = await auth_chat_client.post(
        "/api/chat/sessions",
        json={},
        headers=_bearer(access_token),
    )
    assert create_session_response.status_code == 201
    session_id = create_session_response.json()["id"]

    list_sessions_response = await auth_chat_client.get(
        "/api/chat/sessions",
        headers=_bearer(access_token),
    )
    assert list_sessions_response.status_code == 200
    assert [session["id"] for session in list_sessions_response.json()] == [session_id]

    refresh_response = await auth_chat_client.post("/api/auth/refresh")
    assert refresh_response.status_code == 200
    refreshed_access_token = refresh_response.json()["access_token"]
    assert refreshed_access_token != access_token
    assert auth_chat_client.cookies.get("refresh_token") is not None

    sign_out_response = await auth_chat_client.post("/api/auth/sign-out")
    assert sign_out_response.status_code == 200
    assert sign_out_response.json()["detail"] == "Signed out successfully."
    assert auth_chat_client.cookies.get("refresh_token") is None

    refresh_after_sign_out_response = await auth_chat_client.post("/api/auth/refresh")
    assert refresh_after_sign_out_response.status_code == 401

    forgot_password_response = await auth_chat_client.post(
        "/api/auth/forgot-password",
        json={"email": email},
    )
    assert forgot_password_response.status_code == 200
    assert forgot_password_response.json()["detail"] == (
        "If the account exists, reset instructions have been sent."
    )
    assert len(capturing_email_sender.deliveries) == 2

    reset_token = _extract_token(
        capturing_email_sender.deliveries[-1],
        route_path="/auth/reset-password",
    )
    reset_response = await auth_chat_client.post(
        "/api/auth/reset-password",
        json={"token": reset_token, "new_password": new_password},
    )
    assert reset_response.status_code == 200

    old_password_sign_in_response = await auth_chat_client.post(
        "/api/auth/sign-in",
        json={"email": email, "password": password},
    )
    assert old_password_sign_in_response.status_code == 401

    new_password_sign_in_response = await auth_chat_client.post(
        "/api/auth/sign-in",
        json={"email": email, "password": new_password},
    )
    assert new_password_sign_in_response.status_code == 200
    assert new_password_sign_in_response.json()["access_token"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_chat_endpoints_enforce_session_ownership_for_authenticated_users(
    auth_chat_app: FastAPI,
    create_user,
    make_user_auth_headers,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    owner = await create_user(email="owner@example.com")
    intruder = await create_user(email="intruder@example.com")
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)

    transport = httpx.ASGITransport(app=auth_chat_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=make_user_auth_headers(owner),
    ) as owner_client:
        create_session_response = await owner_client.post("/api/chat/sessions", json={})
        assert create_session_response.status_code == 201
        session_id = create_session_response.json()["id"]

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=make_user_auth_headers(intruder),
    ) as intruder_client:
        intruder_list_response = await intruder_client.get("/api/chat/sessions")
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json() == []

        intruder_get_response = await intruder_client.get(f"/api/chat/sessions/{session_id}")
        assert intruder_get_response.status_code == 403
        assert intruder_get_response.json()["detail"] == "Session belongs to a different user"

        intruder_send_response = await intruder_client.post(
            "/api/chat/messages",
            json={"session_id": session_id, "text": "hello"},
        )
        assert intruder_send_response.status_code == 403
        assert intruder_send_response.json()["detail"] == "Session belongs to a different user"
