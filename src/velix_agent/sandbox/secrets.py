"""Sandbox secret management and redaction.

Security Guarantee:
Secrets are explicitly injected into a sandbox execution environment, are not
inherited from the host by default, and are redacted from captured output. This
does not prevent a malicious process from deliberately transforming or exfiltrating
a secret. This is not an OS-level secure keychain or cryptographic wiping mechanism.
"""

from velix_agent.sandbox.result import OUTPUT_TRUNCATION_MARKER

REDACTED_PLACEHOLDER = "***REDACTED***"


class SecretStore:
    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._registered_names: set[str] = set()

    def register(self, name: str, value: str) -> None:
        if not name or not value:
            raise ValueError("Secret name and value must not be empty.")
        if len(value) < 3:
            raise ValueError(
                f"Secret value for '{name}' is too short (min 3 characters) to safely redact."
            )
        self._secrets[name] = value
        self._registered_names.add(name)

    def create_environment(self, allowed_names: list[str]) -> dict[str, str]:
        env: dict[str, str] = {}
        for name in allowed_names:
            if name in self._secrets:
                env[name] = self._secrets[name]
        return env

    @staticmethod
    def _find_and_merge_ranges(
        text: str, secrets: list[str], extra_ranges: list[tuple[int, int]] | None = None
    ) -> list[tuple[int, int]]:
        """Find all occurrences of secrets in text and return merged [start, end] ranges."""
        ranges: list[tuple[int, int]] = list(extra_ranges or [])
        for secret in secrets:
            start = 0
            secret_len = len(secret)
            while True:
                idx = text.find(secret, start)
                if idx == -1:
                    break
                ranges.append((idx, idx + secret_len))
                start = idx + 1

        if not ranges:
            return []

        ranges.sort(key=lambda r: (r[0], -r[1]))

        merged: list[tuple[int, int]] = [ranges[0]]
        for start, end in ranges[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        return merged

    @staticmethod
    def _replace_ranges(text: str, ranges: list[tuple[int, int]], placeholder: str) -> str:
        """Replace non-overlapping [start, end] ranges in text with placeholder."""
        if not ranges:
            return text

        parts: list[str] = []
        curr = 0
        for start, end in ranges:
            parts.append(text[curr:start])
            parts.append(placeholder)
            curr = end
        parts.append(text[curr:])
        return "".join(parts)

    def redact(self, text: str, *, truncated: bool = False) -> str:
        """Redact all registered secret values from *text*.

        Hardening measures:

        1. **Overlapping and nested secrets** - all occurrences of registered
           secrets in the original output are discovered, overlapping or adjacent
           ranges are merged, and the merged ranges are replaced with
           ``REDACTED_PLACEHOLDER`` safely in a single pass. This ensures that
           substring or overlapping secrets (e.g. ``"abcd"`` and ``"cdef"`` in
           ``"abcdef"``, or ``"pass"`` and ``"password"``) never leak unredacted
           residue.

        2. **Truncation-boundary leakage** - when the backend truncates output
           at ``max_output_size`` bytes and sets *truncated* to ``True``, the
           original captured body is checked for any strict prefix of a
           registered secret at the truncation cut. If a boundary prefix does
           not overlap with a full secret, it is stripped before returning so
           that no partial secret leaks through the truncation cut. If it
           overlaps with a full secret, the range is merged into the redaction
           placeholder so no secret material is exposed.

        Args:
            text: The string to redact (stdout, stderr, or a command token).
            truncated: Set to ``True`` when the caller knows this string was
                hard-truncated by the output limiter. The backend already
                exposes ``SandboxResult.truncation_status`` for this purpose.
                Defaults to ``False``.
        """
        if not text:
            return text

        if not self._secrets:
            return text

        # Detach the truncation marker appended by the backend so that boundary
        # detection and secret matching operate on the original captured body.
        has_marker = text.endswith(OUTPUT_TRUNCATION_MARKER)
        original_body = text[: -len(OUTPUT_TRUNCATION_MARKER)] if has_marker else text

        if not original_body:
            return text

        # Deduplicate registered secret values
        secrets_list = sorted(set(self._secrets.values()), key=len, reverse=True)

        # 1. Find all full-secret occurrences
        full_secret_ranges = self._find_and_merge_ranges(original_body, secrets_list)

        # 2. Truncation-boundary guard on the original captured body:
        # Only runs when output is genuinely truncated.
        extra_boundary_range: list[tuple[int, int]] = []
        if truncated:
            body_len = len(original_body)
            best_len = 0
            for value in secrets_list:
                max_k = min(len(value) - 1, body_len)
                for prefix_len in range(max_k, 0, -1):
                    prefix = value[:prefix_len]
                    if original_body.endswith(prefix):
                        if prefix_len > best_len:
                            best_len = prefix_len
                        break  # longest match for this secret found

            if best_len > 0:
                boundary_start = body_len - best_len
                # Check if this boundary prefix overlaps with any full-secret occurrence
                overlaps_full_secret = any(end > boundary_start for _, end in full_secret_ranges)
                if overlaps_full_secret:
                    # Boundary prefix overlaps with a full secret: merge it into secret ranges
                    extra_boundary_range.append((boundary_start, body_len))
                else:
                    # Stands alone at the truncation cut: strip it from the body
                    original_body = original_body[:boundary_start]

        # 3. Merge ranges (including any boundary range) and replace with placeholder
        final_ranges = (
            self._find_and_merge_ranges(original_body, secrets_list, extra_boundary_range)
            if extra_boundary_range
            else full_secret_ranges
        )
        redacted_body = self._replace_ranges(original_body, final_ranges, REDACTED_PLACEHOLDER)

        return redacted_body + (OUTPUT_TRUNCATION_MARKER if has_marker else "")

    def cleanup(self) -> None:
        self._secrets.clear()
        self._registered_names.clear()
