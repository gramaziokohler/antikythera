from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional
from typing import Dict

from compas.data import Data


class DependencyType(StrEnum):
    """Enumeration of possible dependency types."""

    FS = "FS"  # Finish-to-Start
    FF = "FF"  # Finish-to-Finish
    SS = "SS"  # Start-to-Start
    SF = "SF"  # Start-to-Finish


class TaskState(StrEnum):
    """Enumeration of possible task states."""

    UNSPECIFIED = "UNSPECIFIED"  # TASK_STATE_UNSPECIFIED
    PENDING = "PENDING"  # TASK_STATE_PENDING
    READY = "READY"  # TASK_STATE_READY
    RUNNING = "RUNNING"  # TASK_STATE_RUNNING
    SUCCEEDED = "SUCCEEDED"  # TASK_STATE_SUCCEEDED
    FAILED = "FAILED"  # TASK_STATE_FAILED


class TaskError(Data):
    """Task error information."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    def __init__(self, code: str, message: str, details: Optional[Any] = None) -> Dict[str, Any]:
        self.code = code
        self.message = message
        self.details = details


class TaskAssignmentMessage(Data):
    """Task assignment message sent by orchestrator to agents."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "inputs": self.inputs,
            "output_keys": self.output_keys,
            "params": self.params,
            "timestamp": self.timestamp.isoformat(),
        }

    def __init__(self, id: str, type: str, inputs: Dict[str, Any] = None, output_keys: list[str] = None, params: Dict[str, Any] = None, timestamp: datetime = None) -> None:
        super().__init__()
        self.id = id
        self.type = type
        self.inputs = inputs or {}
        self.output_keys = output_keys or []
        self.params = params or {}
        self.timestamp = timestamp or datetime.now()


class TaskCompletionMessage(Data):
    """Task completion message sent by agents to orchestrator."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "outputs": self.outputs,
            "error": self.error,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }

    def __init__(
        self,
        id: str,
        state: TaskState,
        outputs: Dict[str, Any] = None,
        error: Optional[TaskError] = None,
        timestamp: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.state = state
        self.outputs = outputs or {}
        self.error = error
        self.timestamp = timestamp or datetime.now()
        self.duration_ms = duration_ms
