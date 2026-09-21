from pathlib import Path

from velix_agent.core.input_router import InputRouter
from velix_agent.core.message import DocumentPart, ErrorPart


def test_trailing_punctuation_and_relative_path(tmp_path: Path):
    # Setup test file
    pdf = tmp_path / "TC_Request_Letter.pdf"
    pdf.write_bytes(b"dummy")

    # test bare filename
    parts1 = InputRouter.parse("Explain the contents of TC_Request_Letter.pdf", cwd=tmp_path)
    assert len(parts1) == 2
    assert isinstance(parts1[1], DocumentPart)
    assert parts1[1].mime_type == "application/pdf"

    # test relative path with punctuation
    parts2 = InputRouter.parse("What is written in ./TC_Request_Letter.pdf?", cwd=tmp_path)
    assert len(parts2) == 2
    assert isinstance(parts2[1], DocumentPart)
    assert parts2[1].mime_type == "application/pdf"


def test_missing_relative_with_punctuation(tmp_path: Path):
    parts = InputRouter.parse("What is written in ./nonexistent.pdf?", cwd=tmp_path)
    assert len(parts) == 2
    assert isinstance(parts[1], ErrorPart)
    # The punctuation shouldn't be in the error message as it's stripped
    assert "I couldn't find ./nonexistent.pdf in the current directory." in parts[1].error


def test_quoted_path_with_spaces_and_cwd(tmp_path: Path):
    pdf = tmp_path / "TC Request Letter.pdf"
    pdf.write_bytes(b"dummy")
    parts = InputRouter.parse('Explain "TC Request Letter.pdf"!', cwd=tmp_path)
    assert (
        len(parts) == 3
    )  # 'Explain', 'DocumentPart', '!' -> Wait, '!' is outside quotes, so it's TextPart('!')

    # Wait, '!' is text after. We just verify DocumentPart exists.
    assert any(isinstance(p, DocumentPart) for p in parts)
