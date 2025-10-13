from __future__ import annotations

from enum import Enum


class DependencyType(Enum):
    """Enumeration of possible dependency types."""

    FS = "FS"  # Finish-to-Start
    FF = "FF"  # Finish-to-Finish
    SS = "SS"  # Start-to-Start
    SF = "SF"  # Start-to-Finish


class TaskState(Enum):
    """Enumeration of possible task states."""

    UNSPECIFIED = 0  # TASK_STATE_UNSPECIFIED
    PENDING = 1  # TASK_STATE_PENDING
    READY = 2  # TASK_STATE_READY
    RUNNING = 3  # TASK_STATE_RUNNING
    SUCCEEDED = 4  # TASK_STATE_SUCCEEDED
    FAILED = 5  # TASK_STATE_FAILED
