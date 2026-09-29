"""Input parsing and routing for Phase 4 Multimodal support."""

from __future__ import annotations

import ipaddress
import mimetypes
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from velix_agent.core.logging import get_logger
from velix_agent.core.message import DocumentPart, ErrorPart, ImagePart, MessagePart, TextPart

logger = get_logger("input_router")

# Match URLs (exclude trailing punctuation if possible, but simpler to just match typical URLs)
URL_PATTERN = r"(?P<url>https?://[^\s\"']+)"

# Match extensions for known supported file types
EXT_PATTERN = (
    r"(?i:\.(?:pdf|png|jpe?g|gif|webp|txt|md|json|csv|py|js|ts|java|c|cpp|html|"
    r"css|xml|docx?|pptx?))"
)

# Match Quoted paths. Starts with ~, /, ./, ../ or ends with a known extension.
QUOTED_PATH_PATTERN = (
    rf"(?P<quote>[\"'])(?P<qpath>(?:~/|/|\./|\.\./)[^\"']+?|[^\"']+?{EXT_PATTERN})(?P=quote)"
)

# Match Unquoted paths. Must be preceded by start of string or whitespace.
# Starts with ~, /, ./, ../ or ends with a known extension.
UNQUOTED_PATH_PATTERN = (
    rf"(?P<upath>(?:^|(?<=\s))(?:(?:~/|/|\./|\.\./)[^\s\"']+|[^\s\"']+?{EXT_PATTERN}))"
)

# Combine into one master pattern
MASTER_PATTERN = re.compile(f"{URL_PATTERN}|{QUOTED_PATH_PATTERN}|{UNQUOTED_PATH_PATTERN}")

# Common code file extensions that mimetypes might miss or misclassify
CODE_EXTENSIONS = {
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".ts": "application/typescript",
    ".jsx": "text/javascript",
    ".tsx": "application/typescript",
    ".java": "text/x-java-source",
    ".c": "text/x-c",
    ".cpp": "text/x-c",
    ".h": "text/x-c",
    ".hpp": "text/x-c",
    ".go": "text/x-go",
    ".rs": "text/rust",
    ".html": "text/html",
    ".css": "text/css",
    ".sql": "application/sql",
    ".sh": "application/x-sh",
    ".md": "text/markdown",
    ".json": "application/json",
    ".xml": "application/xml",
    ".csv": "text/csv",
    ".txt": "text/plain",
}


class InputRouter:
    """Parses user string input into strongly typed MessageParts."""

    @classmethod
    def parse(
        cls, user_input: str, max_size: int = 15 * 1024 * 1024, cwd: Path | None = None
    ) -> list[MessagePart]:
        """Parse raw text into multimodal parts (Text, Images, Documents)."""
        if user_input.strip().startswith("execute tool "):
            return [TextPart(text=user_input)]

        parts: list[MessagePart] = []

        last_idx = 0
        for match in MASTER_PATTERN.finditer(user_input):
            text_before = user_input[last_idx : match.start()].strip()
            if text_before:
                parts.append(TextPart(text=text_before))

            url = match.group("url")
            qpath = match.group("qpath")
            upath = match.group("upath")

            if url:
                # Clean trailing punctuation from URL if needed
                while url and url[-1] in ".,;!?":
                    url = url[:-1]
                parts.append(cls._parse_remote_url(url, max_size))
            elif qpath:
                parts.append(cls._parse_local_file(qpath, max_size, cwd))
            elif upath:
                while upath and upath[-1] in ".,;!?":
                    upath = upath[:-1]
                parts.append(cls._parse_local_file(upath, max_size, cwd))

            last_idx = match.end()

        remaining_text = user_input[last_idx:].strip()
        if remaining_text:
            parts.append(TextPart(text=remaining_text))

        return parts

    @classmethod
    def _parse_local_file(
        cls, raw_path: str, max_size: int, cwd: Path | None = None
    ) -> MessagePart:
        """Read a local file securely, adhering to size limits."""
        logger.debug(f"Parsing local file: {raw_path}")
        try:
            expanded = os.path.expanduser(raw_path)
            path = (cwd / expanded).resolve() if cwd else Path(expanded).resolve()

            if not path.exists():
                return ErrorPart(error=f"I couldn't find {raw_path} in the current directory.")
            if not path.is_file():
                return ErrorPart(error=f"Path is not a file: {raw_path}")

            file_size = path.stat().st_size
            if file_size > max_size:
                return ErrorPart(
                    error=f"File {raw_path} exceeds the limit of {max_size // (1024 * 1024)}MB."
                )

            data = path.read_bytes()
            mime_type = cls._detect_mime_type(path.name)
            return cls._create_file_part(mime_type, data, str(path))

        except PermissionError:
            return ErrorPart(error=f"Permission denied: {raw_path}")
        except Exception as e:
            logger.warning(f"Unexpected error reading {raw_path}: {e}")
            return ErrorPart(error=f"Error reading file {raw_path}: {e}")

    @classmethod
    def _parse_remote_url(cls, url: str, max_size: int) -> MessagePart:
        """Safely fetch a URL with SSRF protection and size limits."""
        logger.debug(f"Fetching URL: {url}")

        # 1. SSRF Protection
        ssrf_error = cls._validate_remote_url(url)
        if ssrf_error:
            return ErrorPart(error=ssrf_error)

        # 2. Download Data
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "VelixAgent/0.1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                status = response.getcode()
                if status != 200:
                    return ErrorPart(error=f"Failed to fetch {url}: HTTP {status}")

                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_size:
                    return ErrorPart(error=f"Resource {url} exceeds limit.")

                data = response.read(max_size + 1)
                if len(data) > max_size:
                    return ErrorPart(error=f"Resource {url} exceeds limit.")

                content_type = response.headers.get("Content-Type", "")
                mime_type = content_type.split(";")[0].strip()

                if not mime_type or mime_type == "application/octet-stream":
                    # Fallback to guessing by extension
                    mime_type = cls._detect_mime_type(url)

                return cls._create_file_part(mime_type, data, url)

        except urllib.error.HTTPError as e:
            return ErrorPart(error=f"HTTP {e.code} error fetching {url}")
        except urllib.error.URLError as e:
            logger.warning(f"URL error fetching {url}: {e}")
            return ErrorPart(error=f"Network error fetching {url}: {e.reason}")
        except Exception as e:
            logger.warning(f"Unexpected error fetching {url}: {e}")
            return ErrorPart(error=f"Error fetching {url}: {e}")

    @classmethod
    def _validate_remote_url(cls, url: str) -> str | None:
        """Check for SSRF. Returns error string if blocked, None if allowed."""
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return "Invalid URL format."

            # Resolve IP to prevent DNS rebinding or obfuscation
            ip_str = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(ip_str)

            if ip.is_private:
                return f"URL blocked for security reasons (Private IP {ip_str})"
            if ip.is_loopback:
                return f"URL blocked for security reasons (Loopback IP {ip_str})"
            if ip.is_link_local:
                return f"URL blocked for security reasons (Link-local IP {ip_str})"
            if ip.is_multicast:
                return f"URL blocked for security reasons (Multicast IP {ip_str})"
            if ip_str.startswith("169.254."):
                return f"URL blocked for security reasons (Cloud Metadata IP {ip_str})"
            if ip_str == "0.0.0.0":
                return f"URL blocked for security reasons (Wildcard IP {ip_str})"

            return None
        except socket.gaierror:
            return f"DNS resolution failed for {url}"
        except ValueError:
            return f"Invalid IP address format in {url}"
        except Exception as e:
            return f"Error validating URL {url}: {e}"

    @classmethod
    def _detect_mime_type(cls, filename_or_url: str) -> str:
        """Detect MIME type from extension or predefined mapping."""
        parsed = urllib.parse.urlparse(filename_or_url)
        path = parsed.path if parsed.path else filename_or_url
        ext = os.path.splitext(path)[1].lower()

        if ext in CODE_EXTENSIONS:
            return CODE_EXTENSIONS[ext]

        guessed, _ = mimetypes.guess_type(path)
        return guessed or "application/octet-stream"

    @classmethod
    def _create_file_part(cls, mime_type: str, data: bytes, source: str) -> MessagePart:
        """Create the appropriate MessagePart based on mime_type."""
        if mime_type.startswith("image/"):
            return ImagePart(mime_type=mime_type, data=data)
        elif (
            mime_type == "application/pdf"
            or mime_type.startswith("text/")
            or mime_type == "application/json"
            or mime_type == "application/xml"
            or mime_type == "application/sql"
            or mime_type.startswith("application/x-sh")
            or mime_type.startswith("application/typescript")
        ):
            return DocumentPart(mime_type=mime_type, data=data)
        else:
            return ErrorPart(error=f"Unsupported content type '{mime_type}' for {source}")
