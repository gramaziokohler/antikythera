from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any, Optional
from typing import Dict

from antikythera.compat import StrEnum

from compas.data import Data


class ExecutionMode(StrEnum):
    """Enumeration of execution modes."""

    EXCLUSIVE = "EXCLUSIVE"  # EXECUTION_MODE_EXCLUSIVE
    COMPETITIVE = "COMPETITIVE"  # EXECUTION_MODE_COMPETITIVE


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


class SystemTaskType(StrEnum):
    """Enumeration of system task types."""

    START = "system.start"
    END = "system.end"
    SLEEP = "system.sleep"
    COMPOSITE = "system.composite"


class TaskError(Data):
    """Task error information."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}

    def __init__(self, code: str, message: str, details: Optional[Any] = None) -> Dict[str, Any]:
        self.code = code
        self.message = message
        self.details = details

    def __str__(self) -> str:
        return f"TaskError(code={self.code}, message={self.message}, details={self.details})"


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
            "execution_mode": self.execution_mode,
        }

    def __init__(
        self,
        id: str,
        type: str,
        inputs: Dict[str, Any] = None,
        output_keys: list[str] = None,
        params: Dict[str, Any] = None,
        timestamp: datetime = None,
        execution_mode: ExecutionMode = ExecutionMode.EXCLUSIVE,
    ) -> None:
        super().__init__()
        self.id = id
        self.type = type
        self.inputs = inputs or {}
        self.output_keys = output_keys or []
        self.params = params or {}
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.execution_mode = execution_mode

    def __str__(self) -> str:
        return (
            f"TaskAssignmentMessage("
            f"id={self.id}, "
            f"type={self.type}, "
            f"inputs={self.inputs}, "
            f"output_keys={self.output_keys}, "
            f"params={self.params}, "
            f"timestamp={self.timestamp}, "
            f"execution_mode={self.execution_mode})"
        )


class TaskClaimRequest(Data):
    """Task claim request sent by agents to orchestrator."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
        }

    def __init__(self, task_id: str, agent_id: str, timestamp: Optional[datetime] = None) -> None:
        super().__init__()
        self.task_id = task_id
        self.agent_id = agent_id
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def __str__(self) -> str:
        return f"TaskClaimRequest(task_id={self.task_id}, agent_id={self.agent_id}, timestamp={self.timestamp})"


class TaskAllocationMessage(Data):
    """Task allocation message sent by orchestrator to agents."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "assigned_agent_id": self.assigned_agent_id,
            "timestamp": self.timestamp.isoformat(),
        }

    def __init__(self, task_id: str, assigned_agent_id: str, timestamp: Optional[datetime] = None) -> None:
        super().__init__()
        self.task_id = task_id
        self.assigned_agent_id = assigned_agent_id
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def __str__(self) -> str:
        return f"TaskAllocationMessage(task_id={self.task_id}, assigned_agent_id={self.assigned_agent_id}, timestamp={self.timestamp})"


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
            "agent_id": self.agent_id,
        }

    def __init__(
        self,
        id: str,
        state: TaskState,
        outputs: Dict[str, Any] = None,
        error: Optional[TaskError] = None,
        timestamp: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.state = state
        self.outputs = outputs or {}
        self.error = error
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.duration_ms = duration_ms
        self.agent_id = agent_id

    def __str__(self) -> str:
        return (
            f"TaskCompletionMessage("
            f"id={self.id}, "
            f"state={self.state}, "
            f"outputs={self.outputs}, "
            f"error={self.error}, "
            f"timestamp={self.timestamp}, "
            f"duration_ms={self.duration_ms}, "
            f"agent_id={self.agent_id})"
        )


class TaskCompletionAckMessage(Data):
    """Task completion acknowledgement message sent by orchestrator."""

    @property
    def __data__(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "accepted_agent_id": self.accepted_agent_id,
            "timestamp": self.timestamp.isoformat(),
        }

    def __init__(
        self,
        id: str,
        state: TaskState,
        accepted_agent_id: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        super().__init__()
        self.id = id
        self.state = state
        self.accepted_agent_id = accepted_agent_id
        self.timestamp = timestamp or datetime.now(timezone.utc)

    def __str__(self) -> str:
        return f"TaskCompletionAckMessage(id={self.id}, state={self.state}, accepted_agent_id={self.accepted_agent_id}, timestamp={self.timestamp})"
