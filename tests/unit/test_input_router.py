"""Tests for InputRouter."""

import os
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from velix_agent.core.input_router import InputRouter
from velix_agent.core.message import DocumentPart, ErrorPart, ImagePart, TextPart


@pytest.fixture
def temp_files(tmp_path: Path):
    """Create a variety of temporary files for testing."""
    png = tmp_path / "test.png"
    png.write_bytes(b"fake-png-data")

    jpg = tmp_path / "test.jpg"
    jpg.write_bytes(b"fake-jpg-data")

    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake-pdf-data")

    txt = tmp_path / "test.txt"
    txt.write_bytes(b"hello world")

    py = tmp_path / "test.py"
    py.write_bytes(b"print('hello')")

    spaces = tmp_path / "file with spaces.txt"
    spaces.write_bytes(b"spaces")

    unsupported = tmp_path / "test.bin"
    unsupported.write_bytes(b"\x00\x01\x02")

    return {
        "png": png,
        "jpg": jpg,
        "pdf": pdf,
        "txt": txt,
        "py": py,
        "spaces": spaces,
        "unsupported": unsupported,
    }


def test_parse_plain_text():
    parts = InputRouter.parse("Just a regular string.", max_size=100)
    assert len(parts) == 1
    assert isinstance(parts[0], TextPart)
    assert parts[0].text == "Just a regular string."


def test_parse_local_png(temp_files):
    parts = InputRouter.parse(f"Analyze {temp_files['png']}")
    assert len(parts) == 2
    assert isinstance(parts[0], TextPart)
    assert isinstance(parts[1], ImagePart)
    assert parts[1].mime_type == "image/png"


def test_parse_local_jpg(temp_files):
    parts = InputRouter.parse(f"Analyze {temp_files['jpg']}")
    assert len(parts) == 2
    assert isinstance(parts[1], ImagePart)
    assert parts[1].mime_type in ["image/jpeg", "image/jpg"]


def test_parse_local_pdf(temp_files):
    parts = InputRouter.parse(f"Read {temp_files['pdf']}")
    assert len(parts) == 2
    assert isinstance(parts[1], DocumentPart)
    assert parts[1].mime_type == "application/pdf"


def test_parse_local_text_file(temp_files):
    parts = InputRouter.parse(f"Read {temp_files['txt']}")
    assert isinstance(parts[1], DocumentPart)
    assert parts[1].mime_type == "text/plain"


def test_parse_local_python_file(temp_files):
    parts = InputRouter.parse(f"Review {temp_files['py']}")
    assert isinstance(parts[1], DocumentPart)
    assert parts[1].mime_type == "text/x-python"


def test_path_with_spaces(temp_files):
    parts = InputRouter.parse(f'Read "{temp_files["spaces"]}"')
    assert len(parts) == 2
    assert isinstance(parts[1], DocumentPart)
    assert parts[1].mime_type == "text/plain"


def test_tilde_path(monkeypatch, tmp_path):
    # Mock expanduser
    monkeypatch.setattr(os.path, "expanduser", lambda x: x.replace("~", str(tmp_path)))
    f = tmp_path / "home_test.txt"
    f.write_bytes(b"home")

    parts = InputRouter.parse("Read ~/home_test.txt")
    assert isinstance(parts[1], DocumentPart)


def test_relative_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "rel_test.txt"
    f.write_bytes(b"rel")

    parts = InputRouter.parse("Read ./rel_test.txt")
    assert isinstance(parts[1], DocumentPart)


def test_mixed_text_and_image(temp_files):
    parts = InputRouter.parse(f"Start {temp_files['png']} end")
    assert len(parts) == 3
    assert parts[0].text == "Start"
    assert isinstance(parts[1], ImagePart)
    assert parts[2].text == "end"


def test_multiple_images(temp_files):
    parts = InputRouter.parse(f"Compare {temp_files['png']} and {temp_files['jpg']}")
    assert len(parts) == 4
    assert isinstance(parts[0], TextPart)
    assert isinstance(parts[1], ImagePart)
    assert isinstance(parts[2], TextPart)
    assert isinstance(parts[3], ImagePart)


def test_nonexistent_file(temp_files):
    nonexistent = temp_files["png"].parent / "nope.png"
    parts = InputRouter.parse(f"Read {nonexistent}")
    assert isinstance(parts[1], ErrorPart)
    assert "I couldn't find" in parts[1].error


def test_bare_filename_exists(temp_files, monkeypatch):
    monkeypatch.chdir(temp_files["pdf"].parent)
    parts = InputRouter.parse("Explain the contents of test.pdf")
    assert len(parts) == 2
    assert isinstance(parts[1], DocumentPart)
    assert parts[1].mime_type == "application/pdf"


def test_bare_filename_missing(temp_files, monkeypatch):
    monkeypatch.chdir(temp_files["pdf"].parent)
    parts = InputRouter.parse("Explain the contents of missing.pdf")
    assert isinstance(parts[1], ErrorPart)
    assert "I couldn't find missing.pdf in the current directory." in parts[1].error


def test_unsupported_file(temp_files):
    parts = InputRouter.parse(f"Read {temp_files['unsupported']}")
    assert isinstance(parts[1], ErrorPart)
    assert "Unsupported content type" in parts[1].error


def test_oversized_local_file(temp_files):
    parts = InputRouter.parse(f"Read {temp_files['txt']}", max_size=2)
    assert isinstance(parts[1], ErrorPart)
    assert "exceeds the limit" in parts[1].error


# --- URL Tests ---


def test_parse_image_url(monkeypatch):
    mock_fetch = MagicMock(return_value=ImagePart(mime_type="image/png", data=b"data"))
    monkeypatch.setattr(InputRouter, "_parse_remote_url", mock_fetch)

    parts = InputRouter.parse("Look at https://example.com/img.png")
    assert len(parts) == 2
    assert isinstance(parts[1], ImagePart)


def test_ssrf_localhost():
    parts = InputRouter.parse("Check http://localhost:8080")
    assert isinstance(parts[1], ErrorPart)
    assert "blocked for security reasons" in parts[1].error


def test_ssrf_private_ip():
    parts = InputRouter.parse("Check http://192.168.1.1/admin")
    assert isinstance(parts[1], ErrorPart)
    assert "blocked for security reasons" in parts[1].error


def test_ssrf_metadata_ip():
    parts = InputRouter.parse("Check http://169.254.169.254/latest")
    assert isinstance(parts[1], ErrorPart)
    assert "blocked for security reasons" in parts[1].error


def test_ssrf_dns_resolution(monkeypatch):
    # Mock socket.gethostbyname to simulate DNS resolution to localhost
    monkeypatch.setattr("socket.gethostbyname", lambda x: "127.0.0.1")
    parts = InputRouter.parse("Check http://malicious.com")
    assert isinstance(parts[1], ErrorPart)
    assert "blocked for security reasons" in parts[1].error


def test_url_404(monkeypatch):
    def mock_urlopen(*args, **kwargs):
        raise urllib.error.HTTPError(url="", code=404, msg="Not Found", hdrs=None, fp=None)  # type: ignore

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    parts = InputRouter.parse("Check https://example.com/404.png")
    assert isinstance(parts[1], ErrorPart)
    assert "HTTP 404" in parts[1].error


def test_oversized_url_response(monkeypatch):
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.headers = {"Content-Length": "99999"}

    mock_urlopen = MagicMock()
    mock_urlopen.return_value.__enter__.return_value = mock_response
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    parts = InputRouter.parse("Check https://example.com/huge.png", max_size=100)
    assert isinstance(parts[1], ErrorPart)
    assert "exceeds limit" in parts[1].error


def test_ordering_and_mixed_inputs(temp_files, monkeypatch):
    mock_fetch = MagicMock(return_value=ImagePart(mime_type="image/png", data=b"data"))
    monkeypatch.setattr(InputRouter, "_parse_remote_url", mock_fetch)

    input_str = f"Text1 {temp_files['pdf']} Text2 https://example.com/img.png Text3"
    parts = InputRouter.parse(input_str)

    assert len(parts) == 5
    assert isinstance(parts[0], TextPart)
    assert parts[0].text == "Text1"
    assert isinstance(parts[1], DocumentPart)
    assert isinstance(parts[2], TextPart)
    assert parts[2].text == "Text2"
    assert isinstance(parts[3], ImagePart)
    assert isinstance(parts[4], TextPart)
    assert parts[4].text == "Text3"
