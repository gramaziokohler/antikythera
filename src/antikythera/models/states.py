from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import Enum
from typing import Any
from typing import Dict


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


@dataclass
class TaskError:
    """Task error information."""

    code: str
    message: str
    details: Any | None = None


@dataclass
class TaskAssignmentMessage:
    """Task assignment message sent by orchestrator to agents."""

    id: str
    type: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    output_keys: list[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TaskCompletionMessage:
    """Task completion message sent by agents to orchestrator."""

    id: str
    state: TaskState
    outputs: Dict[str, Any] = field(default_factory=dict)
    error: TaskError | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: int | None = None
