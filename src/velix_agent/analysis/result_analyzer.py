from velix_agent.analysis.models import AnalysisResult, ResultClassification
from velix_agent.sandbox.result import SandboxResult


class ResultAnalyzer:
    @staticmethod
    def analyze(result: SandboxResult) -> AnalysisResult:
        if result.exit_code == 0:
            return AnalysisResult(
                classification=ResultClassification.SUCCESS,
                reason="Execution completed successfully.",
                retryable=False,
                security_blocked=False,
                resource_limited=False,
                timeout=False,
                exit_code=0,
            )

        stderr_lower = result.stderr.lower()
        stdout_lower = result.stdout.lower()
        combined_output = stderr_lower + "\n" + stdout_lower

        # 1. Timeout
        if result.exit_code == -1 and "timed out" in stderr_lower:
            return AnalysisResult(
                classification=ResultClassification.TIMEOUT,
                reason="Execution timed out.",
                retryable=True,  # Might be retryable with more time or optimized code
                security_blocked=False,
                resource_limited=False,
                timeout=True,
                exit_code=result.exit_code,
            )

        # 2. Security Blocked
        if (
            "operation not permitted" in combined_output
            or "permission denied" in combined_output
            or len(result.security_events) > 0
        ):
            return AnalysisResult(
                classification=ResultClassification.SECURITY_BLOCKED,
                reason="Execution blocked by security policy or permission denial.",
                retryable=False,
                security_blocked=True,
                resource_limited=False,
                timeout=False,
                exit_code=result.exit_code,
            )

        # 3. Resource Limit
        if (
            result.exit_code in (137, 153, 159)
            or "memoryerror" in combined_output
            or "out of memory" in combined_output
            or "cannot allocate memory" in combined_output
            or "resource temporarily unavailable" in combined_output
        ):
            return AnalysisResult(
                classification=ResultClassification.RESOURCE_LIMIT,
                reason="Execution hit a system resource limit (memory, CPU, processes).",
                retryable=False,
                security_blocked=False,
                resource_limited=True,
                timeout=False,
                exit_code=result.exit_code,
            )

        # 4. Non-retryable user code errors (Syntax, Compile, Type, etc.)
        non_retryable_markers = [
            "syntaxerror",
            "compilation error",
            "typeerror",
            "referenceerror",
            "nameerror",
            "indentationerror",
            "fatal error",
            "traceback (most recent call last)",
        ]
        # Except we must be careful: if a module is missing, Python gives ModuleNotFoundError, which inherits from Exception.
        # But ModuleNotFoundError is retryable by installing the dependency.
        if (
            "modulenotfounderror" in combined_output
            or "importerror" in combined_output
            or "no module named" in combined_output
        ):
            pass  # Fall through to retryable
        else:
            for marker in non_retryable_markers:
                if marker in combined_output:
                    return AnalysisResult(
                        classification=ResultClassification.NON_RETRYABLE_FAILURE,
                        reason="Syntax or fatal error in code.",
                        retryable=False,
                        security_blocked=False,
                        resource_limited=False,
                        timeout=False,
                        exit_code=result.exit_code,
                    )

        # 5. Retryable Failures (missing files, dependencies, command not found)
        retryable_markers = [
            "no such file or directory",
            "not found",
            "command not found",
            "cannot find module",
            "modulenotfounderror",
            "no module named",
            "importerror",
            "connection refused",
            "network is unreachable",
        ]
        for marker in retryable_markers:
            if marker in combined_output:
                return AnalysisResult(
                    classification=ResultClassification.RETRYABLE_FAILURE,
                    reason="Missing dependency, file, or transient error.",
                    retryable=True,
                    security_blocked=False,
                    resource_limited=False,
                    timeout=False,
                    exit_code=result.exit_code,
                )

        # 6. Unknown Failure
        return AnalysisResult(
            classification=ResultClassification.UNKNOWN_FAILURE,
            reason="Execution failed for an unknown reason.",
            retryable=False,
            security_blocked=False,
            resource_limited=False,
            timeout=False,
            exit_code=result.exit_code,
        )
