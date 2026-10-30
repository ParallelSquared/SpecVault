from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, field_validator

class ModDetail(BaseModel):
    """One modification at one site, as the library writes it.

    *name* is the library's own spelling -- a DIA-NN export may call its label
    nothing more descriptive than "tag" -- while *identified_as* is the tag
    whose mass it matches and *channel* which channel of it. A label we have no
    definition for still reports its measured *mass*, which is the point: an
    unrecognised tag should look unrecognised, not be forced onto the nearest
    channel we happen to know.
    """
    name: str
    site: str                              # "N-term", or a residue letter
    precursors: int
    mass: Optional[float] = None           # Da, solved from the precursor m/z
    identified_as: Optional[str] = None    # e.g. "PSMtag"
    channel: Optional[str] = None          # e.g. "0", "4"
    # What the modification should weigh, where that is known. A mass that
    # disagrees means the library declares the modification without carrying
    # its mass -- see the analyze warning.
    expected_mass: Optional[float] = None


class LibraryPathInfo(BaseModel):
    """One of a library's paths, as somebody looking at it needs it."""
    path: str       # share-relative, the stored form
    display: str    # written the way the asking machine writes paths
    exists: bool    # whether the file is actually there right now


class LibraryBase(BaseModel):
    path: str
    creator: str
    instrument: Optional[str] = None
    acquisition_type: Optional[str] = None
    vendor: Optional[str] = None
    species: Optional[str] = None
    tags: Optional[List[str]] = None
    project: Optional[str] = None
    finetuning: Optional[str] = None
    search_algorithm: Optional[str] = None
    software_version: Optional[str] = None
    date_generated: Optional[date] = None
    mbr: Optional[bool] = None
    source_runs: Optional[List[str]] = None
    notes: Optional[str] = None
    cell_types: Optional[List[str]] = None
    tissues: Optional[List[str]] = None
    protease: Optional[str] = None
    carbamidomethylated: Optional[bool] = None
    ptms: Optional[List[str]] = None
    creation_log_path: Optional[str] = None
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
    vendor: Optional[str] = None
    species: Optional[str] = None
    tags: Optional[List[str]] = None
    project: Optional[str] = None
    finetuning: Optional[str] = None
    search_algorithm: Optional[str] = None
    software_version: Optional[str] = None
    date_generated: Optional[date] = None
    mbr: Optional[bool] = None
    source_runs: Optional[List[str]] = None
    notes: Optional[str] = None
    cell_types: Optional[List[str]] = None
    tissues: Optional[List[str]] = None
    protease: Optional[str] = None
    carbamidomethylated: Optional[bool] = None
    ptms: Optional[List[str]] = None
    creation_log_path: Optional[str] = None
    fasta_path: Optional[str] = None
    in_silico: Optional[str] = None

class LibraryResponse(LibraryBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # Required when adding a library -- LibraryBase says so -- but optional
    # coming back. A library whose paths have somehow gone is a thing to see
    # and fix in the catalog, and making it unserialisable means the listing
    # fails as a whole: one damaged row and nobody can read any of them.
    path: Optional[str] = None
    # Built by the server from the saved file, never taken from a request
    content_hash: Optional[str] = None
    precursors: Optional[int] = None
    proteins: Optional[int] = None
    mod_details: Optional[List[ModDetail]] = None
    library_stats: Optional[dict] = None  # precursors, fragments, digest
    ion_mobility: Optional[bool] = None   # read off library_stats
    decoys: Optional[int] = None          # read off library_stats
    date_created: datetime
    updated_at: Optional[datetime] = None
    path_exists: bool = False
    file_format: Optional[str] = None
    file_size: Optional[int] = None  # bytes; frontend formats for display
    # The stored paths above are share-relative, which is what makes the same
    # library one entry whoever adds it. These are the same paths written the
    # way the machine that asked writes them -- what the UI shows and copies.
    display_path: Optional[str] = None
    display_creation_log_path: Optional[str] = None
    display_fasta_path: Optional[str] = None
    # Every place this library's file is known to be. The first is where it was
    # catalogued and the one whose file was read; `path` above is that one.
    paths: List[str] = []
    # The same list with each one written for the asking machine and said to be
    # there or not. path_exists above is true when any of them is: a library
    # kept in two places is still reachable when one of them is offline.
    path_details: List[LibraryPathInfo] = []

    @field_validator('paths', mode='before')
    @classmethod
    def flatten_paths(cls, v):
        """The relationship gives LibraryPath rows; the API gives strings."""
        return [p if isinstance(p, str) else p.path for p in (v or [])]


class AddPathRequest(BaseModel):
    """Another place an existing library's file is."""
    path: str


class DuplicateLibrary(BaseModel):
    """What a save is told when the file is already catalogued.

    Carries the entry it matched so the caller can offer to add the path to it
    rather than making a second entry for the same bytes.
    """
    message: str
    library_id: int
    paths: List[str] = []        # as the asking machine writes them
    already_recorded: bool = False  # this exact path is one of them

# New schemas for the analyze endpoint
class AnalyzeRequest(BaseModel):
    path: str
    # The creation log, if the user has given one; otherwise one is looked for
    # in the library's folder
    creation_log_path: Optional[str] = None

class LogRequest(BaseModel):
    path: str

class LogResponse(BaseModel):
    """What the creation log says, when one was given or found."""
    creation_log_path: Optional[str] = None
    search_algorithm: Optional[str] = None
    software_version: Optional[str] = None
    date_generated: Optional[date] = None
    fasta_path: Optional[str] = None
    source_runs: List[str] = []
    mbr: Optional[bool] = None
    vendor: Optional[str] = None  # from the source runs' file types
    warning: Optional[str] = None  # e.g. "file read but some columns missing"

class AnalyzeResponse(LogResponse):
    precursors: Optional[int] = None
    proteins: Optional[int] = None
    protease: Optional[str] = None
    carbamidomethylated: Optional[bool] = None
    ptms: List[str] = []
    tags: List[str] = []
    mod_details: List[ModDetail] = []

class HashLookupRequest(BaseModel):
    path: str

class HashLookupResponse(BaseModel):
    content_hash: Optional[str] = None
    error: Optional[str] = None
