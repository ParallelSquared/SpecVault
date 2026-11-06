"""Reading DIA-NN's .speclib, by having DIA-NN rewrite it as .parquet.

A .speclib is DIA-NN's own binary format: undocumented, and changed between
versions. Nothing else reads it, so SpecVault does not try to. DIA-NN itself
will save any library it can load as .parquet -- given a library and no runs,
`--gen-spec-lib --out-lib X.parquet` loads it and writes it straight back out
-- so that is what is done here, once per file.

The copy is written next to the .speclib, named for it with -specvault on the
end: lib.predicted.speclib gets lib.predicted-specvault.parquet. Next to it so
that anybody looking at the folder can see it and use it themselves; named so
that it is plainly not one of DIA-NN's own outputs.

Where DIA-NN is: DIANN_PATH (in the environment, or backend/.env), otherwise
`diann-linux` or `diann` on the PATH. A server without DIA-NN still reads a
.speclib whose copy is already there -- one made by the Linux server, say,
read from a Windows PC that has no DIA-NN of its own. It just cannot make new
ones, and says so.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from typing import Optional

log = logging.getLogger(__name__)

EXTENSION = ".speclib"
COPY_SUFFIX = "-specvault.parquet"

# A 2.8-million-precursor library took DIA-NN 2.5 minutes on 32 threads. An
# hour is a library well past anything the lab has, or DIA-NN stuck.
TIMEOUT_SECONDS = 60 * 60


class Unreadable(Exception):
    """Why a .speclib could not be turned into something SpecVault reads.
    The message is said to the person, so it says what to do where it can."""


def is_speclib(path: str) -> bool:
    return path.lower().endswith(EXTENSION)


def copy_path(speclib: str) -> str:
    """Where the readable copy of *speclib* goes, whether or not it exists."""
    return speclib[: -len(EXTENSION)] + COPY_SUFFIX


def diann() -> Optional[str]:
    """The DIA-NN to run, or None when this server has none."""
    configured = os.getenv("DIANN_PATH", "").strip()
    if configured:
        if os.path.isfile(configured):
            return configured
        log.warning("DIANN_PATH is %s, but there is no file there", configured)
        return None
    return shutil.which("diann-linux") or shutil.which("diann")


def existing_copy(speclib: str) -> Optional[str]:
    """The copy of *speclib*, if there is one at least as new as the .speclib.

    An older one is of a library that has since been rewritten -- reading it
    would describe the old file under the new one's hash.
    """
    copy = copy_path(speclib)
    try:
        if os.path.getmtime(copy) >= os.path.getmtime(speclib):
            return copy
    except OSError:
        pass
    return None


# One conversion per file at a time. Auto-fill reads the library twice at once
# -- the counts and mod table, and the library details -- and both need the
# copy; the second waits for the first and then finds it made.
_LOCKS: dict = {}
_LOCKS_LOCK = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(os.path.normcase(os.path.abspath(path)), threading.Lock())


def readable_copy(speclib: str) -> str:
    """The .parquet copy of *speclib*, made now if need be. Raises Unreadable."""
    with _lock_for(speclib):
        found = existing_copy(speclib)
        if found:
            return found
        program = diann()
        if program is None:
            raise Unreadable(
                "SpecVault reads a .speclib by having DIA-NN convert it to .parquet, "
                "and DIA-NN is not set up on this server (set DIANN_PATH). "
                f"If {os.path.basename(copy_path(speclib))} is made next to it, "
                "that will be read instead."
            )
        _convert(program, speclib, copy_path(speclib))
        return copy_path(speclib)


def _convert(program: str, speclib: str, copy: str) -> None:
    """Have DIA-NN write *speclib* out as *copy*.

    DIA-NN writes into a scratch folder on this machine first, not straight
    onto the share: it leaves a log beside whatever it writes, which nobody
    wants next to their library, and a copy half-written when DIA-NN fails
    must never be mistaken for a finished one. The finished file is copied
    across under a temporary name and only then given its own.
    """
    with tempfile.TemporaryDirectory(prefix="specvault-diann-") as work:
        out = os.path.join(work, "library.parquet")
        # A script that runs DIA-NN elsewhere -- diann/diann-docker.sh -- is
        # run through sh, so it works whether or not git kept it executable
        launcher = ["sh", program] if program.endswith(".sh") else [program]
        command = [
            *launcher,
            "--lib", speclib,
            "--out-lib", out,
            "--gen-spec-lib",
            "--threads", str(os.cpu_count() or 1),
            # No runs, so no report -- but DIA-NN's default for one is the
            # folder it was started in, so it is pointed here too
            "--out", os.path.join(work, "report.parquet"),
        ]
        log.info("Converting %s with %s", speclib, program)
        try:
            result = subprocess.run(
                command, cwd=work, capture_output=True, text=True,
                errors="replace", timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise Unreadable(
                f"DIA-NN was still converting the .speclib after "
                f"{TIMEOUT_SECONDS // 60} minutes, and was stopped."
            )
        except OSError as e:
            raise Unreadable(f"DIA-NN could not be started ({program}): {e}")

        if result.returncode != 0 or not os.path.isfile(out):
            output = result.stdout + result.stderr
            # DIA-NN names itself first thing. Output without that is from
            # before it started -- the system's libraries, or Docker -- and
            # nothing to do with the .speclib or which version made it.
            if "DIA-NN" not in output:
                raise Unreadable(
                    f"DIA-NN could not run on this server ({program}): " + _last_lines(output)
                )
            raise Unreadable(
                "DIA-NN could not convert the .speclib. A .speclib can need the "
                "DIA-NN version that made it, or a newer one. DIA-NN said: "
                + _last_lines(output)
            )

        partial = copy + ".partial"
        try:
            shutil.copyfile(out, partial)
            os.replace(partial, copy)
        except OSError as e:
            try:
                os.remove(partial)
            except OSError:
                pass
            raise Unreadable(f"DIA-NN converted the .speclib, but {copy} could not be written: {e}")
    log.info("Wrote %s", copy)


def _last_lines(output: str, count: int = 4) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return " / ".join(lines[-count:]) or "(nothing)"
