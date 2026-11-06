import hashlib
import os
import re
import socket
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime
from typing import List, NamedTuple, Optional, Tuple

import polars as pl
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import creation_log, library_stats, models, mods, schemas, share, speclib
from ..database import get_db

router = APIRouter(prefix="/libraries", tags=["libraries"])

# Page size for GET /libraries/. The old default of 100 was applied silently,
# so a catalog of 101 libraries looked exactly like a catalog of 100.
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 2000

# The spellings the formats in use here write, taken from JMod's own table --
# it reads DIA-NN, JMod, Spectronaut and FragPipe libraries, so it is the
# list that has actually met them. The first alias present wins (_get_column),
# so the dotted DIA-NN names lead and the rest follow.
COLUMN_ALIASES = {
    "Modified.Sequence": [
        "Modified.Sequence",
        "ModifiedPeptide",
        "ModifiedSequence",
        "ModifiedPeptideSequence",   # FragPipe / EasyPQP
    ],
    "Stripped.Sequence": [
        "Stripped.Sequence",
        "StrippedPeptide",
        "PeptideSequence",
    ],
    "Protein.Group": [
        "Protein.Group",
        "ProteinGroup",
        "ProteinId",                 # FragPipe, which does not separate the two
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

# What makes a precursor: a modified peptide at a charge. A file with neither
# describes something else, whatever its other columns say.
REQUIRED_PRECURSOR = ("Modified.Sequence", "Precursor.Charge")

# ...and what makes a library *spectral*: for each precursor, the fragments it
# produces and how strongly. Every name library_stats knows how to read, plus
# the intensity spellings, which it does not read yet but which are just as
# good evidence that a file holds fragment rows.
FRAGMENT_COLUMNS = [
    *(name for names in library_stats.FRAGMENT_ALIASES.values() for name in names),
    *library_stats.INTENSITY_ALIASES,
]

# Columns only a search report has. Not the test -- the missing fragments are
# the test -- but they turn "this could not be read" into "this is a report",
# which says which file to go and find instead.
REPORT_COLUMNS = [
    "Run", "File.Name", "Q.Value", "PG.Q.Value", "Global.Q.Value",
    "Precursor.Quantity", "Precursor.Normalised", "Ms1.Area",
]


class NotALibrary(ValueError):
    """The file was read and is not a spectral library.

    Separate from a parse failure because it is a different thing to be told:
    the file is fine, it is just not the kind of file this catalog is for.
    """


def _refuse_if_not_a_library(available: List[str]) -> None:
    """Whether these columns belong to a spectral library.

    A DIA-NN report is the case that matters. It describes the same
    precursors a library does, so it carries every precursor column a library
    carries -- and was accepted silently, with no warning and plausible
    counts. What it does not have is fragments, because it records what was
    found in a run rather than what to look for.
    """
    missing = [
        canonical for canonical in REQUIRED_PRECURSOR
        if not any(alias in available for alias in COLUMN_ALIASES[canonical])
    ]
    if missing:
        raise NotALibrary(
            "This file has no precursors: no " + " or ".join(missing) + " column."
        )

    if not any(name in available for name in FRAGMENT_COLUMNS):
        raise NotALibrary(
            "This looks like a search report, not a spectral library: it has "
            "precursors but no fragment ions."
            if any(name in available for name in REPORT_COLUMNS) else
            "This file has no fragment ions, so it is not a spectral library."
        )


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
    if speclib.is_speclib(path):
        # DIA-NN's own format, read through the .parquet copy DIA-NN makes of
        # it -- made here on first reading, so this can take minutes. Raises
        # speclib.Unreadable, saying why, when there is no copy and none can
        # be made.
        return pl.scan_parquet(speclib.readable_copy(path))
    raise ValueError(f"Unsupported file extension: {ext}")


def _read_library_df(path: str) -> pl.DataFrame:
    lf = _scan_library(path)

    # collect_schema() reads only the header -- no data is loaded yet, so a
    # file that is not a library is turned away before any of it is read.
    available = lf.collect_schema().names()
    _refuse_if_not_a_library(available)

    needed = []
    for aliases in COLUMN_ALIASES.values():
        needed.extend(a for a in aliases if a in available)

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
    lf = lf.select(needed)

    # FragPipe and Spectronaut wrap the sequence in underscores as terminus
    # markers: _[527.18773]PEPTIDEK. An N-terminal label is recognised by
    # sitting at the very start, so behind the _ it sat after nothing and was
    # silently dropped -- every one, in a library where all 64,510 sequences
    # are written that way. Only the outer ones go: mod names can contain
    # underscores of their own, K(H_DM_mod), and stripping those would rename
    # the mod and lose its identification.
    modified = next(a for a in COLUMN_ALIASES["Modified.Sequence"] if a in available)
    lf = lf.with_columns(pl.col(modified).str.strip_chars("_"))

    return lf.unique(maintain_order=True).collect(engine="streaming")


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
    identity = (os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns)
    if speclib.is_speclib(path):
        # A .speclib is read through its copy, so the copy appearing -- made
        # by the Linux server, read from a PC with no DIA-NN -- is a new
        # reading, not the remembered "DIA-NN is not set up"
        identity += (speclib.existing_copy(path),)
    return identity


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
    # Why there is nothing above, when there is nothing above. Kept so that
    # Save can say what Auto-fill would have said, rather than falling back on
    # "could not be read" when the file is a report and we know it.
    problem: Optional[str] = None


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
    except (NotALibrary, speclib.Unreadable) as not_one:
        return FileAnalysis(None, None, None, problem=str(not_one))
    except Exception:
        return FileAnalysis(None, None, None, problem=None)


def _analysis_for(path: str) -> Optional[FileAnalysis]:
    """The analysis of the file at *path* as it is now: the one Auto-fill made
    if the file has not changed since, otherwise a fresh one. None when the
    file cannot be read -- a library on a share that is not mounted is still
    saved, it just has no table or counts until it is reachable."""
    identity = _file_identity(path)
    if identity is None:
        return None
    return _ANALYSES.get_or_make(identity, lambda: _build_analysis(path))


def _convert_first(path: str) -> Optional[str]:
    """For a .speclib, its .parquet copy, made now if need be; None for any
    other file, or when no copy can be made (the parse then says why).

    Before anything else is started, because the copy is part of the file's
    identity (_file_identity): the hash, stats and parse started with and
    without it would be filed under two versions of the file."""
    if not speclib.is_speclib(path):
        return None
    try:
        return speclib.readable_copy(path)
    except speclib.Unreadable:
        return None


def _file_facts(path: str) -> dict:
    """The library's fields that come from the file at *path*: its hash, mod
    table, counts and stats. Whatever was not worked out in advance runs at
    once: the hash and the stats in the background while the parse happens
    here, so it takes as long as the slowest, not their sum."""
    copy = _convert_first(path)
    hash_job, stats_job = _start_hash(path), _start_stats(path)
    analysis = _analysis_for(path)
    return {
        "content_hash": _result(hash_job),
        "mod_details": analysis.mod_details if analysis else None,
        "precursors": analysis.precursors if analysis else None,
        "proteins": analysis.proteins if analysis else None,
        "library_stats": _result(stats_job),
        "readable_copy_path": _store_or_keep(copy) if copy else None,
        "readable_copy_hash": _result(_start_hash(copy)) if copy else None,
    }


# What a library's file says about it, as opposed to what people typed.
READ_FROM_FILE = (
    "mod_details", "precursors", "proteins", "library_stats",
    "readable_copy_path", "readable_copy_hash",
)


def _read_again(library: models.Library, given: Optional[str] = None) -> None:
    """Work out what the file says again, for an entry coming back.

    The counts, mod table and library details are read from the file when a
    library is catalogued and stored with it. Restoring used to bring back
    exactly what was stored -- so a library catalogued before an improvement
    to the reading (the N-terminal labels behind FragPipe's underscores) came
    back without it, however many times it was deleted and added again.

    The path just given is tried first, then the entry's own. Only a file
    with the same bytes counts: a path to some other file is not this
    library's to describe. And a file that cannot be read changes nothing --
    an unreachable share is no reason to throw away a reading that was good.
    """
    for stored in ([given] if given else []) + [row.path for row in library.paths]:
        local = share.resolve(stored)
        if not os.path.exists(local):
            continue
        facts = _file_facts(local)
        if facts["content_hash"] != library.content_hash or facts["precursors"] is None:
            continue
        for field in READ_FROM_FILE:
            if facts[field] is not None:
                setattr(library, field, facts[field])
        return


def _clean_path(value: str) -> str:
    """A pasted path without the whitespace and quotes Windows' "Copy as path" adds."""
    path = value.strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in ('"', "'"):
        path = path[1:-1].strip()
    return path


# Paths the catalog stores are share-relative, so that the same library added
# from Windows, a Mac and a Linux box is one entry rather than three. Paths
# arriving in a request are whatever the person pasted, and are translated on
# the way in; see app/share.py.


def _store_path(value: Optional[str], field: str) -> Optional[str]:
    """The form a path is stored in, or a 400 saying why it cannot be.

    Refusing a library off the share is the point rather than an inconvenience:
    a catalog entry only its author can open claims the library is available to
    everyone when it is not.
    """
    if value is None:
        return None
    cleaned = _clean_path(value)
    if not cleaned:
        return None
    if not share.configured():
        return cleaned
    canonical = share.to_canonical(cleaned)
    if canonical is not None:
        return canonical
    if not share.CONFIG.require_on_share:
        return cleaned
    raise HTTPException(
        status_code=400,
        detail=(
            f"{field} is not on the lab share, so nobody else could open it. "
            f"Paths should start with one of: {share.describe_mounts()}. Got: {cleaned}"
        ),
    )


def _local_path(value: str, field: str = "path") -> str:
    """This server's path for one a request gave us, refused if off the share.

    Checked here rather than only at Save, for two reasons. The useful one:
    somebody who points Auto-fill at a library on their own desktop finds out
    at the first click, instead of filling in the whole form and being turned
    away at the end. The other: these endpoints open whatever path they are
    given, so without the check they read any file the service account can
    reach, and answer whether any path exists -- to anyone who can reach the
    server, which is the whole network.
    """
    local = _store_path(value, field)
    if local is None:
        raise HTTPException(status_code=400, detail="No path given")
    return share.resolve(local)


# Which flavour of path to show someone back, from the browser that asked.
# Getting this wrong is cosmetic -- the path still identifies the same file --
# so an unfamiliar browser gets the server's own spelling rather than an error.
_PLATFORMS = [("windows", share.WINDOWS), ("mac os", share.MAC), ("macintosh", share.MAC),
              ("linux", share.LINUX), ("x11", share.LINUX)]


def _viewer_os(user_agent: Optional[str]) -> str:
    agent = (user_agent or "").lower()
    return next((flavour for token, flavour in _PLATFORMS if token in agent), share.WINDOWS)


# The paths the catalog owns. source_runs are deliberately not here: they name
# raw files that may sit on an instrument's own storage, or have since been
# deleted, and refusing a library because its runs moved would help nobody.
# They are stored the same way where they can be (_store_runs), just never
# refused.
PATH_FIELDS = ("path", "creation_log_path", "fasta_path")


def _store_runs(runs: Optional[List[str]]) -> Optional[List[str]]:
    """The runs a library was built from, in the form the catalog keeps.

    A run on the share is stored share-relative, like every other path, so
    that it can be shown to each machine the way that machine writes it -- a
    run saved from Windows used to reach a Mac as \\\\PTI\\Lab\\..., which it
    cannot paste. A run anywhere else is kept exactly as written: it is a
    record of where the data came from, not a file the catalog has to open.

    The same run typed two ways -- L:\\ and \\\\PTI\\Lab\\ -- is one run.
    """
    if runs is None:
        return None
    kept = []
    for run in runs:
        cleaned = _clean_path(run or "")
        if cleaned:
            kept.append(share.to_canonical(cleaned) or cleaned)
    return list(dict.fromkeys(kept)) or None


def _store_paths(values: dict) -> None:
    """Every path in a save, an edit or a restore, put in stored form.

    One place, so the three cannot drift: the runs were left out of all three
    before, which is how a Windows spelling ended up stored for everybody.
    """
    for field in PATH_FIELDS:
        if field in values:
            values[field] = _store_path(values[field], field)
    if "source_runs" in values:
        values["source_runs"] = _store_runs(values["source_runs"])


# Everything a person types about a library, which is everything worth keeping
# a history of. Read off LibraryUpdate rather than listed again, so a field
# added there is versioned without anyone remembering to come here. `path` is
# left out: where the library is lives in `paths` below, as a list.
VERSIONED_FIELDS = tuple(
    name for name in schemas.LibraryUpdate.model_fields if name != "path"
)

# What a history row says happened. The snapshot is the same shape either way;
# this is what lets the timeline read as sentences rather than as diffs.
EVENTS = (
    "catalogued", "edited", "deleted", "restored",
    "path added", "path removed", "file changed",
)

# A name is whatever the browser claimed, so it is trimmed and capped rather
# than trusted. Nobody is kept out by it -- it only has to be readable.
MAX_NAME = 60


def _who(changed_by: Optional[str]) -> Optional[str]:
    """Who the browser says is doing this, or None if it did not say."""
    cleaned = (changed_by or "").strip()[:MAX_NAME]
    return cleaned or None


# Which computer a change came from, by address. Looked up once per address
# and kept: machines rarely change names, and a reverse lookup that finds
# nothing can take seconds on a Windows network.
_MACHINES: dict = {}
_PENDING: dict = {}  # address -> the lookup under way for it
_LOOKUPS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="machine-name")
_LOOKUP_WAIT = 0.5  # seconds a change waits for a name before settling for the address


def _machine_name(address: Optional[str]) -> Optional[str]:
    """The network name of the computer at *address*, or the address itself.

    A lookup that is slow does not hold the change up: the address is
    recorded this time, and the name is there for the next change once the
    lookup finishes. One lookup per address at a time, and only the change
    that starts it waits -- a reverse lookup that finds nothing took 2.7 s
    here, and every change in that window used to start another and wait too.
    """
    if not address:
        return None
    if address in _MACHINES:
        return _MACHINES[address]
    if address in _PENDING:
        return address  # being looked up already; not worth waiting twice

    def settle(done: Future) -> None:
        try:
            _MACHINES[address] = done.result()[0]
        except Exception:
            _MACHINES[address] = address  # no name to be had; stop asking
        _PENDING.pop(address, None)

    lookup = _LOOKUPS.submit(socket.gethostbyaddr, address)
    _PENDING[address] = lookup
    lookup.add_done_callback(settle)
    try:
        return lookup.result(timeout=_LOOKUP_WAIT)[0]
    except Exception:
        return address


def _changed_from(request: Request) -> Optional[str]:
    """The machine a request came from, for the history.

    The browser making the request, so on a remote desktop it is the remote
    desktop, which is the machine that matters: one shared Windows account
    there means one remembered name for everyone who sits down at it.
    """
    return _machine_name(request.client.host if request.client else None)


def _require_who(changed_by: Optional[str]) -> str:
    """The same, for a change that will not go ahead without one.

    Changing an entry that already exists alters or removes somebody else's
    work, and the old values survive only in the history -- which is worth
    little if half of it says "someone". Cataloguing a new library is the
    exception: nothing is being overwritten, and `creator` already names a
    person.

    Not a login, and not pretending to be: it refuses a request that says
    nothing, not one that says something untrue.
    """
    who = _who(changed_by)
    if who is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This change is recorded against a name. Send an "
                "X-SpecVault-User header saying who you are."
            ),
        )
    return who


def _jsonable(value):
    """Dates do not survive JSON on their own."""
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _snapshot(library: models.Library) -> dict:
    data = {field: _jsonable(getattr(library, field)) for field in VERSIONED_FIELDS}
    data["paths"] = [row.path for row in library.paths]
    return data


def _displayed_snapshot(data: dict, flavour: str) -> dict:
    """A snapshot with its paths written for the machine asking."""
    shown = dict(data)
    if isinstance(shown.get("paths"), list):
        shown["paths"] = [share.to_display(p, flavour) for p in shown["paths"]]
    if isinstance(shown.get("source_runs"), list):
        shown["source_runs"] = [_display(run, flavour) for run in shown["source_runs"]]
    for field in ("creation_log_path", "fasta_path"):
        if shown.get(field):
            shown[field] = _display(shown[field], flavour)
    return shown


def _record(db: Session, library: models.Library, event: str, changed_by: Optional[str],
            changed_from: Optional[str] = None) -> None:
    """Note what the library looks like now, and who left it that way.

    Called after the change has been applied to *library* and before the
    commit, so the snapshot and the row it describes land together or not at
    all.
    """
    db.add(models.LibraryVersion(
        library_id=library.id,
        event=event,
        changed_by=_who(changed_by),
        changed_from=changed_from,
        data=_snapshot(library),
    ))


def _live(db: Session):
    """The catalog: every library that has not been deleted.

    Deleting only sets `deleted_at`, so every query that answers "what is in
    SpecVault" starts here. The two that deliberately do not are the duplicate
    checks below -- a deleted entry still owns its hash and its paths, and
    saying so is what lets it be offered back.
    """
    return db.query(models.Library).filter(models.Library.deleted_at.is_(None))


def _deleted_on(library: models.Library) -> Optional[str]:
    """The day an entry was deleted, for saying so to a person."""
    return library.deleted_at.strftime("%d %b %Y") if library.deleted_at else None


def _catalogued_as(
    db: Session, content_hash: Optional[str], path: str, flavour: str,
) -> Optional[schemas.DuplicateLibrary]:
    """The entry that already holds this file's bytes, if there is one.

    The hash is stored so that "do we already have this?" has an answer; two
    entries for one file is the question going unasked. What comes back names
    the entry it matched, so the caller can offer to add this path to it --
    a library copied to a second folder is one library in two places.

    A deleted entry matches too, and is the more useful answer: somebody who
    deletes a library and adds the file again means to undo it. Saying nothing
    would leave them pointed at an entry they cannot see.
    """
    if not content_hash:
        return None  # unreadable file: no hash is not the same as a matching one
    # The .parquet copy of a catalogued .speclib is that library too, in the
    # only form SpecVault can read -- not a second library to catalogue.
    matches = (
        db.query(models.Library)
        .filter(or_(
            models.Library.content_hash == content_hash,
            models.Library.readable_copy_hash == content_hash,
        ))
        .order_by(models.Library.id)
        .all()
    )
    if not matches:
        return None
    # A live entry is what the file belongs to; a deleted one only matters when
    # there is no live one.
    existing = next((row for row in matches if row.deleted_at is None), matches[0])
    deleted_on = _deleted_on(existing)
    is_copy = existing.content_hash != content_hash
    if is_copy:
        message = (
            "This is the .parquet copy SpecVault made of a .speclib that is "
            + (f"in SpecVault, deleted on {deleted_on}." if deleted_on else "already in SpecVault.")
        )
    elif deleted_on:
        message = f"This library was deleted from SpecVault on {deleted_on}."
    else:
        message = "Library already exists in SpecVault."
    return schemas.DuplicateLibrary(
        message=message,
        library_id=existing.id,
        paths=[share.to_display(row.path, flavour) for row in existing.paths],
        # A copy is never another of the entry's paths: those are all the same
        # bytes, and these are not. Recorded already, as its readable copy.
        already_recorded=is_copy or any(row.path == path for row in existing.paths),
        deleted=deleted_on is not None,
    )


def _refuse_without_a_hash(local: str, facts: dict, shown: str) -> None:
    """No hash, no entry. Not a thing to confirm past.

    The hash is the library's identity: it is how the same file is recognised
    when it turns up again somewhere else, how a duplicate is matched, how a
    deleted entry is offered back, and what a check that a library has not
    been altered compares against. An entry without one can do none of that
    and never will -- nothing re-reads a file once it is catalogued -- so it
    is a row that looks like a library and is not one.
    """
    if facts.get("content_hash") is not None:
        return
    missing_file = not os.path.exists(local)
    raise HTTPException(status_code=400, detail=(
        (f"There is no file at {shown}." if missing_file
         else f"{shown} could not be read.")
        + " A library has to be readable to be catalogued: its hash is how"
          " SpecVault recognises the file again, and an entry without one"
          " cannot be matched, checked, or told apart from any other."
    ))


def _unparsed(local: str, facts: dict, shown: str) -> Optional[schemas.UnreadableLibrary]:
    """A file that is there and hashed, but that could not be read as a
    library -- because it is in a format SpecVault does not know, or because
    it is not a library at all.

    Still worth offering to catalogue: it is a real file with an identity, and
    the person pointing at it may know something the parser does not. What it
    costs is everything the library itself would have said, so that is said
    first -- along with *why*, where the reason is known.
    """
    if facts.get("precursors") is not None:
        return None
    # Cached from the parse that _file_facts just did, so this costs nothing
    analysis = _analysis_for(local)
    reason = analysis.problem if analysis else None
    return schemas.UnreadableLibrary(
        message=reason or f"{shown} could not be read as a spectral library.",
        path=shown,
        missing=[
            "precursor and protein counts",
            "the modification table",
            "the library details: charges, fragments, digest",
        ],
    )


def _refuse_if_catalogued(db: Session, content_hash: Optional[str], path: str, flavour: str) -> None:
    """The same question, asked where the answer stops a save going through."""
    found = _catalogued_as(db, content_hash, path, flavour)
    if found is not None:
        raise HTTPException(status_code=409, detail=found.model_dump())


def _refuse_if_path_taken(db: Session, path: str, flavour: str) -> None:
    """A path names one file, so it belongs to one entry.

    The unique constraint says the same thing, but an IntegrityError cannot say
    *which* library already has it, and that is the useful half. A deleted
    entry keeps its paths, so it is named here as well -- otherwise the refusal
    points at a library the catalog will not show.
    """
    owner = (
        db.query(models.Library)
        .join(models.LibraryPath)
        .filter(models.LibraryPath.path == path)
        .first()
    )
    if owner is not None:
        deleted_on = _deleted_on(owner)
        raise HTTPException(
            status_code=409,
            detail=(
                f"{share.to_display(path, flavour)} is recorded as library "
                f"#{owner.id}, which was deleted on {deleted_on}."
                if deleted_on else
                f"{share.to_display(path, flavour)} is already recorded as library "
                f"#{owner.id}."
            ),
        )


def _display(stored: Optional[str], flavour: str) -> Optional[str]:
    """A stored path written for *flavour*. Several FASTAs are one field joined
    by "; ", so each part is rendered rather than the string as a whole.

    A part that is not share-relative is not on the share -- a run on an
    instrument's own disk, kept as written -- and is shown as it is. Rendering
    it would hang the share's prefix in front of a drive letter."""
    if not stored or not share.configured():
        return stored
    return "; ".join(
        part if share.is_absolute(part) else share.to_display(part, flavour)
        for part in stored.split("; ") if part
    )


def _log_for_viewer(log: dict, flavour: str) -> dict:
    """The paths a log yielded, written for the machine that asked.

    A log records paths as the machine that ran the software saw them, and
    creation_log.read() has already translated those onto this server. Left
    there, Auto-fill would drop the server's own spelling into a Mac user's
    form -- correct, and not what they would have typed.
    """
    if not share.configured():
        return log
    rendered = dict(log)
    for field in ("creation_log_path", "fasta_path"):
        if rendered.get(field):
            rendered[field] = _display(_store_or_keep(rendered[field]), flavour)
    if rendered.get("source_runs"):
        rendered["source_runs"] = [
            _display(_store_or_keep(run), flavour) for run in rendered["source_runs"]
        ]
    return rendered


def _store_or_keep(path: str) -> str:
    """The share-relative form where there is one, otherwise the path itself.
    Used for paths that are reported rather than stored, which may legitimately
    point off the share."""
    return "; ".join(
        share.to_canonical(part) or part for part in path.split("; ") if part
    )


@router.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze_library(
    payload: schemas.AnalyzeRequest,
    user_agent: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    # Pasted from whichever machine the person is on, so translated to this
    # server's view of the share before anything is opened -- and refused here
    # if it is not on the share, rather than after the form has been filled in.
    path = _local_path(payload.path)

    if not os.path.exists(path):
        raise HTTPException(status_code=400, detail="File not found at that path")

    # A .speclib's copy first: everything below reads it, and is filed under it
    if speclib.is_speclib(path):
        try:
            speclib.readable_copy(path)
        except speclib.Unreadable as unreadable:
            raise HTTPException(status_code=400, detail=str(unreadable))

    # Not waited for: these are Save's to collect, and by then they are done.
    _start_hash(path)
    _start_stats(path)

    try:
        df = _read_library_df(path)
    except (NotALibrary, speclib.Unreadable) as not_one:
        # Says what is wrong with the file, not that reading it went wrong
        raise HTTPException(status_code=400, detail=str(not_one))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    # One pass over the modifications, read three ways; it is the expensive
    # part of the analysis, so it is not repeated per field.
    report = _mod_report(df)
    analysis = _analyse(df, report)
    _remember_analysis(path, analysis)
    if speclib.is_speclib(path):
        # The copy just read is hashed too, for finding the library by it --
        # started now, like the .speclib's own, so Save only collects it
        _start_hash(speclib.existing_copy(path) or "")

    notes = []
    missing = _find_missing_columns(df)
    if missing:
        notes.append(
            "Missing expected columns, some fields could not be detected: "
            + ", ".join(sorted(missing))
        )
    if report.note:
        notes.append(report.note)
    if speclib.is_speclib(path):
        notes.append(
            f"Read from {os.path.basename(speclib.copy_path(path))}, the .parquet copy of "
            "this .speclib that DIA-NN made next to it. It is saved with the library."
        )

    # The creation log: the one given, or else one where its software leaves it
    given = _local_path(payload.creation_log_path, "creation_log_path") if payload.creation_log_path else ""
    log, log_note = _read_log(given or creation_log.find(path), given=bool(given))
    if log_note:
        notes.append(log_note)
    log = _log_for_viewer(log, _viewer_os(user_agent))

    # Collected here rather than left for Save. The hash has had the whole
    # parse above to finish in, and knowing now that the file is already
    # catalogued saves filling in a form whose Save cannot go through.
    duplicate = _catalogued_as(
        db, _result(_start_hash(path)), _store_path(payload.path, "path"),
        _viewer_os(user_agent),
    )

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
        duplicate=duplicate,
    )


@router.post("/analyze-log", response_model=schemas.LogResponse)
def analyze_log(
    payload: schemas.LogRequest,
    user_agent: Optional[str] = Header(default=None),
):
    """Auto-fill from the creation log alone, without reading the library."""
    log, note = _read_log(_local_path(payload.path, "creation_log_path"), given=True)
    return schemas.LogResponse(**_log_for_viewer(log, _viewer_os(user_agent)), warning=note)


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
        "protein_inference": log.protein_inference,
        "vendor": creation_log.vendor(log.runs),
    }, None

@router.post("/hash-file")
def hash_file(payload: schemas.AnalyzeRequest):  # reusing AnalyzeRequest since it's just {path: str}
    path = _local_path(payload.path)

    if not os.path.exists(path):
        return {"error": "File not found at that path"}

    file_hash = _result(_start_hash(path))
    if file_hash is None:
        return {"error": "Could not read file to compute hash"}

    return {"content_hash": file_hash}

def _to_response(lib: models.Library, flavour: str = share.WINDOWS) -> schemas.LibraryResponse:
    data = schemas.LibraryResponse.model_validate(lib)
    stored = [row.path for row in lib.paths]

    # Each path is checked, not just the first: the files panel marks the ones
    # that are not there, so a copy that has been moved or deleted shows up as
    # the thing to fix rather than silently going stale.
    local = {p: share.resolve(p) for p in stored}
    present = {p: os.path.exists(local[p]) for p in stored}
    data.path_details = [
        schemas.LibraryPathInfo(
            id=row.id,
            path=row.path,
            display=_display(row.path, flavour) or row.path,
            exists=present[row.path],
        )
        for row in lib.paths
    ]

    # Found wherever it is: a library kept in two places is still reachable
    # when one of them is offline, and saying "missing" because the first copy
    # is away would send someone looking for a file that is right there.
    found = next((local[p] for p in stored if present[p]), None)
    data.path_exists = found is not None

    # Written the way the machine asking for it writes paths, so that the path
    # shown -- and the one the Copy button puts on the clipboard -- is one that
    # works when pasted into that person's own shell or file manager.
    data.display_path = _display(lib.path, flavour)
    data.display_creation_log_path = _display(lib.creation_log_path, flavour)
    data.display_fasta_path = _display(lib.fasta_path, flavour)
    data.display_source_runs = [_display(run, flavour) for run in lib.source_runs or []]
    data.display_readable_copy_path = _display(lib.readable_copy_path, flavour)

    # Who uses it, oldest star first. The page works out "starred by me" from
    # this, so the listing is the same for everybody and needs no name to read.
    data.starred_by = [row.name for row in lib.star_rows]
    data.stars = len(data.starred_by)

    _, ext = os.path.splitext(lib.path or "")
    data.file_format = ext.lstrip('.').upper() if ext else None

    if found is not None:
        try:
            data.file_size = os.path.getsize(found)
            data.updated_at = datetime.fromtimestamp(os.path.getmtime(found))
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
        "creator", "instrument", "acquisition_type", "vendor", "species",
        "project", "finetuning", "search_algorithm", "software_version", "protease",
        "in_silico",
    ]
    options = {}
    # Deleted entries are left out: these fill the dropdowns, and offering a
    # creator or a project that only a deleted library ever used spreads it
    # back through the catalog.
    live = models.Library.deleted_at.is_(None)
    for field in simple_fields:
        col = getattr(models.Library, field)
        rows = db.query(col).filter(col.isnot(None), col != "", live).distinct().all()
        options[field] = sorted({r[0] for r in rows if r[0]})

    # List-type fields store JSON arrays — flatten distinct values across all rows
    list_fields = ["cell_types", "tissues", "ptms", "tags"]
    for field in list_fields:
        col = getattr(models.Library, field)
        rows = db.query(col).filter(col.isnot(None), live).all()
        values = set()
        for (row_list,) in rows:
            if row_list:
                values.update(row_list)
        options[field] = sorted(values)

    return options


@router.post("/", response_model=schemas.LibraryResponse, status_code=201)
def create_library(
    library: schemas.LibraryCreate,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    changed_from: Optional[str] = Depends(_changed_from),
    db: Session = Depends(get_db),
):
    data = library.model_dump()
    confirmed = data.pop("save_unreadable", False)
    _store_paths(data)
    path = data.pop("path")
    local = share.resolve(path)
    data.update(_file_facts(local))

    flavour = _viewer_os(user_agent)
    shown = share.to_display(path, flavour)

    # Both before the duplicate checks: with no hash there is nothing to match
    # on, so "do we already have this?" cannot be answered either way, and why
    # not is the more useful thing to say.
    _refuse_without_a_hash(local, data, shown)
    if not confirmed:
        unparsed = _unparsed(local, data, shown)
        if unparsed is not None:
            raise HTTPException(status_code=409, detail=unparsed.model_dump())

    _refuse_if_catalogued(db, data.get("content_hash"), path, flavour)
    _refuse_if_path_taken(db, path, flavour)

    db_library = models.Library(**data, paths=[models.LibraryPath(path=path)])
    db.add(db_library)
    try:
        # flush first: the history row needs the library's id, which the
        # database only hands out when the insert actually goes.
        db.flush()
        _record(db, db_library, "catalogued", changed_by, changed_from)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A library with this path already exists")
    db.refresh(db_library)
    return _to_response(db_library, flavour)


@router.post("/{library_id}/paths", response_model=schemas.LibraryResponse)
def add_path(
    library_id: int,
    payload: schemas.AddPathRequest,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    changed_from: Optional[str] = Depends(_changed_from),
    db: Session = Depends(get_db),
):
    """Record another place this library's file is.

    What the duplicate refusal on save offers: the file is already catalogued,
    so instead of a second entry for the same bytes, the entry it matched
    learns about this copy too.
    """
    changed_by = _require_who(changed_by)
    library = _live(db).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    flavour = _viewer_os(user_agent)
    path = _store_path(payload.path, "path")
    if path is None:
        raise HTTPException(status_code=400, detail="No path given")
    if path in (row.path for row in library.paths):
        raise HTTPException(
            status_code=409,
            detail=f"This library already lists {share.to_display(path, flavour)}",
        )
    _refuse_if_path_taken(db, path, flavour)

    library.paths.append(models.LibraryPath(path=path))
    try:
        _record(db, library, "path added", changed_by, changed_from)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="That path belongs to another library")
    db.refresh(library)
    return _to_response(library, flavour)


@router.delete("/{library_id}/paths/{path_id}", response_model=schemas.LibraryResponse)
def remove_path(
    library_id: int,
    path_id: int,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    changed_from: Optional[str] = Depends(_changed_from),
    db: Session = Depends(get_db),
):
    """Stop recording one of the places this library's file is.

    For a copy that has been moved or deleted: the entry goes on claiming it
    is there, and the files panel marks it missing forever with no way to say
    "that one is gone". Nothing on the share is touched -- the path is only
    ever a record of where a file was.

    **Not** restricted to paths whose file is missing. A path pasted by
    mistake may well point at something real -- another library's file, even
    -- and that is exactly the one worth being able to take back. What the
    history is for: the snapshot either side says what was removed.

    The last path cannot go. An entry with none says nothing about where its
    library is, and is the shape that broke the listing once already.
    """
    changed_by = _require_who(changed_by)
    library = _live(db).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    doomed = next((row for row in library.paths if row.id == path_id), None)
    if doomed is None:
        raise HTTPException(status_code=404, detail="This library has no such path")
    if len(library.paths) == 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "This is the only place this library is recorded. Add another "
                "path first, or delete the library."
            ),
        )

    flavour = _viewer_os(user_agent)
    library.paths.remove(doomed)
    _record(db, library, "path removed", changed_by, changed_from)
    db.commit()
    db.refresh(library)
    return _to_response(library, flavour)


def _starrable(db: Session, library_id: int, changed_by: Optional[str]):
    """The library to star and who is starring it -- or why not.

    A star needs a name, like any change, but is not one: nothing about the
    library moves, so nothing goes in the history and nobody is asked "not
    you?". A deleted library cannot be starred; its stars are kept, and come
    back with it.
    """
    who = _require_who(changed_by)
    library = _live(db).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return library, who


# PUT and DELETE rather than one toggle, so that a double click or a request
# sent twice leaves the star where the person meant it rather than undoing it.
@router.put("/{library_id}/star", response_model=schemas.LibraryResponse)
def star_library(
    library_id: int,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    db: Session = Depends(get_db),
):
    library, who = _starrable(db, library_id, changed_by)
    if who not in (row.name for row in library.star_rows):
        library.star_rows.append(models.LibraryStar(name=who))
        db.commit()
        db.refresh(library)
    return _to_response(library, _viewer_os(user_agent))


@router.delete("/{library_id}/star", response_model=schemas.LibraryResponse)
def unstar_library(
    library_id: int,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    db: Session = Depends(get_db),
):
    library, who = _starrable(db, library_id, changed_by)
    mine = next((row for row in library.star_rows if row.name == who), None)
    if mine is not None:
        library.star_rows.remove(mine)
        db.commit()
        db.refresh(library)
    return _to_response(library, _viewer_os(user_agent))


@router.patch("/{library_id}", response_model=schemas.LibraryResponse)
def update_library(
    library_id: int,
    updates: schemas.LibraryUpdate,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    changed_from: Optional[str] = Depends(_changed_from),
    db: Session = Depends(get_db),
):
    changed_by = _require_who(changed_by)
    library = _live(db).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    before = _snapshot(library)
    update_data = updates.model_dump(exclude_unset=True)
    _store_paths(update_data)

    # path is where the library was catalogued -- the first of its paths, and
    # the copy whose file is read. Setting it moves that one; any other places
    # the library is recorded stay as they are, and are added or removed
    # through /{id}/paths rather than here.
    new_path = update_data.pop("path", None)
    for field, value in update_data.items():
        setattr(library, field, value)

    changed_file = False
    if new_path is not None and new_path != library.path:
        _refuse_if_path_taken(db, new_path, _viewer_os(user_agent))
        if library.paths:
            library.paths[0].path = new_path
        else:
            library.paths.append(models.LibraryPath(path=new_path))
        # a different file: its hash, table and counts are its own
        facts = _file_facts(share.resolve(new_path))
        # Worth telling apart in the history: correcting a path is housekeeping,
        # while the entry now describing different bytes means every count and
        # every reading of it below that point was about another file.
        changed_file = facts.get("content_hash") != library.content_hash
        for field, value in facts.items():
            setattr(library, field, value)

    # A PATCH that sets everything to what it already was is not a change, and
    # a history full of empty edits is a history nobody reads.
    if changed_file or _snapshot(library) != before:
        _record(db, library, "file changed" if changed_file else "edited", changed_by, changed_from)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A library with this path already exists")
    db.refresh(library)
    return _to_response(library, _viewer_os(user_agent))

@router.get("/", response_model=List[schemas.LibraryResponse])
def list_libraries(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user_agent: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    # X-Total-Count lets the client tell a complete result from a truncated page.
    # Without it a client that asked for one page rendered it as the whole
    # catalog. Exposed to the browser via expose_headers in main.py.
    total = (
        db.query(func.count(models.Library.id))
        .filter(models.Library.deleted_at.is_(None))
        .scalar()
    )
    response.headers["X-Total-Count"] = str(total)

    rows = (
        _live(db)
        .order_by(models.Library.id)  # stable order, or paging repeats/skips rows
        .offset(skip)
        .limit(limit)
        .all()
    )
    flavour = _viewer_os(user_agent)
    return [_to_response(row, flavour) for row in rows]

@router.get("/{library_id}", response_model=schemas.LibraryResponse)
def get_library(
    library_id: int,
    user_agent: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    library = _live(db).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    return _to_response(library, _viewer_os(user_agent))

@router.delete("/{library_id}", status_code=204)
def delete_library(
    library_id: int,
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    changed_from: Optional[str] = Depends(_changed_from),
    db: Session = Depends(get_db),
):
    """Take a library out of the catalog, reversibly.

    The row stays and stops being listed. Nothing on the share is touched --
    SpecVault only ever reads library files -- and nothing is lost: the entry
    keeps its metadata, its hash and its paths, so adding the file again finds
    it and offers it back rather than starting a second entry.

    Deleting an already-deleted library is a 404: it is not in the catalog to
    delete. The date it went is the date it first went.
    """
    changed_by = _require_who(changed_by)
    library = _live(db).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    library.deleted_at = func.now()
    _record(db, library, "deleted", changed_by, changed_from)
    db.commit()


@router.post("/{library_id}/restore", response_model=schemas.LibraryResponse)
def restore_library(
    library_id: int,
    payload: Optional[schemas.RestoreRequest] = None,
    user_agent: Optional[str] = Header(default=None),
    changed_by: Optional[str] = Header(default=None, alias="X-SpecVault-User"),
    changed_from: Optional[str] = Depends(_changed_from),
    db: Session = Depends(get_db),
):
    """Put a deleted library back in the catalog.

    With a body, it also takes what the person had just typed: somebody who
    deletes a library and adds the file again has usually filled the form in
    first, and throwing that away to bring back the metadata they were
    replacing is the wrong way round. Without one, the entry returns as it
    was.

    The path comes back either way, because it says where the file is rather
    than what the entry should claim -- the file has often moved, which is why
    it is being added again at all.

    Deliberately not filtered to deleted ones: restoring a library that is
    already there is what the caller wanted either way, and it means a second
    click cannot turn into an error.
    """
    changed_by = _require_who(changed_by)
    library = db.query(models.Library).filter(models.Library.id == library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    flavour = _viewer_os(user_agent)
    was_deleted = library.deleted_at is not None
    library.deleted_at = None

    before = _snapshot(library)
    if payload is not None and payload.details is not None:
        updates = payload.details.model_dump(exclude_unset=True)
        # Where the library is comes from `path` below, as a list; one field
        # could only ever stand for the first of them.
        updates.pop("path", None)
        _store_paths(updates)
        for field, value in updates.items():
            setattr(library, field, value)

    given = None
    if payload is not None and payload.path:
        given = _store_path(payload.path, "path")
        if given and given not in (row.path for row in library.paths):
            _refuse_if_path_taken(db, given, flavour)
            library.paths.append(models.LibraryPath(path=given))

    _read_again(library, given)

    if was_deleted or _snapshot(library) != before:
        _record(db, library, "restored" if was_deleted else "edited", changed_by, changed_from)
    db.commit()
    db.refresh(library)
    return _to_response(library, flavour)


@router.get("/{library_id}/history", response_model=List[schemas.LibraryVersion])
def get_library_history(
    library_id: int,
    user_agent: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    """Everything that has happened to this library, newest first.

    Deliberately readable for a deleted library: "when did this go, and who
    took it out" is a question worth being able to answer about an entry that
    is no longer listed.

    What changed between two snapshots is worked out by the caller, which
    knows what each field is called and how to show it. Paths are the one
    thing done here: they are stored share-relative, and a history reading
    "JMod/.../lib.parquet" shows a path nobody can open rather than the one
    they would have pasted.
    """
    if not db.query(models.Library.id).filter(models.Library.id == library_id).first():
        raise HTTPException(status_code=404, detail="Library not found")
    rows = (
        db.query(models.LibraryVersion)
        .filter(models.LibraryVersion.library_id == library_id)
        .order_by(models.LibraryVersion.id.desc())
        .all()
    )
    flavour = _viewer_os(user_agent)
    return [
        schemas.LibraryVersion(
            id=row.id,
            recorded_at=row.recorded_at,
            event=row.event,
            changed_by=row.changed_by,
            changed_from=row.changed_from,
            # A copy: the stored snapshot keeps the canonical spelling, which
            # is what makes it comparable across machines.
            data=_displayed_snapshot(row.data, flavour),
        )
        for row in rows
    ]
