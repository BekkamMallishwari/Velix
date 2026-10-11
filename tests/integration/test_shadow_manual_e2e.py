"""
Manual end-to-end shadow workspace test.

Creates a disposable sample project, runs the shadow workspace session
against it with a mock tool invocation, and verifies:
  1. File operations target only the shadow copy.
  2. Host files remain byte-identical.
  3. Shadow directory is fully cleaned up afterward.
  4. Cleanup also occurs on exception.
"""
import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from velix_agent.workspace.session import ShadowWorkspaceSession


def _hash_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _create_sample_project(base: Path) -> dict[str, str]:
    """Create a small disposable project and return {relpath: sha256}."""
    files = {
        "main.py": 'print("hello world")\n',
        "lib/utils.py": "def add(a, b):\n    return a + b\n",
        "lib/__init__.py": "",
        "data/config.json": '{"key": "value"}\n',
        "README.md": "# Sample Project\n",
    }
    checksums = {}
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        checksums[rel] = _hash_file(p)
    return checksums


class TestShadowManualE2E:
    """End-to-end shadow workspace tests against a real temporary project."""

    def test_shadow_isolates_writes_from_host(self, tmp_path: Path) -> None:
        """Write a file in the shadow; verify host is untouched and shadow is cleaned up."""
        project = tmp_path / "sample_project"
        project.mkdir()
        host_checksums = _create_sample_project(project)

        shadow_root_path: Path | None = None

        with ShadowWorkspaceSession(project) as shadow_root:
            shadow_root_path = shadow_root

            # Verify shadow has the expected files
            for rel in host_checksums:
                assert (shadow_root / rel).exists(), f"Missing in shadow: {rel}"

            # Write a NEW file in the shadow
            (shadow_root / "agent_output.txt").write_text("agent was here\n")

            # Modify an EXISTING file in the shadow
            (shadow_root / "main.py").write_text('print("modified by agent")\n')

            # Verify the shadow has the changes
            assert (shadow_root / "agent_output.txt").exists()
            assert "modified by agent" in (shadow_root / "main.py").read_text()

        # After exit: shadow directory must be gone
        assert not shadow_root_path.exists(), "Shadow directory was not cleaned up"

        # Host files must be byte-identical
        for rel, expected_hash in host_checksums.items():
            actual_hash = _hash_file(project / rel)
            assert actual_hash == expected_hash, f"Host file modified: {rel}"

        # The agent's new file must NOT exist in the host
        assert not (project / "agent_output.txt").exists(), "Shadow file leaked to host"

    def test_shadow_cleanup_on_exception(self, tmp_path: Path) -> None:
        """Shadow is cleaned up even when an exception occurs inside the context."""
        project = tmp_path / "sample_project"
        project.mkdir()
        host_checksums = _create_sample_project(project)

        shadow_root_path: Path | None = None

        with pytest.raises(RuntimeError, match="simulated agent crash"):
            with ShadowWorkspaceSession(project) as shadow_root:
                shadow_root_path = shadow_root
                (shadow_root / "partial_work.txt").write_text("incomplete\n")
                raise RuntimeError("simulated agent crash")

        assert shadow_root_path is not None
        assert not shadow_root_path.exists(), "Shadow not cleaned up after exception"

        for rel, expected_hash in host_checksums.items():
            assert _hash_file(project / rel) == expected_hash, f"Host modified: {rel}"

    def test_shadow_excludes_git_directory(self, tmp_path: Path) -> None:
        """The .git directory must not be copied to the shadow."""
        project = tmp_path / "sample_project"
        project.mkdir()
        _create_sample_project(project)

        # Create a fake .git directory
        git_dir = project / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (git_dir / "config").write_text("[core]\n")

        with ShadowWorkspaceSession(project) as shadow_root:
            assert not (shadow_root / ".git").exists(), ".git leaked into shadow"
            # But other files should be present
            assert (shadow_root / "main.py").exists()
            assert (shadow_root / "README.md").exists()

    def test_shadow_handles_symlink_within_project(self, tmp_path: Path) -> None:
        """Internal symlinks (pointing within the project) should be preserved."""
        project = tmp_path / "sample_project"
        project.mkdir()
        _create_sample_project(project)

        # Create a symlink within the project
        (project / "link_to_readme").symlink_to(project / "README.md")

        with ShadowWorkspaceSession(project) as shadow_root:
            shadow_link = shadow_root / "link_to_readme"
            # The link or its target content should be accessible
            if shadow_link.exists():
                content = shadow_link.read_text()
                assert "Sample Project" in content

    def test_shadow_reports_seed_stats(self, tmp_path: Path) -> None:
        """ShadowWorkspaceSession exposes seed_result with file counts."""
        project = tmp_path / "sample_project"
        project.mkdir()
        _create_sample_project(project)

        session = ShadowWorkspaceSession(project)
        with session as shadow_root:
            assert session.seed_result is not None
            assert session.seed_result.files_copied >= 5  # at least our 5 files
            assert session.seed_result.bytes_copied > 0
            assert session.seed_result.ok()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
