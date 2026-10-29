"""Tests for the library details: precursors, fragments and digest."""
import pytest

from app.routers import libraries as lib

COLUMNS = ["Modified.Sequence", "Stripped.Sequence", "Precursor.Charge", "Precursor.Mz", "IM",
           "Decoy", "Fragment.Type", "Fragment.Series.Number", "Fragment.Charge",
           "Fragment.Loss.Type", "Product.Mz"]


def write_library(path, precursors, columns=COLUMNS):
    """precursors: (modified, stripped, charge, mz, im, decoy, [fragments]),
    each fragment (type, number, charge, loss, mz). One row per fragment, the
    way libraries are written."""
    lines = ["\t".join(columns)]
    for modified, stripped, charge, mz, im, decoy, fragments in precursors:
        for ftype, number, fcharge, loss, fmz in fragments:
            row = dict(zip(COLUMNS, [modified, stripped, charge, mz, im, decoy,
                                     ftype, number, fcharge, loss, fmz]))
            lines.append("\t".join(str(row[c]) for c in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def frags(*spec):
    return [(t, n, 1, "noloss", 300.0 + i * 100) for i, (t, n) in enumerate(spec)]


LIBRARY = [
    ("PEPTIDEK", "PEPTIDEK", 2, 465.24, 0.9, 0, frags(("b", 3), ("y", 3), ("y", 4))),
    ("PEPTIDEK", "PEPTIDEK", 3, 310.49, 0.8, 0, frags(("b", 3), ("y", 5))),
    ("ELVISR", "ELVISR", 2, 351.71, 1.1, 0, frags(("b", 4), ("y", 3), ("y", 6), ("b", 5))),
    ("AKPEPTIDER", "AKPEPTIDER", 2, 570.80, 1.2, 0, frags(("y", 3))),
    # A decoy with a charge and an ion type nothing else has: if either shows
    # up anywhere, decoys are leaking into the figures.
    ("KEDITPEP", "KEDITPEP", 5, 186.30, 1.5, 1, frags(("c", 1), ("c", 2))),
]


@pytest.fixture
def stats(tmp_path):
    return lib._build_library_stats(write_library(tmp_path / "lib.tsv", LIBRARY))


# ------------------------------------------------------------- precursors

def test_charges_are_shares_of_target_precursors(stats):
    assert stats["precursors"]["charges"] == {"2": 75.0, "3": 25.0}


def test_precursor_mz_range(stats):
    assert stats["precursors"]["mz"] == [310.49, 570.8]


def test_peptide_lengths_are_over_distinct_peptides(stats):
    assert stats["precursors"]["length"] == {"min": 6, "median": 8.0, "max": 10}


def test_ion_mobility_range(stats):
    assert stats["precursors"]["ion_mobility"] == [0.8, 1.2]


def test_decoys_are_counted_and_nothing_else(stats):
    assert stats["precursors"]["decoys"] == 1
    assert stats["precursors"]["count"] == 4
    assert "5" not in stats["precursors"]["charges"]
    assert "c" not in {t["type"] for t in stats["fragments"]["types"]}


def test_an_all_zero_ion_mobility_column_means_none(tmp_path):
    """DIA-NN writes 0 when there is no ion mobility."""
    flat = [(m, s, z, mz, 0.0, d, f) for m, s, z, mz, _, d, f in LIBRARY]
    stats = lib._build_library_stats(write_library(tmp_path / "lib.tsv", flat))
    assert stats["precursors"]["ion_mobility"] is None


def test_no_ion_mobility_column_means_none(tmp_path):
    columns = [c for c in COLUMNS if c != "IM"]
    stats = lib._build_library_stats(write_library(tmp_path / "lib.tsv", LIBRARY, columns))
    assert stats["precursors"]["ion_mobility"] is None


def test_float_charges_read_as_whole_charges(tmp_path):
    floated = [(m, s, float(z), mz, im, d, f) for m, s, z, mz, im, d, f in LIBRARY]
    stats = lib._build_library_stats(write_library(tmp_path / "lib.tsv", floated))
    assert stats["precursors"]["charges"] == {"2": 75.0, "3": 25.0}


# -------------------------------------------------------------- fragments

def test_fragments_per_precursor(stats):
    assert stats["fragments"]["per_precursor"] == {"min": 1, "median": 2.5, "mean": 2.5, "max": 4}


def test_only_the_ion_types_present_are_reported(stats):
    types = {t["type"]: t for t in stats["fragments"]["types"]}
    assert set(types) == {"b", "y"}
    assert (types["b"]["first"], types["b"]["last"]) == (3, 5)
    assert (types["y"]["first"], types["y"]["last"]) == (3, 6)


def test_ion_type_means_add_up_to_the_fragment_mean(stats):
    total = sum(t["mean"] for t in stats["fragments"]["types"])
    assert total == pytest.approx(stats["fragments"]["per_precursor"]["mean"])


def test_fragment_charges_losses_and_mz(stats):
    f = stats["fragments"]
    assert f["charges"] == [1]
    assert f["losses"] == ["noloss"]
    assert f["mz"] == [300.0, 600.0]


def test_a_library_without_fragment_columns_has_no_fragment_section(tmp_path):
    columns = ["Modified.Sequence", "Stripped.Sequence", "Precursor.Charge", "Precursor.Mz"]
    stats = lib._build_library_stats(write_library(tmp_path / "lib.tsv", LIBRARY, columns))
    assert stats["fragments"] is None
    assert stats["precursors"]["count"] == 5  # no Decoy column to leave any out


# ----------------------------------------------------------------- digest

def test_tryptic_termini_are_reported_per_residue(stats):
    digest = stats["digest"]
    assert digest["protease"] == "Trypsin"
    assert digest["residues"] == {"K": pytest.approx(33.33), "R": pytest.approx(66.67)}
    assert digest["other"] == pytest.approx(0.0)


def test_a_k_before_p_is_still_a_missed_cleavage(stats):
    """Trypsin cuts at K and R whatever follows; AKPEPTIDER missed one."""
    assert stats["digest"]["missed_cleavages"] == {"0": pytest.approx(66.67), "1": pytest.approx(33.33)}


def test_nothing_is_left_out_of_the_terminal_shares(tmp_path):
    """A protein C-terminal peptide that ends in neither K nor R is reported
    under "other", not excluded."""
    extra = LIBRARY + [("ELVISLIVESG", "ELVISLIVESG", 2, 580.3, 1.0, 0, frags(("y", 3)))]
    digest = lib._build_library_stats(write_library(tmp_path / "lib.tsv", extra))["digest"]
    assert digest["other"] == pytest.approx(25.0)


def test_an_n_terminal_protease_reads_the_first_residue(tmp_path):
    aspn = [("DPEPTIK", "DPEPTIK", 2, 400.0, 1.0, 0, frags(("y", 3))),
            ("DELVISDK", "DELVISDK", 2, 450.0, 1.0, 0, frags(("y", 3))),
            ("DAAAK", "DAAAK", 2, 250.0, 1.0, 0, frags(("y", 3)))]
    digest = lib._build_library_stats(write_library(tmp_path / "lib.tsv", aspn))["digest"]
    assert digest["protease"] == "AspN"
    assert digest["residues"] == {"D": pytest.approx(100.0)}
    # DELVISDK has a D inside it; the D it starts with is the cut, not a miss
    assert digest["missed_cleavages"] == {"0": pytest.approx(66.67), "1": pytest.approx(33.33)}


def test_no_protease_no_digest_section(tmp_path):
    mixed = [(s, s, 2, 400.0, 1.0, 0, frags(("y", 3))) for s in ("PEPTIDEA", "PEPTIDEG", "PEPTIDES", "PEPTIDEV")]
    assert lib._build_library_stats(write_library(tmp_path / "lib.tsv", mixed))["digest"] is None
