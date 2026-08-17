import hashlib
import os
import re
from datetime import datetime
from typing import List, Optional

import polars as pl
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/libraries", tags=["libraries"])

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

    # lf.columns reads only the schema (fast, no data loaded yet)
    available = lf.columns
    needed = []
    for aliases in COLUMN_ALIASES.values():
        needed.extend(a for a in aliases if a in available)

    if not needed:
        raise ValueError("None of the expected columns were found in this file")

    lf = lf.select(needed)  # only pull the handful of columns we actually need
    return lf.collect(engine="streaming")  # streaming keeps memory bounded even for huge files


def _get_column(df, canonical):
    return next((col for col in COLUMN_ALIASES[canonical] if col in df.columns), None)

def _determine_precursors(df: pl.DataFrame) -> Optional[int]:
    modified_col =  _get_column(df, "Modified.Sequence")
    charge_col =  _get_column(df, "Precursor.Charge")

    if modified_col is None or charge_col is None:
        return None

    return (df.select([pl.col(modified_col), pl.col(charge_col)]).unique().height)

def _determine_proteins(df: pl.DataFrame) -> Optional[int]:
    col = _get_column(df, "Protein.Group")
    if col is None:
        return None
    return df[col].str.split(";").explode(empty_as_null=False).n_unique()


def _determine_protease(df: pl.DataFrame) -> Optional[str]:
    col = _get_column(df, "Stripped.Sequence")
    if col is None:
        return None
    
    stripped_sequences = df[col].unique().to_list()[:1000]
   
    proteases = {
        "Trypsin":      {"residues": {"K", "R"}, "side": "C"},
        "GluC":         {"residues": {"E"},      "side": "C"},
        "ArgC":         {"residues": {"R"},      "side": "C"},
        "AspN":         {"residues": {"D"},      "side": "N"},
        "LysC":         {"residues": {"K"},      "side": "C"},
        "Chymotrypsin": {"residues": {"F", "W", "Y"}, "side": "C"},
    }
    scores = {}
    for name, rule in proteases.items():
        matches = total = 0
        for pep in stripped_sequences:
            if not pep:
                continue
            aa = pep[0] if rule["side"] == "N" else pep[-1]
            matches += aa in rule["residues"]
            total += 1
        scores[name] = matches / total if total else 0

    if not scores:
        return None
    max_score = max(scores.values())
    candidates = [p for p, s in scores.items() if max_score - s <= 0.1]
    best = min(candidates, key=lambda p: (len(proteases[p]["residues"]), -scores[p]))
    return best

def _determine_carbamidomethylated(df: pl.DataFrame) -> Optional[bool]:

    col = _get_column(df, "Modified.Sequence")
    if col is None:
        return None
        
    modified_sequences = df[col].unique().to_list()[:1000]

    return any("UniMod:4" in seq for seq in modified_sequences)

def _determine_mods(df: pl.DataFrame) -> List[str]:
    col = _get_column(df, "Modified.Sequence")
    if col is None:
        return []
        
    modified_sequences = df[col].unique().to_list()[:1000]
    
    mods = set()
    for seq in modified_sequences:
        mods.update(re.findall(r"UniMod:\d+", seq))
    mods.discard("UniMod:4")  # tracked separately as carbamidomethylation
    return sorted(mods)

def _determine_tags(df: pl.DataFrame) -> List[str]:
    col = _get_column(df, "Modified.Sequence")
    if col is None:
        return []
        
    modified_sequences = df[col].unique().to_list()[:1000]
    
    tag_options = ["PSMtag", "dimethyl", "SILAC", "K_6C13", "diethyl", "mtraq"]
    tags = set()
    for seq in modified_sequences:
        for tag in tag_options:
            if tag.lower() in seq.lower():
                tags.add(tag)

    return sorted(tags) if tags else ["LF"]


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
def list_libraries(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(models.Library).offset(skip).limit(limit).all()
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