"""DIA-NN's .speclib, read through the .parquet copy DIA-NN makes of it.

DIA-NN itself is not run here -- most machines that run these tests have none
-- so a stand-in takes its place: it is handed the same command, and writes
the .parquet DIA-NN would. The "speclib" each test uses is a TSV library under
a .speclib name, which the stand-in knows how to read and SpecVault does not.
"""
import hashlib
import os
import subprocess

import polars as pl
import pytest

import libraries
from app import speclib


@pytest.fixture
def lib(tmp_path):
    """A .speclib, with two precursors in it."""
    return str(libraries.write(tmp_path / "lib.predicted.speclib", "PEPTIDK", "ANTHERK"))


@pytest.fixture
def diann(monkeypatch):
    """A DIA-NN on this machine that converts as the real one does.

    Records each command it is given, so a test can see what was asked and
    how often. `fail` makes it fail as DIA-NN does on a library it cannot
    load: exit code 1, no library written.
    """
    state = {"commands": [], "fail": False}

    def run(command, cwd=None, **kwargs):
        state["commands"].append(command)
        if state["fail"]:
            return subprocess.CompletedProcess(
                command, 1, "DIA-NN 2.0.1 Academia\nLoading spectral library\nERROR: cannot read the library", "",
            )
        given = command[command.index("--lib") + 1]
        out = command[command.index("--out-lib") + 1]
        pl.read_csv(given, separator="\t").write_parquet(out)
        return subprocess.CompletedProcess(command, 0, "Spectral library saved", "")

    monkeypatch.setattr(speclib, "diann", lambda: "/opt/diann/diann-linux")
    monkeypatch.setattr(speclib.subprocess, "run", run)
    return state


@pytest.fixture
def no_diann(monkeypatch):
    monkeypatch.setattr(speclib, "diann", lambda: None)


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def analyze(client, path):
    return client.post("/libraries/analyze", json={"path": path})


def save(client, path, **extra):
    return client.post("/libraries/", json={"path": path, "creator": "ZC", **extra})


# ------------------------------------------------------------- the copy

def test_the_copy_is_named_for_the_speclib():
    assert speclib.copy_path("/lab/x/lib.predicted.speclib") == "/lab/x/lib.predicted-specvault.parquet"


def test_auto_fill_reads_a_speclib(client, lib, diann):
    filled = analyze(client, lib)
    assert filled.status_code == 200, filled.text
    assert filled.json()["precursors"] == 2


def test_the_copy_is_written_next_to_it(client, lib, diann):
    analyze(client, lib)
    copy = speclib.copy_path(lib)
    assert os.path.isfile(copy)
    assert pl.read_parquet(copy).height == 4  # two precursors, two fragments each


def test_auto_fill_says_where_it_read_from(client, lib, diann):
    assert "lib.predicted-specvault.parquet" in analyze(client, lib).json()["warning"]


def test_diann_is_asked_to_write_the_library_out(client, lib, diann):
    analyze(client, lib)
    command = diann["commands"][0]
    assert command[0] == "/opt/diann/diann-linux"
    assert command[command.index("--lib") + 1] == lib
    assert "--gen-spec-lib" in command


def test_diann_runs_once_for_auto_fill_and_save(client, lib, diann):
    """Auto-fill reads the library twice at once, and Save reads it again;
    the copy made by the first is what the rest read."""
    analyze(client, lib)
    save(client, lib)
    assert len(diann["commands"]) == 1


def test_save_without_auto_fill_converts_too(client, lib, diann):
    saved = save(client, lib)
    assert saved.status_code == 201, saved.text
    assert saved.json()["precursors"] == 2


# ----------------------------------------------------------- the entry

def test_the_entry_is_the_speclib(client, lib, diann):
    saved = save(client, lib).json()
    assert saved["path"] == lib
    assert saved["content_hash"] == sha256(lib)
    assert saved["file_format"] == "SPECLIB"


def test_the_entry_records_its_copy(client, lib, diann):
    saved = save(client, lib).json()
    copy = speclib.copy_path(lib)
    assert saved["readable_copy_path"] == copy
    assert saved["display_readable_copy_path"] == copy
    assert saved["readable_copy_hash"] == sha256(copy)


def test_the_library_details_are_read_from_the_copy(client, lib, diann):
    assert save(client, lib).json()["library_stats"] is not None


def test_other_libraries_have_no_copy(client, library_file):
    saved = save(client, library_file()).json()
    assert saved["readable_copy_path"] is None
    assert saved["readable_copy_hash"] is None


# ------------------------------------- one library, found by either file

def test_adding_the_copy_finds_the_speclib_entry(client, lib, diann):
    entry = save(client, lib).json()
    refused = save(client, speclib.copy_path(lib))
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["library_id"] == entry["id"]
    assert ".parquet copy" in detail["message"]


def test_the_copy_is_not_offered_as_another_path(client, lib, diann):
    """Every path of an entry is the same bytes; the copy is not."""
    save(client, lib)
    assert save(client, speclib.copy_path(lib)).json()["detail"]["already_recorded"] is True


def test_auto_fill_on_the_copy_says_so(client, lib, diann):
    save(client, lib)
    assert analyze(client, speclib.copy_path(lib)).json()["duplicate"]["library_id"] is not None


# ------------------------------------------------------- without DIA-NN

def test_an_existing_copy_is_read_without_diann(client, lib, diann, monkeypatch):
    """A Windows PC with no DIA-NN, reading a copy the Linux server made."""
    analyze(client, lib)
    os.utime(lib, (1, 1))  # a different version of the file to the caches above
    monkeypatch.setattr(speclib, "diann", lambda: None)
    os.utime(speclib.copy_path(lib), None)  # and the copy newer than it
    saved = save(client, lib)
    assert saved.status_code == 201, saved.text
    assert saved.json()["precursors"] == 2


def test_no_diann_and_no_copy_says_so(client, lib, no_diann):
    refused = analyze(client, lib)
    assert refused.status_code == 400
    assert "DIA-NN is not set up" in refused.json()["detail"]


def test_it_can_still_be_saved_as_unreadable(client, lib, no_diann):
    asked = save(client, lib)
    assert asked.status_code == 409
    assert "DIA-NN" in asked.json()["detail"]["message"]
    assert save(client, lib, save_unreadable=True).status_code == 201


def test_a_copy_made_after_a_failed_read_is_read(client, lib, diann, monkeypatch):
    """Tried from a PC with no DIA-NN, then converted by the server: trying
    again finds the copy rather than remembering that there was none."""
    monkeypatch.setattr(speclib, "diann", lambda: None)
    assert analyze(client, lib).status_code == 400
    monkeypatch.setattr(speclib, "diann", lambda: "/opt/diann/diann-linux")
    speclib.readable_copy(lib)
    monkeypatch.setattr(speclib, "diann", lambda: None)
    assert analyze(client, lib).json()["precursors"] == 2
    assert save(client, lib).status_code == 201


def test_auto_fill_work_is_reused_at_save(client, lib, diann, monkeypatch):
    """The parse Auto-fill did is filed under the file with its copy, so Save
    finds it rather than parsing the library a second time."""
    analyze(client, lib)
    from app.routers import libraries as router
    monkeypatch.setattr(router, "_read_library_df", lambda path: pytest.fail("parsed again"))
    assert save(client, lib).status_code == 201


def test_a_copy_older_than_the_speclib_is_not_read(client, lib, diann, monkeypatch):
    """The .speclib has been rewritten since: the copy describes the old one."""
    analyze(client, lib)
    copy = speclib.copy_path(lib)
    os.utime(copy, (1, 1))
    os.utime(lib, None)
    assert speclib.existing_copy(lib) is None


def test_a_stale_copy_is_made_again(client, lib, diann):
    analyze(client, lib)
    os.utime(speclib.copy_path(lib), (1, 1))
    os.utime(lib, None)
    speclib.readable_copy(lib)
    assert len(diann["commands"]) == 2


# ------------------------------------------------------- DIA-NN failing

def test_diann_failing_says_what_diann_said(client, lib, diann):
    diann["fail"] = True
    refused = analyze(client, lib)
    assert refused.status_code == 400
    assert "cannot read the library" in refused.json()["detail"]


def test_diann_failing_blames_the_version(client, lib, diann):
    diann["fail"] = True
    assert "version" in analyze(client, lib).json()["detail"]


def test_diann_not_starting_does_not_blame_the_version(client, lib, monkeypatch):
    """What Ubuntu 20.04 said: DIA-NN never got as far as the .speclib."""
    monkeypatch.setattr(speclib, "diann", lambda: "/opt/diann/diann-linux")
    monkeypatch.setattr(speclib.subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(
        command, 1, "", "diann-linux: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.34' not found",
    ))
    detail = analyze(client, lib).json()["detail"]
    assert "could not run on this server" in detail
    assert "GLIBC_2.34" in detail
    assert "version that made it" not in detail


def test_a_script_is_run_through_sh(client, lib, diann, monkeypatch):
    """diann-docker.sh, which git on Windows may not have kept executable."""
    monkeypatch.setattr(speclib, "diann", lambda: "/srv/specvault/diann-docker.sh")
    analyze(client, lib)
    assert diann["commands"][0][:2] == ["sh", "/srv/specvault/diann-docker.sh"]


def test_diann_failing_leaves_nothing_behind(client, lib, diann):
    diann["fail"] = True
    analyze(client, lib)
    assert sorted(os.listdir(os.path.dirname(lib))) == ["lib.predicted.speclib"]
