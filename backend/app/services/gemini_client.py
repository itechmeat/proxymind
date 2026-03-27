from __future__ import annotations

from typing import Any

from google import genai


def create_genai_client(
    *,
    api_key: str | None,
    use_vertexai: bool,
    project: str | None,
    location: str,
) -> Any:
    if use_vertexai:
        if project is None and api_key is None:
            raise ValueError(
                "Vertex AI Gemini client requires GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY"
            )

        client_kwargs: dict[str, object] = {
            "vertexai": True,
            "location": location,
        }
        if project is not None:
            client_kwargs["project"] = project
        if api_key is not None:
            client_kwargs["api_key"] = api_key
        return genai.Client(**client_kwargs)

    if not api_key:
        raise ValueError("GEMINI_API_KEY is required for Gemini API access")

    return genai.Client(api_key=api_key)
