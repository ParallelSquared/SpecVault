from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator

class LibraryBase(BaseModel):
    path: str
    creator: str
    instrument: Optional[str] = None
    acquisition_type: Optional[str] = None
    species: Optional[str] = None
    tags: Optional[List[str]] = None
    project: Optional[str] = None
    finetuning: Optional[str] = None
    search_algorithm: Optional[str] = None
    notes: Optional[str] = None
    cell_types: Optional[List[str]] = None
    tissues: Optional[List[str]] = None
    protease: Optional[str] = None
    carbamidomethylated: Optional[bool] = None
    ptms: Optional[List[str]] = None
    creation_log_path: Optional[str] = None
    precursors: Optional[int] = None
    proteins: Optional[int] = None
    content_hash: Optional[str] = None
    fasta_path: Optional[str] = None
    in_silico: Optional[str] = None

    @field_validator('path', 'creation_log_path', 'fasta_path')
    @classmethod
    def clean_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
            v = v[1:-1].strip()
        return v

class LibraryCreate(LibraryBase):
    pass

class LibraryUpdate(BaseModel):
    path: Optional[str] = None
    creator: Optional[str] = None
    instrument: Optional[str] = None
    acquisition_type: Optional[str] = None
    species: Optional[str] = None
    tags: Optional[List[str]] = None
    project: Optional[str] = None
    finetuning: Optional[str] = None
    search_algorithm: Optional[str] = None
    notes: Optional[str] = None
    cell_types: Optional[List[str]] = None
    tissues: Optional[List[str]] = None
    protease: Optional[str] = None
    carbamidomethylated: Optional[bool] = None
    ptms: Optional[List[str]] = None
    creation_log_path: Optional[str] = None
    precursors: Optional[int] = None
    proteins: Optional[int] = None
    content_hash: Optional[str] = None
    fasta_path: Optional[str] = None
    in_silico: Optional[str] = None

class LibraryResponse(LibraryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    date_created: datetime
    updated_at: Optional[datetime] = None
    path_exists: bool = False
    file_format: Optional[str] = None
    file_size: Optional[int] = None  # bytes; frontend formats for display

# New schemas for the analyze endpoint
class AnalyzeRequest(BaseModel):
    path: str

class AnalyzeResponse(BaseModel):
    precursors: Optional[int] = None
    proteins: Optional[int] = None
    protease: Optional[str] = None
    carbamidomethylated: Optional[bool] = None
    ptms: List[str] = []
    tags: List[str] = []
    content_hash: Optional[str] = None
    warning: Optional[str] = None  # e.g. "file read but some columns missing"

class HashLookupRequest(BaseModel):
    path: str

class HashLookupResponse(BaseModel):
    content_hash: Optional[str] = None
    error: Optional[str] = None