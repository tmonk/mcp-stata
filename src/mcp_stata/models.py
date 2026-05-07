from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, model_validator


class ErrorEnvelope(BaseModel):
    message: str
    rc: Optional[int] = None
    line: Optional[int] = None
    command: Optional[str] = None
    log_path: Optional[str] = None
    details: Optional[str] = None


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


class GraphExportResponse(BaseModel):
    graphs: List[GraphExport]


class SessionInfo(BaseModel):
    id: str
    status: str
    created_at: str
    pid: Optional[int] = None


class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]
