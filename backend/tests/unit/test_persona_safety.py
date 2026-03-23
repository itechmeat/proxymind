from __future__ import annotations

from app.persona.safety import SYSTEM_SAFETY_POLICY


def test_safety_policy_is_nonempty_string() -> None:
    assert isinstance(SYSTEM_SAFETY_POLICY, str)
    assert len(SYSTEM_SAFETY_POLICY.strip()) > 100


def test_safety_policy_contains_core_rules() -> None:
    policy_lower = SYSTEM_SAFETY_POLICY.lower()

    assert "knowledge context" in policy_lower
    assert "untrusted data" in policy_lower
    assert "source_id" in SYSTEM_SAFETY_POLICY
    assert "system prompt" in policy_lower


def test_safety_policy_forbids_url_generation() -> None:
    policy_lower = SYSTEM_SAFETY_POLICY.lower()

    assert "url" in policy_lower
    assert any(word in policy_lower for word in ("fabricate", "guess", "generate"))
