from __future__ import annotations

from enum import Enum


class DependencyType(Enum):
    """Enumeration of possible dependency types."""

    FS = "FS" # Finish-to-Start
    FF = "FF" # Finish-to-Finish
    SS = "SS" # Start-to-Start
    SF = "SF" # Start-to-Finish


class TaskState(Enum):
    """Enumeration of possible task states."""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
