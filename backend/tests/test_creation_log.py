"""Tests for reading what a creation log says about the library it built."""
import os
from datetime import date, datetime

from app import creation_log

BANNER = """
DIA-NN 2.5.0 Academia  (Data-Independent Acquisition by Neural Networks)
Compiled on Apr 12 2026 17:01:59
Current date and time: Tue Sep 29 16:10:05 2026
CPU: GenuineIntel Intel(R) Xeon(R) Gold 6126 CPU @ 2.60GHz
"""


def write_log(folder, command, body="", name="report.log.txt", banner=BANNER):
    """A DIA-NN log in *folder*, which mirrors the --out folder in *command*."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(banner + command + "\n\n" + body)
    return path


def mirrored(tmp_path):
    """The folder L:\\JMod\\DIANN\\lib_mbr really is, under tmp_path."""
    return os.path.join(str(tmp_path), "JMod", "DIANN", "lib_mbr")


COMMAND = (r"diann.exe --f L:\JMod\Data\run 1.raw --f L:\JMod\Data\run2.raw --lib  --threads 10"
           r" --out L:\JMod\DIANN\lib_mbr\report.parquet --out-lib L:\JMod\DIANN\lib_mbr\lib.parquet"
           r" --fasta L:\fasta\human.fasta --reanalyse --cut K*,R*")
RUNS = r"""[29:02] Loading run L:\JMod\Data\run 1.raw
[136:32] Loading run L:\JMod\Data\run2.raw
Second pass: using the newly created spectral library to reanalyse the data
[205:07] Loading run L:\JMod\Data\run 1.raw
[208:44] Loading run L:\JMod\Data\run2.raw
"""


def test_the_software_version_and_date_are_read(tmp_path):
    facts = creation_log.read(write_log(mirrored(tmp_path), COMMAND, RUNS))
    assert facts.software == "DIA-NN"
    assert facts.version == "2.5.0"
    assert facts.generated == date(2026, 9, 29)


def test_paths_are_translated_from_the_mapped_drive(tmp_path):
    """DIA-NN wrote L:\\, but the log lives under tmp_path. Comparing the log's
    real folder with its --out folder gives the mapping."""
    facts = creation_log.read(write_log(mirrored(tmp_path), COMMAND, RUNS))
    assert facts.fasta == [os.path.join(str(tmp_path), "fasta", "human.fasta")]
    assert facts.runs[0] == os.path.join(str(tmp_path), "JMod", "Data", "run 1.raw")


def test_each_run_is_listed_once_in_order(tmp_path):
    """With MBR every run is loaded once per pass."""
    facts = creation_log.read(write_log(mirrored(tmp_path), COMMAND, RUNS))
    assert [os.path.basename(r) for r in facts.runs] == ["run 1.raw", "run2.raw"]


def test_reanalyse_means_mbr(tmp_path):
    assert creation_log.read(write_log(mirrored(tmp_path), COMMAND, RUNS)).mbr is True


def test_without_reanalyse_there_is_no_mbr(tmp_path):
    command = COMMAND.replace(" --reanalyse", "")
    assert creation_log.read(write_log(mirrored(tmp_path), command, RUNS)).mbr is False


def test_runs_given_with_dir_come_from_the_loading_lines(tmp_path):
    """--dir names a folder, not runs; the runs show up as they are loaded."""
    command = (r"diann.exe --dir L:\JMod\Data --out L:\JMod\DIANN\lib_mbr\report.parquet"
               r" --fasta L:\fasta\human.fasta")
    facts = creation_log.read(write_log(mirrored(tmp_path), command, RUNS))
    assert len(facts.runs) == 2


def test_runs_fall_back_to_the_command_before_any_are_loaded(tmp_path):
    facts = creation_log.read(write_log(mirrored(tmp_path), COMMAND, ""))
    assert [os.path.basename(r) for r in facts.runs] == ["run 1.raw", "run2.raw"]


def test_an_in_silico_only_run_has_no_source_runs(tmp_path):
    command = (r"diann.exe --lib  --out L:\JMod\DIANN\lib_mbr\report.parquet --gen-spec-lib"
               r" --predictor --fasta L:\fasta\human.fasta --fasta-search")
    facts = creation_log.read(write_log(mirrored(tmp_path), command))
    assert facts.runs == []
    assert facts.mbr is False


def test_every_fasta_is_kept(tmp_path):
    command = COMMAND + r" --fasta L:\fasta\contaminants.fasta"
    facts = creation_log.read(write_log(mirrored(tmp_path), command, RUNS))
    assert [os.path.basename(f) for f in facts.fasta] == ["human.fasta", "contaminants.fasta"]


def test_paths_already_valid_here_are_left_alone(tmp_path):
    folder = mirrored(tmp_path)
    command = f"diann.exe --out {folder}\\report.parquet --fasta {tmp_path}\\fasta\\human.fasta"
    facts = creation_log.read(write_log(folder, command))
    assert facts.fasta == [f"{tmp_path}\\fasta\\human.fasta"]


def test_without_an_out_path_nothing_is_translated(tmp_path):
    command = r"diann.exe --f L:\JMod\Data\run2.raw --fasta L:\fasta\human.fasta"
    facts = creation_log.read(write_log(mirrored(tmp_path), command))
    assert facts.fasta == [r"L:\fasta\human.fasta"]


def test_an_unreadable_date_is_left_blank(tmp_path):
    banner = BANNER.replace("Tue Sep 29 16:10:05 2026", "sometime")
    assert creation_log.read(write_log(mirrored(tmp_path), COMMAND, banner=banner)).generated is None


def test_a_file_in_no_known_format_reads_as_nothing(tmp_path):
    path = tmp_path / "notes.log.txt"
    path.write_text("Spectronaut 19.0\nsomething else entirely\n", encoding="utf-8")
    assert creation_log.read(str(path)) is None


def test_a_missing_log_reads_as_nothing(tmp_path):
    assert creation_log.read(str(tmp_path / "absent.log.txt")) is None


# ------------------------------------------------------------------- finding it

def library_in(folder):
    path = os.path.join(folder, "lib.parquet")
    open(path, "w").close()
    return path


def test_the_report_log_beside_the_library_is_found(tmp_path):
    folder = mirrored(tmp_path)
    write_log(folder, COMMAND, name="other.log.txt")
    log = write_log(folder, COMMAND)
    assert creation_log.find(library_in(folder)) == log


def test_any_diann_log_beside_the_library_is_found(tmp_path):
    folder = mirrored(tmp_path)
    log = write_log(folder, COMMAND, name="my_run.log.txt")
    assert creation_log.find(library_in(folder)) == log


def test_a_log_txt_that_is_not_from_diann_is_ignored(tmp_path):
    folder = mirrored(tmp_path)
    os.makedirs(folder)
    with open(os.path.join(folder, "report.log.txt"), "w") as handle:
        handle.write("not DIA-NN\n")
    assert creation_log.find(library_in(folder)) is None


def test_no_log_beside_the_library_finds_nothing(tmp_path):
    folder = mirrored(tmp_path)
    os.makedirs(folder)
    assert creation_log.find(library_in(folder)) is None


def test_a_folder_that_cannot_be_listed_finds_nothing(tmp_path):
    assert creation_log.find(str(tmp_path / "absent" / "lib.parquet")) is None


# ------------------------------------------------------------------------- JMod

def jmod_log(results, mbr=True, version="2.1.0-7-g857745b", written=None):
    """A JMod log as it writes them, in *results* (a JMod_Results_* folder),
    for two runs written on drive L:. *written* is the folder JMod says it
    wrote the log to."""
    written = written or r"L:\JMod\JMod_Results_2026_10_30_10_17_39"
    passes = [("First pass", r"\first_pass"), ("Final pass, against the MBR library", "")]
    lines = [
        f"00:00:23 - INFO - JMod v{version}",
        "00:00:23 - INFO - Branch Multi-Run, commit 857745b",
        f"00:00:23 - INFO - Log writing to {written}\\JMod_log.log",
        "00:00:23 - INFO - Loaded 16479 library precursors",
    ]
    for title, sub in passes if mbr else passes[:1]:
        lines += ["00:00:35 - INFO - ", f"00:00:35 - INFO - {title}", "00:00:35 - INFO - "]
        for i, run in enumerate(["L:/JMod/Data/run 1.mzML", "L:/JMod/Data/run2.mzML"], 1):
            lines += [f"00:00:35 - INFO - Run {i} of 2", f"00:00:35 - INFO - {run}",
                      f"00:00:35 - INFO - Results will be saved to {written}{sub}\\run{i}_results",
                      f"00:11:12 - INFO - Run {i} of 2 finished"]
        if mbr and sub:
            lines.append(f"00:21:09 - INFO - MBR library written to {written}\\mbr_library\\mbrlib.parquet")
    lines.append("00:46:21 - INFO - JMod Finished")
    os.makedirs(results, exist_ok=True)
    path = os.path.join(results, "JMod_log.log")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def jmod_results(tmp_path):
    """The folder L:\\JMod\\JMod_Results_... really is, under tmp_path."""
    return os.path.join(str(tmp_path), "JMod", "JMod_Results_2026_10_30_10_17_39")


def test_a_jmod_log_gives_its_software_and_release(tmp_path):
    """v2.1.0-7-g857745b is seven commits past 2.1.0; the release is the version."""
    facts = creation_log.read(jmod_log(jmod_results(tmp_path)))
    assert facts.software == "JMod"
    assert facts.version == "2.1.0"


def test_a_jmod_library_is_dated_by_when_its_log_was_last_written(tmp_path):
    """JMod logs elapsed times, not a date, and its results folder need not be
    named by date."""
    log = jmod_log(os.path.join(str(tmp_path), "JMod", "my_results"), written=r"L:\JMod\my_results")
    finished = datetime(2026, 10, 30, 11, 3).timestamp()
    os.utime(log, (finished, finished))
    assert creation_log.read(log).generated == date(2026, 10, 30)


def test_jmod_runs_are_listed_once_and_translated(tmp_path):
    """Each run comes up once per pass; JMod writes forward slashes on L:."""
    facts = creation_log.read(jmod_log(jmod_results(tmp_path)))
    assert facts.runs == [os.path.join(str(tmp_path), "JMod", "Data", "run 1.mzML"),
                          os.path.join(str(tmp_path), "JMod", "Data", "run2.mzML")]


def test_a_jmod_mbr_library_means_mbr(tmp_path):
    assert creation_log.read(jmod_log(jmod_results(tmp_path))).mbr is True
    assert creation_log.read(jmod_log(jmod_results(tmp_path), mbr=False)).mbr is False


def test_jmod_has_no_fasta(tmp_path):
    assert creation_log.read(jmod_log(jmod_results(tmp_path))).fasta == []


def test_the_jmod_log_above_its_mbr_library_is_found(tmp_path):
    results = jmod_results(tmp_path)
    log = jmod_log(results)
    library = os.path.join(results, "mbr_library")
    os.makedirs(library)
    assert creation_log.find(library_in(library)) == log


def test_a_diann_log_above_the_library_is_not_taken(tmp_path):
    """Only JMod puts its library a folder below its log."""
    folder = mirrored(tmp_path)
    write_log(folder, COMMAND)
    below = os.path.join(folder, "sub")
    os.makedirs(below)
    assert creation_log.find(library_in(below)) is None

