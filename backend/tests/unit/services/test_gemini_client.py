from __future__ import annotations

from types import ModuleType

import pytest

from app.services.gemini_client import create_genai_client


def test_create_genai_client_requires_api_key_outside_vertex_ai() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY is required for Gemini API access"):
        create_genai_client(
            api_key=None,
            use_vertexai=False,
            project=None,
            location="global",
        )


def test_create_genai_client_requires_project_or_api_key_in_vertex_ai_mode() -> None:
    with pytest.raises(
        ValueError,
        match="Vertex AI Gemini client requires GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY",
    ):
        create_genai_client(
            api_key=None,
            use_vertexai=True,
            project=None,
            location="global",
        )


def test_create_genai_client_uses_api_key_for_direct_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setattr("app.services.gemini_client.genai.Client", FakeClient)

    client = create_genai_client(
        api_key="secret",
        use_vertexai=False,
        project=None,
        location="global",
    )

    assert isinstance(client, FakeClient)
    assert captured_kwargs == {"api_key": "secret"}


def test_create_genai_client_uses_vertex_ai_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setattr("app.services.gemini_client.genai.Client", FakeClient)

    client = create_genai_client(
        api_key=None,
        use_vertexai=True,
        project="vertex-project",
        location="global",
    )

    assert isinstance(client, FakeClient)
    assert captured_kwargs == {
        "vertexai": True,
        "project": "vertex-project",
        "location": "global",
    }
