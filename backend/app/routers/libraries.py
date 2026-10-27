import hashlib
import os
import re
from datetime import datetime
from typing import List, Optional

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/libraries", tags=["libraries"])

# Page size for GET /libraries/. The old default of 100 was applied silently,
# so a catalog of 101 libraries looked exactly like a catalog of 100.
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 2000

COLUMN_ALIASES = {
    "Modified.Sequence": [
        "Modified.Sequence",
        "ModifiedPeptide",
        "ModifiedSequence",
    ],
    "Stripped.Sequence": [
        "Stripped.Sequence",
        "StrippedPeptide",
        "PeptideSequence",
    ],
    "Protein.Group": [
        "Protein.Group",
        "ProteinGroup",
    ],
    "Precursor.Charge": [
        "Precursor.Charge",
        "PrecursorCharge",
    ],
}


def _read_library_df(path: str) -> pl.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tsv", ".txt"):
        lf = pl.scan_csv(path, separator="\t")
    elif ext == ".csv":
        lf = pl.scan_csv(path)
    elif ext == ".parquet":
        lf = pl.scan_parquet(path)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    # collect_schema() reads only the header -- no data is loaded yet
    available = lf.collect_schema().names()
    needed = []
    for aliases in COLUMN_ALIASES.values():
        needed.extend(a for a in aliases if a in available)

    if not needed:
        raise ValueError("None of the expected columns were found in this file")

    lf = lf.select(needed)  # only pull the handful of columns we actually need
    return lf.collect(engine="streaming")  # streaming keeps memory bounded even for huge files


def _get_column(df, canonical):
    return next((col for col in COLUMN_ALIASES[canonical] if col in df.columns), None)

# Every helper below reads the WHOLE column. They used to score a "sample" of
# df[col].unique().to_list()[:1000], but .unique() makes no ordering promise, so
# the same file analysed twice could yield different PTMs or a different
# carbamidomethylation flag. Whole-column polars expressions are both
# deterministic and considerably faster than looping in Python.

UNIMOD_PATTERN = r"UniMod:\d+"
CARBAMIDOMETHYL = "UniMod:4"  # compared exactly, so UniMod:40 is not a match
TAG_OPTIONS = ["PSMtag", "dimethyl", "SILAC", "K_6C13", "diethyl", "mtraq"]

# A tag is a modification name, so it only counts inside a modification
# annotation -- "(SILAC)", "[Dimethyl]". Searching the bare sequence also
# matched runs of amino acids: SILAC, MTRAQ, PSMTAG, DIETHYL and DIMETHYL are
# all spellable in one-letter codes, so the perfectly ordinary unmodified
# peptide PEPTIDESILACK was reported as a SILAC library. At ~1M precursors
# that collision is expected to happen several times over by chance, and one
# hit was enough to mislabel the whole file.
ANNOTATION_PATTERN = r"\([^()]*\)|\[[^\[\]]*\]"

PROTEASES = {
    "Trypsin":      {"residues": {"K", "R"}, "side": "C"},
    "GluC":         {"residues": {"E"},      "side": "C"},
    "ArgC":         {"residues": {"R"},      "side": "C"},
    "AspN":         {"residues": {"D"},      "side": "N"},
    "LysC":         {"residues": {"K"},      "side": "C"},
    "Chymotrypsin": {"residues": {"F", "W", "Y"}, "side": "C"},
}

# A protease is only named if the best-fitting rule explains at least this share
# of peptide termini. Without a floor, non-enzymatic peptides still produced a
# confident-looking answer off a near-zero score.
MIN_PROTEASE_CONFIDENCE = 0.6


def _unique_sequences(df: pl.DataFrame, canonical: str) -> Optional[pl.Series]:
    """Distinct non-null, non-empty values of a sequence column; None if absent."""
    col = _get_column(df, canonical)
    if col is None:
        return None
    seqs = df[col].drop_nulls().unique()
    return seqs.filter(seqs.str.len_chars() > 0)


def _unimod_accessions(sequences: pl.Series) -> set:
    """Every distinct UniMod accession appearing in the sequences."""
    if sequences.is_empty():
        return set()
    exploded = sequences.str.extract_all(UNIMOD_PATTERN).explode(empty_as_null=False)
    return set(exploded.drop_nulls().to_list())


def _determine_precursors(df: pl.DataFrame) -> Optional[int]:
    modified_col = _get_column(df, "Modified.Sequence")
    charge_col = _get_column(df, "Precursor.Charge")

    if modified_col is None or charge_col is None:
        return None

    return (
        df.select([pl.col(modified_col), pl.col(charge_col)])
        .drop_nulls()
        .unique()
        .height
    )


def _determine_proteins(df: pl.DataFrame) -> Optional[int]:
    col = _get_column(df, "Protein.Group")
    if col is None:
        return None
    # Null and empty groups are not proteins; n_unique() used to count them as one.
    groups = (
        df[col].drop_nulls().str.split(";")
        .explode(empty_as_null=False)
        .str.strip_chars()
        .drop_nulls()
    )
    return groups.filter(groups != "").n_unique()


def _determine_protease(df: pl.DataFrame) -> Optional[str]:
    peptides = _unique_sequences(df, "Stripped.Sequence")
    if peptides is None or peptides.is_empty():
        return None

    total = peptides.len()
    n_term = peptides.str.slice(0, 1)
    c_term = peptides.str.slice(-1, 1)

    scores = {}
    for name, rule in PROTEASES.items():
        terminus = n_term if rule["side"] == "N" else c_term
        scores[name] = terminus.is_in(sorted(rule["residues"])).sum() / total

    max_score = max(scores.values())
    if max_score < MIN_PROTEASE_CONFIDENCE:
        return None  # nothing fits well enough to name a protease

    # Among near-ties prefer the most specific rule: LysC (K) over Trypsin (K/R).
    candidates = [p for p, s in scores.items() if max_score - s <= 0.1]
    return min(candidates, key=lambda p: (len(PROTEASES[p]["residues"]), -scores[p]))


def _determine_carbamidomethylated(df: pl.DataFrame) -> Optional[bool]:
    sequences = _unique_sequences(df, "Modified.Sequence")
    if sequences is None:
        return None
    return CARBAMIDOMETHYL in _unimod_accessions(sequences)


def _determine_mods(df: pl.DataFrame) -> List[str]:
    sequences = _unique_sequences(df, "Modified.Sequence")
    if sequences is None:
        return []
    mods = _unimod_accessions(sequences)
    mods.discard(CARBAMIDOMETHYL)  # tracked separately as carbamidomethylation
    return sorted(mods, key=lambda m: int(m.split(":")[1]))


def _modification_annotations(sequences: pl.Series) -> pl.Series:
    """The bracketed modification annotations, with their delimiters."""
    return (
        sequences.str.extract_all(ANNOTATION_PATTERN)
        .explode(empty_as_null=False)
        .drop_nulls()
    )


def _determine_tags(df: pl.DataFrame) -> List[str]:
    sequences = _unique_sequences(df, "Modified.Sequence")
    if sequences is None:
        return []
    annotations = _modification_annotations(sequences)
    if annotations.is_empty():
        return ["LF"]
    tags = sorted(
        tag for tag in TAG_OPTIONS
        if annotations.str.contains("(?i)" + re.escape(tag)).any()
    )
    return tags if tags else ["LF"]


def _find_missing_columns(df: pl.DataFrame) -> list[str]:
    missing = []

    for canonical, aliases in COLUMN_ALIASES.items():
        if not any(alias in df.columns for alias in aliases):
            missing.append(canonical)

    return missing

def _hash_file(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    sha256 = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):  # 1MB chunks
                sha256.update(chunk)
    except OSError:
        return None
    return sha256.hexdigest()
    

@router.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze_library(payload: schemas.AnalyzeRequest):
    path = payload.path.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
        path = path[1:-1].strip()

    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="File not found at that path")

    content_hash = _hash_file(path)
    if content_hash is None:
        raise HTTPException(status_code=400, detail="Could not read file to compute hash")

    try:
        df = _read_library_df(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    warning = None
    missing = _find_missing_columns(df)
    if missing:
        warning = (
            "Missing expected columns, some fields could not be detected: "
            + ", ".join(sorted(missing))
        )

    return schemas.AnalyzeResponse(
        precursors=_determine_precursors(df),
        proteins=_determine_proteins(df),
        protease=_determine_protease(df),
        carbamidomethylated=_determine_carbamidomethylated(df),
        ptms=_determine_mods(df),
        tags=_determine_tags(df),
        content_hash=content_hash,
        warning=warning,
    )

@router.post("/hash-file")
def hash_file(payload: schemas.AnalyzeRequest):  # reusing AnalyzeRequest since it's just {path: str}
    path = payload.path.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
        path = path[1:-1].strip()

    if not os.path.exists(path):
        return {"error": "File not found at that path"}

    file_hash = _hash_file(path)
    if file_hash is None:
        return {"error": "Could not read file to compute hash"}

    return {"content_hash": file_hash}

def _to_response(lib: models.Library) -> schemas.LibraryResponse:
    data = schemas.LibraryResponse.model_validate(lib)
    exists = os.path.exists(lib.path)
    data.path_exists = exists

    _, ext = os.path.splitext(lib.path)
    data.file_format = ext.lstrip('.').upper() if ext else None

    if exists:
        try:
            data.file_size = os.path.getsize(lib.path)
            data.updated_at = datetime.fromtimestamp(os.path.getmtime(lib.path))
        except OSError:
            data.file_size = None
            data.updated_at = None
    else:
        data.file_size = None
        data.updated_at = None

    return data

# IMPORTANT: this must be declared before the /{library_id} route below,
# or FastAPI will try to parse "options" as an integer library_id and fail.
@router.get("/options")
def get_field_options(db: Session = Depends(get_db)):
    simple_fields = [
        "creator", "instrument", "acquisition_type", "species",
        "project", "finetuning", "search_algorithm", "protease",
        "in_silico",
    ]
    options = {}
    for field in simple_fields:
        col = getattr(models.Library, field)
        rows = db.query(col).filter(col.isnot(None), col != "").distinct().all()
        options[field] = sorted({r[0] for r in rows if r[0]})

    # List-type fields store JSON arrays — flatten distinct values across all rows
    list_fields = ["cell_types", "tissues", "ptms", "tags"]
    for field in list_fields:
        col = getattr(models.Library, field)
        rows = db.query(col).filter(col.isnot(None)).all()
        values = set()
        for (row_list,) in rows:
            if row_list:
                values.update(row_list)
        options[field] = sorted(values)

    return options


@router.post("/", response_model=schemas.LibraryResponse, status_code=201)
def create_library(library: schemas.LibraryCreate, db: Session = Depends(get_db)):
    data = library.model_dump()
    if not data.get("content_hash"):
        data["content_hash"] = _hash_file(data["path"])  # fallback: full separate read, only if auto-fill wasn't used
    db_library = models.Library(**data)
    db.add(db_library)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A library with this path already exists")
    db.refresh(db_library)
    return _to_response(db_library)

@router.patch("/{library_id}", response_model=schemas.LibraryResponse)
def update_library(library_id: int, updates: schemas.LibraryUpdate, db: Session = Depends(get_db)):
    library = db.query(models.Library).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    update_data = updates.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(library, field, value)
    if "path" in update_data:  # path changed, hash needs recomputing
        library.content_hash = _hash_file(library.path)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A library with this path already exists")
    db.refresh(library)
    return _to_response(library)

@router.get("/", response_model=List[schemas.LibraryResponse])
def list_libraries(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
):
    # X-Total-Count lets the client tell a complete result from a truncated page.
    # Without it a client that asked for one page rendered it as the whole
    # catalog. Exposed to the browser via expose_headers in main.py.
    total = db.query(func.count(models.Library.id)).scalar()
    response.headers["X-Total-Count"] = str(total)

    rows = (
        db.query(models.Library)
        .order_by(models.Library.id)  # stable order, or paging repeats/skips rows
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_to_response(row) for row in rows]

@router.get("/{library_id}", response_model=schemas.LibraryResponse)
def get_library(library_id: int, db: Session = Depends(get_db)):
    library = db.query(models.Library).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return _to_response(library)

@router.delete("/{library_id}", status_code=204)
def delete_library(library_id: int, db: Session = Depends(get_db)):
    library = db.query(models.Library).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    db.delete(library)
    db.commit()