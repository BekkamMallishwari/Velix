"""Unit tests for the AgentResponse model."""

import pytest

from velix_agent.core.response import AgentResponse


def test_success_response() -> None:
    """Test creating a valid success response."""
    resp = AgentResponse(text="Success", status="success", metadata={"key": "value"})
    assert resp.text == "Success"
    assert resp.status == "success"
    assert resp.metadata == {"key": "value"}
    assert resp.error is None


def test_error_response_valid() -> None:
    """Test creating a valid error response."""
    resp = AgentResponse(text="Failed", status="error", error="An error occurred")
    assert resp.status == "error"
    assert resp.error == "An error occurred"


def test_error_response_missing_error() -> None:
    """Test creating an error response without error details."""
    with pytest.raises(ValueError, match=r"Error response must include error details."):
        AgentResponse(text="Failed", status="error")


def test_invalid_status() -> None:
    """Test creating a response with an invalid status."""
    with pytest.raises(ValueError, match="Invalid status"):
        AgentResponse(text="Test", status="invalid")  # type: ignore
