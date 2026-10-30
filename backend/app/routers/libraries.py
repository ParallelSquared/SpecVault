import hashlib
import os
import re
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import List, NamedTuple, Optional, Tuple

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import creation_log, library_stats, models, mods, schemas
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
    "Precursor.Mz": [
        "Precursor.Mz",
        "PrecursorMz",
    ],
}

# Precursor.Mz is what lets us work out each modification's mass, but a library
# without it is still perfectly analysable -- so its absence is not worth
# warning about the way a missing Protein.Group is.
OPTIONAL_COLUMNS = {"Precursor.Mz"}

# Where a library marks its decoys: DIA-NN writes "Decoy", the OpenSWATH-style
# exports "decoy", both as 0 or 1. Decoys are generated to estimate false
# discovery, not peptides anyone measured, and counting them inflated every
# library's precursors by 6-8% -- and, where a decoy kept its target's sequence
# at a different mass, faked the "several label channels" warning.
DECOY_COLUMNS = ["Decoy", "decoy"]


def _is_decoy(column: pl.Expr) -> pl.Expr:
    """True for decoy rows, read loosely enough for 1, 1.0, True or "true".
    A blank counts as a target: dropping rows on a missing value would lose
    real precursors."""
    text = column.cast(pl.String).str.strip_chars().str.to_lowercase()
    return text.is_in(["1", "1.0", "true"]).fill_null(False)


def _scan_library(path: str) -> pl.LazyFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tsv", ".txt"):
        return pl.scan_csv(path, separator="\t")
    if ext == ".csv":
        return pl.scan_csv(path)
    if ext == ".parquet":
        return pl.scan_parquet(path)
    raise ValueError(f"Unsupported file extension: {ext}")


def _read_library_df(path: str) -> pl.DataFrame:
    lf = _scan_library(path)

    # collect_schema() reads only the header -- no data is loaded yet
    available = lf.collect_schema().names()
    needed = []
    for aliases in COLUMN_ALIASES.values():
        needed.extend(a for a in aliases if a in available)

    if not needed:
        raise ValueError("None of the expected columns were found in this file")

    # A library has one row per fragment, and every column read here describes
    # the precursor, not the fragment -- so the same values repeat a dozen or
    # more times per precursor. Collapsing to distinct rows here, once, means no
    # step after this one ever sees a fragment row: on a 28-million-row library
    # that is 2.4 million rows and 185 MB instead of 2.2 GB. It changes no answer,
    # because nothing downstream depends on how often a row repeats, only on
    # which distinct rows exist. File order is kept so that the mass fit's
    # seeded sample, and so its result, is the same every time.
    decoy = next((c for c in DECOY_COLUMNS if c in available), None)
    if decoy is not None:
        lf = lf.filter(~_is_decoy(pl.col(decoy)))
    lf = lf.select(needed).unique(maintain_order=True)
    return lf.collect(engine="streaming")


def _get_column(df, canonical):
    return next((col for col in COLUMN_ALIASES[canonical] if col in df.columns), None)

# Every helper below reads the WHOLE column. They used to score a "sample" of
# df[col].unique().to_list()[:1000], but .unique() makes no ordering promise, so
# the same file analysed twice could yield different PTMs or a different
# carbamidomethylation flag. Whole-column polars expressions are both
# deterministic and considerably faster than looping in Python.

CARBAMIDOMETHYL = "UniMod:4"  # compared exactly, so UniMod:40 is not a match

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
    # Split each distinct group once: millions of precursors share a few tens of
    # thousands of groups, and splitting the same string again changes nothing.
    groups = (
        df[col].drop_nulls().unique().str.split(";")
        .explode(empty_as_null=False)
        .str.strip_chars()
        .drop_nulls()
    )
    return groups.filter(groups != "").n_unique()


def _determine_protease(df: pl.DataFrame) -> Optional[str]:
    peptides = _unique_sequences(df, "Stripped.Sequence")
    if peptides is None:
        return None
    return _protease_of(peptides)


def _protease_of(peptides: pl.Series) -> Optional[str]:
    if peptides.is_empty():
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


class ModReport(NamedTuple):
    """Everything we can say about a library's modifications, worked out once.

    Tags, PTMs and the detail table are three views of the same analysis, and
    the analysis reads every sequence in the library -- so it is done once here
    rather than three times over.
    """
    details: List[dict]
    ptms: List[str]
    tags: List[str]
    carbamidomethylated: Optional[bool]
    note: Optional[str]


EMPTY_MOD_REPORT = ModReport([], [], [], None, None)


def _ptm_order(name: str):
    """UniMod accessions in numeric order, then everything else alphabetically."""
    match = re.fullmatch(r"UniMod:(\d+)", name)
    return (0, int(match.group(1)), "") if match else (1, 0, name.lower())


def _mod_report(df: pl.DataFrame) -> ModReport:
    if _get_column(df, "Modified.Sequence") is None:
        return EMPTY_MOD_REPORT

    sites = mods.mod_sites(_precursor_sequences(df))
    # Read off the mod table rather than scanned for separately, so the flag
    # and the table can never disagree about whether UniMod:4 is there.
    carbamidomethylated = any(site.name == CARBAMIDOMETHYL for site in sites)
    if not sites:
        return ModReport([], [], ["LF"], carbamidomethylated, None)

    masses, note = _derive_masses(df, sorted({site.name for site in sites}))

    # A tag counts if the library names it -- "(dimethyl-0)" -- or if its mass
    # and site say so. The mass is what rescues a DIA-NN library that calls its
    # label nothing more descriptive than "(tag)", and the site is what keeps
    # the Lys and Arg SILAC labels apart, since 13C(6) weighs the same on both.
    tags, details = set(), []
    tagged_names, misweighed = set(), {}
    for site in sites:
        mass = masses.get(site.name)
        expected = mods.expected_mass(site.name)
        if mass is not None and expected is not None and abs(mass - expected) > mods.MASS_TOLERANCE:
            misweighed[site.name] = (mass, expected)
        matched = mods.identify_tag(mass, site.site)
        # Matched against the annotation's name, never the bare sequence:
        # SILAC, MTRAQ, PSMTAG, DIETHYL and DIMETHYL are all spellable in amino
        # acids, so the unmodified peptide PEPTIDESILACK once read as labelled.
        by_name = sorted(
            tag for tag in mods.TAG_OPTIONS
            if re.search("(?i)" + re.escape(tag), site.name)
        )
        named = sorted(set(by_name) | set(mods.tag_names(matched)))
        if named:
            tagged_names.add(site.name)
            tags.update(named)
        details.append({
            "name": site.name,
            "site": site.site,
            "precursors": site.precursors,
            "mass": round(mass, 5) if mass is not None else None,
            "identified_as": named[0] if named else None,
            "channel": matched[0].channel if len(matched) == 1 else None,
            "expected_mass": round(expected, 5) if expected is not None else None,
        })

    # A library can name a modification and leave its mass out of the precursor
    # m/z -- some of these libraries dropped carbamidomethyl's 57.0215 Da while
    # keeping every "(UniMod:4)" in place. Nothing downstream can detect that
    # from the annotations alone, and a search run against such a library is
    # wrong by the missing mass on every cysteine, so it is said out loud.
    #
    # A mass that is there but wrong is a different problem -- a mislabelled
    # annotation, or a library built with another mass for it -- and saying
    # "missing" about a modification weighing +16 Da would send whoever reads it
    # looking for the wrong fault.
    massless = {n: m for n, m in misweighed.items() if abs(m[0]) <= mods.MASS_TOLERANCE}
    mismatched = {n: m for n, m in misweighed.items() if n not in massless}
    if massless:
        listed = "; ".join(
            f"{name} weighs {found:+.5f} Da here but should weigh {should:+.5f}"
            for name, (found, should) in sorted(massless.items())
        )
        note = " ".join(filter(None, [note, (
            f"This library declares modifications whose mass is missing from its "
            f"precursor m/z: {listed}. Anything searched against it will be wrong "
            f"by that much wherever the modification occurs."
        )]))
    if mismatched:
        listed = "; ".join(
            f"{name} weighs {found:+.5f} Da here, but UniMod lists it as {should:+.5f}"
            for name, (found, should) in sorted(mismatched.items())
        )
        note = " ".join(filter(None, [note, (
            f"{listed}. Either the annotation names the wrong modification, or the "
            f"library was built with a different mass for it."
        )]))

    ptms = sorted(
        {site.name for site in sites} - tagged_names - {CARBAMIDOMETHYL},
        key=_ptm_order,
    )
    # No tag found means LF. An unidentified modification does not hold that
    # back: the field is a starting point the user edits, and the mod detail
    # table shows what was found either way.
    return ModReport(details, ptms, sorted(tags) or ["LF"], carbamidomethylated, note)


def _precursor_sequences(df: pl.DataFrame) -> pl.Series:
    """One modified sequence per precursor -- sequence and charge -- so that the
    mod table counts precursors rather than peptides. Without a charge column
    there is nothing to tell precursors apart, and it is one per sequence."""
    modified_col = _get_column(df, "Modified.Sequence")
    charge_col = _get_column(df, "Precursor.Charge")
    columns = [modified_col] + ([charge_col] if charge_col else [])
    sequences = df.select(columns).drop_nulls().unique()[modified_col]
    return sequences.filter(sequences.str.len_chars() > 0)


def _derive_masses(df: pl.DataFrame, names: List[str]):
    """Each modification's mass, and a note when they could not be worked out.
    *names* are the modifications already found, so they are not looked for twice."""
    stripped_col = _get_column(df, "Stripped.Sequence")
    charge_col = _get_column(df, "Precursor.Charge")
    mz_col = _get_column(df, "Precursor.Mz")
    if charge_col is None or mz_col is None:
        return {}, None

    modified_col = _get_column(df, "Modified.Sequence")
    stripped = (
        df[stripped_col] if stripped_col
        else df[modified_col].str.replace_all(mods.ANNOTATION_PATTERN, "")
    )
    masses = mods.derive_masses(df[modified_col], stripped, df[charge_col], df[mz_col], names)
    if masses:
        return masses, None

    conflicts = mods.mass_conflicts(df[modified_col], df[charge_col], df[mz_col])
    if conflicts:
        return {}, (
            f"Modification masses could not be resolved: {conflicts:,} precursors "
            "appear at more than one mass under the same modified sequence, which "
            "means the library holds several label channels under one set of "
            "annotation names."
        )
    return {}, "Modification masses could not be resolved from the precursor m/z."


def _determine_carbamidomethylated(df: pl.DataFrame) -> Optional[bool]:
    return _mod_report(df).carbamidomethylated


def _determine_mods(df: pl.DataFrame) -> List[str]:
    return _mod_report(df).ptms


def _determine_tags(df: pl.DataFrame) -> List[str]:
    return _mod_report(df).tags


def _find_missing_columns(df: pl.DataFrame) -> list[str]:
    missing = []

    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical in OPTIONAL_COLUMNS:
            continue
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
    

# The content hash and the mod table are built by the server, for the file
# actually saved -- the form supplies neither. Each is kept per version of a
# file, meaning the same path, size and modification time, so the work Auto-fill
# did is reused at Save, while a file rewritten in between, or a different path
# typed in after Auto-fill, is read afresh rather than inheriting another
# file's answers.


def _file_identity(path: str) -> Optional[tuple]:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns)


class _PerFile:
    """A small, thread-safe store of one answer per version of a file. FastAPI
    runs these endpoints on a thread pool, so two Auto-fills can arrive at once."""

    def __init__(self, keep: int = 32):
        self._items: "OrderedDict[tuple, object]" = OrderedDict()
        self._lock = threading.Lock()
        self._keep = keep

    def get_or_make(self, identity: tuple, make):
        with self._lock:
            if identity in self._items:
                self._items.move_to_end(identity)
                return self._items[identity]
            value = self._items[identity] = make()
            while len(self._items) > self._keep:
                self._items.popitem(last=False)
            return value

    def put(self, identity: tuple, value) -> None:
        self.get_or_make(identity, lambda: value)


_ANALYSES = _PerFile()
_HASHES = _PerFile()

# Hashing reads every byte of the file. SHA-256 already runs at the fastest
# the standard library offers here (0.73 GB/s; SHA-1 ties, MD5, BLAKE2b and
# SHA-512 are slower), and over the PTI share the network is the real limit, so
# the way to make it cheap is to start it early: Auto-fill sets it going in the
# background, it runs while the form is filled in, and Save usually just
# collects the answer. Two workers, so a second Auto-fill is not stuck behind
# the first one's hash.
_BACKGROUND = ThreadPoolExecutor(max_workers=4, thread_name_prefix="file-facts")


def _start_hash(path: str) -> Optional[Future]:
    """The hash of the file at *path*, under way. None if there is no file."""
    identity = _file_identity(path)
    if identity is None:
        return None
    return _HASHES.get_or_make(identity, lambda: _BACKGROUND.submit(_hash_file, path))


# The library details -- fragments, charges, digest -- are read from fragment
# rows, which the rest of the analysis never sees. Like the hash they are
# started at Auto-fill and collected at Save, so neither one waits for them.
_STATS = _PerFile()


def _build_library_stats(path: str) -> Optional[dict]:
    lf = _scan_library(path)
    available = lf.collect_schema().names()
    pick = lambda canonical: next((a for a in COLUMN_ALIASES[canonical] if a in available), None)  # noqa: E731
    modified, charge = pick("Modified.Sequence"), pick("Precursor.Charge")
    if modified is None or charge is None:
        return None
    decoy = next((c for c in DECOY_COLUMNS if c in available), None)
    stats, peptides = library_stats.compute(
        lf, available, modified, charge, pick("Stripped.Sequence"), pick("Precursor.Mz"),
        _is_decoy(pl.col(decoy)) if decoy else None, mods.ANNOTATION_PATTERN,
    )
    protease = _protease_of(peptides)
    stats["digest"] = (
        library_stats.digest(peptides, protease, PROTEASES[protease]["residues"], PROTEASES[protease]["side"])
        if protease else None
    )
    return stats


def _start_stats(path: str) -> Optional[Future]:
    identity = _file_identity(path)
    if identity is None:
        return None

    def build():
        try:
            return _build_library_stats(path)
        except Exception:
            return None  # an odd file should not stop the library being saved

    return _STATS.get_or_make(identity, lambda: _BACKGROUND.submit(build))


def _result(job: Optional[Future]) -> Optional[str]:
    if job is None:
        return None
    try:
        return job.result()
    except Exception:
        return None


class FileAnalysis(NamedTuple):
    """What Save keeps from parsing the library: everything read off the parsed
    rows, so one parse serves them all."""
    mod_details: list
    precursors: Optional[int]
    proteins: Optional[int]


def _analyse(df: pl.DataFrame, report: ModReport) -> FileAnalysis:
    return FileAnalysis(report.details, _determine_precursors(df), _determine_proteins(df))


def _remember_analysis(path: str, analysis: FileAnalysis) -> None:
    identity = _file_identity(path)
    if identity is not None:
        _ANALYSES.put(identity, analysis)


def _build_analysis(path: str) -> Optional[FileAnalysis]:
    try:
        df = _read_library_df(path)
        return _analyse(df, _mod_report(df))
    except Exception:
        return None


def _analysis_for(path: str) -> Optional[FileAnalysis]:
    """The analysis of the file at *path* as it is now: the one Auto-fill made
    if the file has not changed since, otherwise a fresh one. None when the
    file cannot be read -- a library on a share that is not mounted is still
    saved, it just has no table or counts until it is reachable."""
    identity = _file_identity(path)
    if identity is None:
        return None
    return _ANALYSES.get_or_make(identity, lambda: _build_analysis(path))


def _file_facts(path: str) -> dict:
    """The library's fields that come from the file at *path*: its hash, mod
    table, counts and stats. Whatever was not worked out in advance runs at
    once: the hash and the stats in the background while the parse happens
    here, so it takes as long as the slowest, not their sum."""
    hash_job, stats_job = _start_hash(path), _start_stats(path)
    analysis = _analysis_for(path)
    return {
        "content_hash": _result(hash_job),
        "mod_details": analysis.mod_details if analysis else None,
        "precursors": analysis.precursors if analysis else None,
        "proteins": analysis.proteins if analysis else None,
        "library_stats": _result(stats_job),
    }


def _clean_path(value: str) -> str:
    """A pasted path without the whitespace and quotes Windows' "Copy as path" adds."""
    path = value.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
        path = path[1:-1].strip()
    return path


@router.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze_library(payload: schemas.AnalyzeRequest):
    path = _clean_path(payload.path)

    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="File not found at that path")

    # Not waited for: these are Save's to collect, and by then they are done.
    _start_hash(path)
    _start_stats(path)

    try:
        df = _read_library_df(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    # One pass over the modifications, read three ways; it is the expensive
    # part of the analysis, so it is not repeated per field.
    report = _mod_report(df)
    analysis = _analyse(df, report)
    _remember_analysis(path, analysis)

    notes = []
    missing = _find_missing_columns(df)
    if missing:
        notes.append(
            "Missing expected columns, some fields could not be detected: "
            + ", ".join(sorted(missing))
        )
    if report.note:
        notes.append(report.note)

    # The creation log: the one given, or else one where its software leaves it
    given = _clean_path(payload.creation_log_path) if payload.creation_log_path else ""
    log, log_note = _read_log(given or creation_log.find(path), given=bool(given))
    if log_note:
        notes.append(log_note)

    return schemas.AnalyzeResponse(
        precursors=analysis.precursors,
        proteins=analysis.proteins,
        protease=_determine_protease(df),
        carbamidomethylated=report.carbamidomethylated,
        ptms=report.ptms,
        tags=report.tags,
        mod_details=[schemas.ModDetail(**detail) for detail in report.details],
        **log,
        warning=" ".join(notes) if notes else None,
    )


@router.post("/analyze-log", response_model=schemas.LogResponse)
def analyze_log(payload: schemas.LogRequest):
    """Auto-fill from the creation log alone, without reading the library."""
    log, note = _read_log(_clean_path(payload.path), given=True)
    return schemas.LogResponse(**log, warning=note)


def _read_log(path: Optional[str], given: bool) -> Tuple[dict, Optional[str]]:
    """The LogResponse fields for the log at *path*, and a note when a log the
    user *given* could not be used. One looked for and not found is no news."""
    if not path:
        return {}, None
    if not os.path.isfile(path):
        return {"creation_log_path": path}, "No creation log was found at that path."
    log = creation_log.read(path)
    if log is None:
        return ({"creation_log_path": path}, creation_log.UNRECOGNISED) if given else ({}, None)
    return {
        "creation_log_path": log.path,
        "search_algorithm": log.software,
        "software_version": log.version,
        "date_generated": log.generated,
        "fasta_path": "; ".join(log.fasta) or None,
        "source_runs": log.runs,
        "mbr": log.mbr,
    }, None

@router.post("/hash-file")
def hash_file(payload: schemas.AnalyzeRequest):  # reusing AnalyzeRequest since it's just {path: str}
    path = _clean_path(payload.path)

    if not os.path.exists(path):
        return {"error": "File not found at that path"}

    file_hash = _result(_start_hash(path))
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

    precursors = (lib.library_stats or {}).get("precursors") or {}
    if precursors:
        data.ion_mobility = precursors.get("ion_mobility") is not None
        data.decoys = precursors.get("decoys")

    return data

# IMPORTANT: this must be declared before the /{library_id} route below,
# or FastAPI will try to parse "options" as an integer library_id and fail.
@router.get("/options")
def get_field_options(db: Session = Depends(get_db)):
    simple_fields = [
        "creator", "instrument", "acquisition_type", "species",
        "project", "finetuning", "search_algorithm", "software_version", "protease",
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
    data.update(_file_facts(data["path"]))
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
    if "path" in update_data:  # a different file: its hash, table and counts are its own
        for field, value in _file_facts(library.path).items():
            setattr(library, field, value)
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