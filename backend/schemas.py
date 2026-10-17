from pydantic import BaseModel
from typing import List, Optional


class EvidenceFrame(BaseModel):
    timestamp_sec: float
    image_base64: str


class Violation(BaseModel):
    type: str
    timecode_sec: float
    description: str
    evidence_frames: List[EvidenceFrame]


class JobResponse(BaseModel):
    job_id: str
    status: str
    verdict: Optional[str] = None
    violations: List[Violation] = []