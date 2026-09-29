"""Local model provider implementation."""

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from velix_agent.core.logging import get_logger
from velix_agent.core.message import DocumentPart, ErrorPart, ImagePart, Message, TextPart
from velix_agent.core.response import AgentResponse
from velix_agent.providers.base import Provider

if TYPE_CHECKING:
    from velix_agent.tools.base import Tool
from velix_agent.providers.errors import (
    ProviderAPIError,
    ProviderTransientError,
    ProviderUnsupportedError,
)

logger = get_logger("local_provider")


class LocalProvider(Provider):
    """Provider for local models via Ollama."""

    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")

    def check_availability(self) -> tuple[bool, str]:
        """Check if Ollama is running and the model is installed."""
        req = urllib.request.Request(f"{self.base_url}/api/tags")
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.getcode() != 200:
                    return False, "Ollama not running"
                data = json.loads(response.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]

                # Check exact match or base match (e.g., "llama3" in "llama3:latest")
                for m in models:
                    if m == self.model or m.startswith(f"{self.model}:"):
                        return True, "available"
                return False, "model not installed"
        except (urllib.error.URLError, TimeoutError, OSError):
            return False, "Ollama not running"

    def generate(
        self, messages: list[Message], tools: list["Tool"] | None = None
    ) -> AgentResponse:
        is_available, reason = self.check_availability()
        if not is_available:
            if "Ollama not running" in reason:
                raise ProviderTransientError(f"Local provider connection error: {reason}")
            raise ProviderAPIError(f"Local provider error: {reason}")

        ollama_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                if isinstance(msg.content, list):
                    text_parts = [p.text for p in msg.content if isinstance(p, TextPart)]
                    content_str = "\n".join(text_parts)
                else:
                    content_str = msg.content
                ollama_messages.append({"role": "system", "content": content_str})
            else:
                if isinstance(msg.content, list):
                    parts_text = []
                    for part in msg.content:
                        if isinstance(part, TextPart):
                            parts_text.append(part.text)
                        elif isinstance(part, (ImagePart, DocumentPart)):
                            raise ProviderUnsupportedError(
                                "Local provider does not support this file type."
                            )
                        elif isinstance(part, ErrorPart):
                            parts_text.append(f"[System Note: {part.error}]")

                    ollama_messages.append(
                        {
                            "role": "user" if msg.role == "user" else "assistant",
                            "content": "\n".join(parts_text),
                        }
                    )
                else:
                    ollama_messages.append(
                        {
                            "role": "user" if msg.role == "user" else "assistant",
                            "content": msg.content,
                        }
                    )

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }

        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                status = response.getcode()
                if status != 200:
                    raise ProviderAPIError(f"Local provider HTTP {status}")

                resp_data = json.loads(response.read().decode("utf-8"))
                content = resp_data.get("message", {}).get("content", "")

                metadata = {
                    "provider": "local",
                    "model": self.model,
                }

                return AgentResponse(text=content, status="success", metadata=metadata)
        except urllib.error.URLError as e:
            # Handle connection refused (Ollama not running)
            raise ProviderTransientError(f"Local provider connection error: {e.reason}") from e
        except Exception as e:
            raise ProviderAPIError(f"Local provider error: {e}") from e
