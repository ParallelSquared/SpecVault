"""What a creation log says about the library it produced.

A log is treated as describing the library being added: which software built
it, which version, when, from which FASTA and which runs, and whether
match-between-runs was on. Nothing in it is matched against the library's own
path. Two formats are read:

* DIA-NN's report.log.txt, which sits beside the library it wrote.
* JMod's JMod_log.log. JMod only makes libraries by MBR, and writes them to
  mbr_library/ inside the results folder, so the log is one folder up.

Both write paths as the machine that ran them saw them -- often a mapped drive
such as L:\\ for \\\\PTI\\Lab. Each log says which folder it was written to, so
comparing that with where the log really is gives the mapping, and every path
read from the log is translated through it into one anyone can open.
"""
import ntpath
import os
import re
from datetime import date, datetime
from typing import Callable, List, NamedTuple, Optional, Tuple

DIANN = "DIA-NN"
JMOD = "JMod"
SUPPORTED = (DIANN, JMOD)
UNRECOGNISED = "Unrecognised log format. Currently supported formats: " + ", ".join(SUPPORTED) + "."

_DIANN_VERSION = re.compile(r"^DIA-NN (\S+)")
_DIANN_STARTED = re.compile(r"^Current date and time: (.+?)\s*$")
_DIANN_LOADING_RUN = re.compile(r"Loading run (.+?)\s*$")

# JMod lines are "00:21:09 - INFO - message", timed from the start of the run
_JMOD_MESSAGE = re.compile(r"^\d+:\d\d:\d\d - [A-Z]+ - ?(.*?)\s*$")
# The release only: "JMod v2.1.0-7-g857745b" is 2.1.0 plus seven commits
_JMOD_VERSION = re.compile(r"^JMod v(\d+(?:\.\d+)*)")
_JMOD_LOG_WRITTEN = re.compile(r"^Log writing to (.+)$")
_JMOD_RUN = re.compile(r"^Run \d+ of \d+$")
_JMOD_MBR_LIBRARY = re.compile(r"^MBR library written to ")

# How far into a file to look for the banner when deciding whether a file
# beside a library is a log, and which.
_BANNER_LINES = 10
# Names each software gives its log, preferred over any other log beside it
_USUAL_NAMES = {DIANN: "report.log.txt", JMOD: "jmod_log.log"}
# Raw files that only one vendor writes. An .mzML could have come from anyone.
_VENDOR_FORMATS = {".d": "Bruker", ".raw": "Thermo"}


class LogFacts(NamedTuple):
    path: str
    software: str
    version: Optional[str]
    generated: Optional[date]
    fasta: List[str]
    runs: List[str]
    mbr: bool


def read(path: str) -> Optional[LogFacts]:
    """The facts in the log at *path*, or None if it cannot be read or is in no
    format we know."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    software = _identify(lines[:_BANNER_LINES])
    if software == DIANN:
        return _read_diann(path, lines)
    if software == JMOD:
        return _read_jmod(path, lines)
    return None


def vendor(runs: List[str]) -> Optional[str]:
    """The instrument vendor, when every run is a raw file only it writes."""
    vendors = {_VENDOR_FORMATS.get(os.path.splitext(run.rstrip("\\/"))[1].lower()) for run in runs}
    return vendors.pop() if len(vendors) == 1 else None


def find(library_path: str) -> Optional[str]:
    """The creation log for the library, if one is where its software leaves
    it: a DIA-NN or JMod log in the library's own folder, or a JMod log in the
    folder above (JMod writes its library to mbr_library/)."""
    folder = os.path.dirname(library_path)
    return _find_in(folder, SUPPORTED) or _find_in(os.path.dirname(folder), (JMOD,))


def _find_in(folder: str, formats: Tuple[str, ...]) -> Optional[str]:
    """The log in *folder* written by one of *formats*: the one with its
    software's usual name by preference, otherwise the most recent."""
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    logs = []
    for name in names:
        if not name.lower().endswith((".log.txt", ".log")):
            continue
        path = os.path.join(folder, name)
        software = _identify_file(path)
        if software in formats:
            if name.lower() == _USUAL_NAMES[software]:
                return path
            logs.append(path)
    return max(logs, key=os.path.getmtime) if logs else None


def _identify_file(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return _identify([handle.readline() for _ in range(_BANNER_LINES)])
    except OSError:
        return None


def _identify(head: List[str]) -> Optional[str]:
    """Which software wrote a log, from its first few lines."""
    for line in head:
        if _DIANN_VERSION.match(line):
            return DIANN
        message = _JMOD_MESSAGE.match(line)
        if message and _JMOD_VERSION.match(message.group(1)):
            return JMOD
    return None


# ----------------------------------------------------------------------- DIA-NN

def _read_diann(path: str, lines: List[str]) -> LogFacts:
    flags = _diann_flags(lines)
    out = next((value for name, value in flags if name == "out"), None)
    mapped = _drive_mapping(path, ntpath.dirname(out) if out else None)

    runs = [mapped(m.group(1)) for m in map(_DIANN_LOADING_RUN.search, lines) if m]
    if not runs:  # nothing was searched yet when the log was written
        runs = [mapped(value) for name, value in flags if name == "f"]
    return LogFacts(
        path=path,
        software=DIANN,
        version=next(m.group(1) for m in map(_DIANN_VERSION.match, lines) if m),
        generated=_diann_started(lines),
        fasta=[mapped(value) for name, value in flags if name == "fasta" and value],
        # Each run is loaded once per pass, so with MBR it is listed twice
        runs=list(dict.fromkeys(runs)),
        mbr=any(name == "reanalyse" for name, _ in flags),
    )


def _diann_started(lines: List[str]) -> Optional[date]:
    for m in map(_DIANN_STARTED.match, lines):
        if m:
            try:
                return datetime.strptime(m.group(1), "%a %b %d %H:%M:%S %Y").date()
            except ValueError:
                return None
    return None


def _diann_flags(lines: List[str]) -> List[Tuple[str, str]]:
    """The command DIA-NN logged, as (flag, value) pairs in order. Values may
    contain spaces -- paths do -- so a flag runs until the next " --"."""
    command = next((line for line in lines
                    if " --" in line and "diann" in line.split(" --")[0].lower()), "")
    pairs = []
    for part in command.split(" --")[1:]:
        name, _, value = part.partition(" ")
        pairs.append((name.strip(), value.strip()))
    return pairs


# ------------------------------------------------------------------------- JMod

def _read_jmod(path: str, lines: List[str]) -> LogFacts:
    messages = [m.group(1) for m in map(_JMOD_MESSAGE.match, lines) if m]
    written = next((m.group(1) for m in map(_JMOD_LOG_WRITTEN.match, messages) if m), None)
    mapped = _drive_mapping(path, ntpath.dirname(written) if written else None)

    # Each "Run 1 of 2" is followed by the file it runs; with MBR every run
    # comes up once per pass.
    runs = [mapped(after) for before, after in zip(messages, messages[1:])
            if _JMOD_RUN.match(before)]
    return LogFacts(
        path=path,
        software=JMOD,
        version=next(m.group(1) for m in map(_JMOD_VERSION.match, messages) if m),
        generated=_jmod_generated(path),
        fasta=[],  # JMod searches a library, not a FASTA
        runs=list(dict.fromkeys(runs)),
        mbr=any(_JMOD_MBR_LIBRARY.match(message) for message in messages),
    )


def _jmod_generated(path: str) -> Optional[date]:
    """When the JMod run finished. Its clock times are elapsed, not dates, and
    the results folder can be named anything, so until JMod logs the date this
    is the day the log was last written -- the end of the run. Once the date is
    in the log, read it from the log here instead."""
    try:
        return date.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


# ----------------------------------------------------------------------- paths

def _drive_mapping(log_path: str, written_folder: Optional[str]) -> Callable[[str], str]:
    """A function translating paths written in the log into ones that work here.

    *written_folder* is the log's folder as the software saw it. It and the
    folder the log really is in are the same folder seen two ways; whatever they
    share at the end is the same, and the parts in front are the mapping
    (L:\\ -> \\\\PTI\\Lab\\). Without it, or with nothing in common, paths are
    left as the log wrote them, apart from JMod's forward slashes.
    """
    if not written_folder:
        return ntpath.normpath
    real = ntpath.normpath(ntpath.dirname(ntpath.abspath(log_path))).split("\\")
    written = ntpath.normpath(written_folder).split("\\")
    shared = 0
    while (shared < min(len(real), len(written))
           and real[-1 - shared].lower() == written[-1 - shared].lower()):
        shared += 1
    old = "\\".join(written[:len(written) - shared])
    new = "\\".join(real[:len(real) - shared])
    if shared == 0 or not old or old.lower() == new.lower():
        return ntpath.normpath

    def translate(path: str) -> str:
        path = ntpath.normpath(path)
        if path.lower().startswith(old.lower() + "\\"):
            return new + path[len(old):]
        return path

    return translate
