from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class EvidenceFrame(BaseModel):
    timestamp_sec: float
    image_base64: str


class Violation(BaseModel):
    type: str
    timecode_sec: float
    description: str
    evidence_frames: List[EvidenceFrame] = Field(default_factory=list)


class JobProcessingResponse(BaseModel):
    job_id: str
    status: Literal["processing"]


class JobDoneResponse(BaseModel):
    job_id: str
    status: Literal["done"]
    verdict: Literal["violation", "no_violation"]
    violations: List[Violation] = Field(default_factory=list)


class JobFailedResponse(BaseModel):
    job_id: str
    status: Literal["failed"]
    error: str


class AnalyzeResponse(BaseModel):
    job_id: str