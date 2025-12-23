from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class ErrorEnvelope(BaseModel):
    message: str
    rc: Optional[int] = None
    line: Optional[int] = None
    command: Optional[str] = None
    log_path: Optional[str] = None
    context: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    snippet: Optional[str] = None
    trace: Optional[bool] = None


class CommandResponse(BaseModel):
    command: str
    rc: int
    stdout: str
    stderr: Optional[str] = None
    log_path: Optional[str] = None
    success: bool
    error: Optional[ErrorEnvelope] = None


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


class GraphListResponse(BaseModel):
    graphs: List[GraphInfo]


class GraphExport(BaseModel):
    name: str
    file_path: Optional[str] = None
    image_base64: Optional[str] = None


class GraphExportResponse(BaseModel):
    graphs: List[GraphExport]

