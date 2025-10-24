
from dataclasses import dataclass, field
from asyncio import Event, Task
import socket
from enum import Enum
from pydantic import BaseModel
from typing import Optional, Literal, List, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .unix_socket_manager import UnixSocketManager


class AgentType(str, Enum):
    """Predefined agent types matching Claude Code's Task tool."""
    GENERAL_PURPOSE = "general-purpose"
    EXPLORE = "Explore"
    STATUSLINE_SETUP = "statusline-setup"
    OUTPUT_STYLE_SETUP = "output-style-setup"

@dataclass
class ClaudeJobResult:
    worker_id: str
    returncode: int
    stdout: str
    stderr: str
    output_file: str  # Absolute path to logs/worker-{id}.json


@dataclass
class ActiveTask:
    worker_id: str
    task: Task[ClaudeJobResult]
    permission_socket: Optional[socket.socket] = None


class CompleteTask(BaseModel):
    """Completed worker task with output."""
    worker_id: str
    claude_session_id: str
    conversation_history_file_path: str  # Absolute path to logs/worker-{id}.json


class FailedTask(BaseModel):
    """Failed worker task with error details."""
    worker_id: str
    returncode: int
    conversation_history_file_path: Optional[str]  # Path to partial output if exists
    error_hint: str  # Brief actionable hint (max 150 chars)


class WorkerStatus(Enum):
    """Enum for tracking worker lifecycle state."""
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Worker:
    """Unified worker registry entry with explicit state management."""
    worker_id: str
    status: WorkerStatus
    task: Optional[Task[ClaudeJobResult]] = None
    complete_task: Optional[CompleteTask] = None
    socket_mgr: Optional['UnixSocketManager'] = None  # Forward reference
    agent_type: Optional[AgentType] = None


class PermissionRequest(BaseModel):
    """Permission request data returned to client and used for wire format."""
    request_id: str
    worker_id: str
    tool: str
    input: dict


# Event models for event-driven polling
class CompletionEvent(BaseModel):
    """Event: worker completed successfully."""
    worker_id: str
    task: 'CompleteTask'


class FailureEvent(BaseModel):
    """Event: worker failed."""
    worker_id: str
    task: 'FailedTask'


class PermissionEvent(BaseModel):
    """Event: worker requesting permission."""
    worker_id: str
    permission: PermissionRequest


# Union type for queue
WorkerEvent = Union[CompletionEvent, FailureEvent, PermissionEvent]


@dataclass
class PendingPermission:
    request_id: str
    worker_id: str
    tool: str
    input: dict
    event: Event
    socket: socket
    response: Optional['PermissionResponseMessage'] = None  # Type-safe response


class WorkerState(BaseModel):
    """
    Unified worker state snapshot.

    Combines completed task results with live permission request state.
    Returned by wait() to provide complete visibility into worker status.
    """
    completed: List[CompleteTask]
    failed: List[FailedTask]
    pending_permissions: List[PermissionRequest]


class PermissionResponse(BaseModel):
    """Permission decision response from proxy."""
    behavior: Literal["allow", "deny"]
    updatedInput: Optional[dict] = None  # Only for "allow"
    message: Optional[str] = None  # Only for "deny"

    @classmethod
    def allow(cls, updated_input: Optional[dict] = None) -> "PermissionResponse":
        """Create an allow response."""
        return cls(behavior="allow", updatedInput=updated_input)

    @classmethod
    def deny(cls, message: str) -> "PermissionResponse":
        """Create a deny response."""
        return cls(behavior="deny", message=message)


# Wire format models for socket communication

class PermissionResponseMessage(BaseModel):
    """Wire format: permission response sent from parent → worker via socket."""
    request_id: str
    allow: bool
    updatedInput: Optional[dict] = None  # Present when allow=True (camelCase for Claude)
    message: Optional[str] = None  # Present when allow=False


# Discriminated union return types for wait_for_worker

class WorkerCompleted(BaseModel):
    """Worker completed successfully."""
    status: Literal["completed"] = "completed"
    worker_id: str
    conversation_history_file_path: str
    session_id: str


class WorkerFailed(BaseModel):
    """Worker failed with error."""
    status: Literal["failed"] = "failed"
    worker_id: str
    error_hint: str
    conversation_history_file_path: Optional[str] = None


class PermissionNeeded(BaseModel):
    """Worker needs permission approval."""
    status: Literal["permission_needed"] = "permission_needed"
    worker_id: str
    request_id: str
    tool: str
    input: dict


class WaitTimedOut(BaseModel):
    """Wait timed out without events."""
    status: Literal["timed_out"] = "timed_out"
    message: str = "No worker events occurred within timeout"


# Discriminated union type for wait_for_worker return
WorkerResult = Union[WorkerCompleted, WorkerFailed, PermissionNeeded, WaitTimedOut]


class WorkerOptions(BaseModel):
    model: Optional[str] = "claude-sonnet-4-5"
    temperature: Optional[float] = 1.0
    max_tokens: Optional[int]
    thinking: Optional[bool] = False
    top_p: Optional[float] = None
    top_k: Optional[int] = None
