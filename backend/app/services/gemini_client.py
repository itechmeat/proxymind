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
    normalized_project = project.strip() if isinstance(project, str) else project
    normalized_api_key = api_key.strip() if isinstance(api_key, str) else api_key
    if normalized_project == "":
        normalized_project = None
    if normalized_api_key == "":
        normalized_api_key = None

    if use_vertexai:
        if normalized_project is None and normalized_api_key is None:
            raise ValueError(
                "Vertex AI Gemini client requires GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY"
            )

        client_kwargs: dict[str, object] = {
            "vertexai": True,
            "location": location,
        }
        if normalized_project is not None:
            client_kwargs["project"] = normalized_project
        if normalized_api_key is not None:
            client_kwargs["api_key"] = normalized_api_key
        return genai.Client(**client_kwargs)

    if normalized_api_key is None:
        raise ValueError("GEMINI_API_KEY is required for Gemini API access")

    return genai.Client(api_key=normalized_api_key)
