from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


SCHEMA_VERSION = "2026-05-07"


class ErrorEnvelope(BaseModel):
    message: str
    rc: Optional[int] = None
    line: Optional[int] = None
    command: Optional[str] = None
    log_path: Optional[str] = None
    details: Optional[str] = None


class ArtifactRef(BaseModel):
    kind: str
    path: str
    title: Optional[str] = None
    mime_type: Optional[str] = None
    format: Optional[str] = None


class LogRef(BaseModel):
    path: Optional[str] = None
    offset: Optional[int] = None
    next_offset: Optional[int] = None
    tail: Optional[str] = None


class ToolEnvelope(BaseModel):
    schema_version: str = SCHEMA_VERSION
    tool: str
    success: bool
    session_id: Optional[str] = None
    data: Optional[Dict[str, Any] | List[Any] | str] = None
    error: Optional[ErrorEnvelope] = None
    artifacts: List[ArtifactRef] = Field(default_factory=list)
    log: Optional[LogRef] = None
    warnings: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class CommandResponse(BaseModel):
    command: str
    success: bool
    rc: int
    error: Optional[ErrorEnvelope] = None
    log_path: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    smcl_output: Optional[str] = None
    artifacts: Optional[List[Dict[str, Any]]] = None

    @property
    def error_message(self) -> Optional[str]:
        return self.error.message if self.error else None


class DataResponse(BaseModel):
    start: int
    count: int
    data: List[Dict[str, Any]]


class VariableInfo(BaseModel):
    name: str
    label: Optional[str] = None
    type: Optional[str] = None


class VariablesResponse(BaseModel):
    variables: List[VariableInfo]


class GraphInfo(BaseModel):
    name: str
    active: bool = False
    created: Optional[str] = None


class GraphListResponse(BaseModel):
    graphs: List[GraphInfo]


class GraphExport(BaseModel):
    name: str
    file_path: Optional[str] = None
    format: Optional[str] = None
    mime_type: Optional[str] = None


class GraphExportResponse(BaseModel):
    graphs: List[GraphExport]


class SessionInfo(BaseModel):
    id: str
    status: str
    created_at: str
    pid: Optional[int] = None


class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]


class TaskResult(BaseModel):
    task_id: str
    status: Literal["started", "running", "done", "failed", "timeout", "not_found", "cancelling"]
    kind: Optional[str] = None
    created_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    error_details: Optional[ErrorEnvelope] = None


class LogMatch(BaseModel):
    line: int
    content: str
    context: List[str]


class LogReadResult(BaseModel):
    path: str
    offset: Optional[int] = None
    next_offset: Optional[int] = None
    data: Optional[str] = None
    query: Optional[str] = None
    truncated: Optional[bool] = None
    matches: List[LogMatch] = Field(default_factory=list)
    error: Optional[str] = None
