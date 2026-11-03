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
    id: int         # names this one path, so it can be removed
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
    # Save a library whose file could not be read, having been told what that
    # costs. Defaults to false so the refusal has to be answered rather than
    # worked around by accident; see UnreadableLibrary.
    save_unreadable: bool = False

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
    # The runs, each written for the asking machine. Runs off the share --
    # on an instrument's own disk -- are kept and shown exactly as written.
    display_source_runs: List[str] = []
    # How many people use this library, and who: each name has starred it once
    stars: int = 0
    starred_by: List[str] = []
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


class LibraryVersion(BaseModel):
    """One thing that happened to a library.

    *data* is a snapshot of the typed fields as they stood afterwards, so two
    neighbouring rows compared give what changed. *changed_by* is whatever the
    browser said; there are no accounts, so it is null for anything done
    before someone gave a name, or by hand.
    """
    model_config = ConfigDict(from_attributes=True)
    id: int
    recorded_at: datetime
    event: str
    changed_by: Optional[str] = None
    changed_from: Optional[str] = None  # the computer, by name or address
    data: dict


class DuplicateLibrary(BaseModel):
    """What a save is told when the file is already catalogued.

    Carries the entry it matched so the caller can offer to add the path to it
    rather than making a second entry for the same bytes.
    """
    message: str
    library_id: int
    paths: List[str] = []        # as the asking machine writes them
    already_recorded: bool = False  # this exact path is one of them
    # The entry it matched was deleted. The offer is to restore it rather than
    # to add a path, and the message above already says when it went.
    deleted: bool = False

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
    # Set when the catalog already holds this file. Not an error -- Auto-fill
    # has read the file and can say so now, rather than letting a whole form
    # be filled in for a save that cannot go through.
    duplicate: Optional[DuplicateLibrary] = None


class UnreadableLibrary(BaseModel):
    """What a save is told when the file is there but will not parse.

    Not an error: a real file in a format SpecVault does not know is still
    worth cataloguing, and it has a hash, so the entry can still be
    recognised later. What it costs is everything the library itself would
    have said -- and saying so before the save rather than after is the
    difference between a decision and a surprise.

    A file that is *not* there is refused outright instead, with no way to
    confirm past it: no file means no hash, and no hash means an entry
    nothing can ever match.
    """
    unreadable: bool = True   # tells this apart from the duplicate 409
    message: str
    path: str                 # as the asking machine writes it
    missing: List[str] = []   # what the entry will not hold, in words


class RestoreRequest(BaseModel):
    """What a restore should put back, beyond the entry itself.

    *details* replaces the metadata, for somebody who deleted a library
    because it was catalogued wrongly and has just filled the form in again.
    Left out, the entry comes back exactly as it was.

    *path* is where the file is now, and is recorded either way: that is a
    fact about the file rather than a judgement about the entry, and an entry
    restored pointing only at somewhere the file has left is no use to
    anybody.
    """
    details: Optional[LibraryUpdate] = None
    path: Optional[str] = None

class HashLookupRequest(BaseModel):
    path: str

class HashLookupResponse(BaseModel):
    content_hash: Optional[str] = None
    error: Optional[str] = None
