from dataclasses import dataclass
from enum import Enum


class ResultClassification(Enum):
    SUCCESS = "SUCCESS"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    NON_RETRYABLE_FAILURE = "NON_RETRYABLE_FAILURE"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


@dataclass
class AnalysisResult:
    classification: ResultClassification
    reason: str
    retryable: bool
    security_blocked: bool
    resource_limited: bool
    timeout: bool
    exit_code: int | None = None
