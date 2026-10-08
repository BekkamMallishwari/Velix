from dataclasses import dataclass
from enum import Enum


class RuntimeStatus(Enum):
    SUPPORTED = "SUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass
class RuntimeInfo:
    name: str
    status: RuntimeStatus
    executable: str | None = None
    version: str | None = None
    package_manager: str | None = None
    package_manager_executable: str | None = None
    platform: str = ""
    is_virtual_env: bool = False


@dataclass
class RuntimeCapability:
    detection: str = "SUPPORTED"
