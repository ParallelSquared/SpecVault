"""Unit tests for the library-file analysis helpers.

These functions decide the metadata that ends up in the catalog -- precursor
and protein counts, protease, PTMs -- so a wrong answer here is a wrong number
in somebody's methods section. Several tests below exist because the original
implementation got these wrong; each one names the failure it guards against.
"""
import hashlib
import random

import polars as pl
import pytest

from app.routers import libraries as lib

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


def peptides(n, prefix="", suffix="", seed=0):
    """n distinct pseudo-random peptides, optionally with a fixed terminus."""
    rng = random.Random(seed)
    out = set()
    while len(out) < n:
        body = "".join(rng.choice(AMINO_ACIDS) for _ in range(rng.randint(6, 14)))
        out.add(f"{prefix}{body}{suffix}")
    return sorted(out)


def stripped(seqs):
    return pl.DataFrame({"Stripped.Sequence": seqs})


def modified(seqs):
    return pl.DataFrame({"Modified.Sequence": seqs})


# --------------------------------------------------------------------- protease

@pytest.mark.parametrize(
    "sequences, expected",
    [
        (peptides(500, suffix="K", seed=1), "LysC"),
        (peptides(500, prefix="D", seed=2), "AspN"),
        (peptides(500, suffix="E", seed=3), "GluC"),
        (peptides(500, suffix="R", seed=4), "ArgC"),
    ],
    ids=["lysc", "aspn", "gluc", "argc"],
)
def test_protease_detected_from_termini(sequences, expected):
    assert lib._determine_protease(stripped(sequences)) == expected


def test_tryptic_library_prefers_trypsin_over_single_residue_rules():
    rng = random.Random(5)
    seqs = [p + rng.choice("KR") for p in peptides(1000, seed=5)]
    assert lib._determine_protease(stripped(seqs)) == "Trypsin"


def test_lysc_wins_over_trypsin_when_both_fit_perfectly():
    # Every peptide ends in K, so Trypsin (K/R) and LysC (K) both score 1.0.
    # The more specific rule should win.
    assert lib._determine_protease(stripped(peptides(500, suffix="K", seed=6))) == "LysC"


def test_partially_ragged_digest_still_detected():
    rng = random.Random(7)
    tryptic = [p + rng.choice("KR") for p in peptides(900, seed=7)]
    ragged = [p + "G" for p in peptides(100, seed=8)]
    assert lib._determine_protease(stripped(tryptic + ragged)) == "Trypsin"


def test_non_enzymatic_peptides_report_no_protease():
    """Regression: a near-zero best score used to be reported as a confident hit.

    500 random peptides have no consistent terminus, so every rule scores badly
    and the answer must be "unknown" rather than whichever rule scored least
    badly (which was ArgC).
    """
    assert lib._determine_protease(stripped(peptides(500, seed=9))) is None


@pytest.mark.parametrize(
    "frame",
    [
        pl.DataFrame({"Unrelated.Column": ["PEPTIDEK"]}),
        pl.DataFrame({"Stripped.Sequence": pl.Series([None, None], dtype=pl.String)}),
        pl.DataFrame({"Stripped.Sequence": pl.Series([], dtype=pl.String)}),
    ],
    ids=["missing-column", "all-null", "empty"],
)
def test_protease_none_without_usable_sequences(frame):
    assert lib._determine_protease(frame) is None


# --------------------------------------------------------------------- proteins

def test_proteins_counts_distinct_accessions_across_groups():
    frame = pl.DataFrame({"Protein.Group": ["P1;P2", "P2;P3", "P1"]})
    assert lib._determine_proteins(frame) == 3


def test_proteins_ignores_null_and_empty_groups():
    """Regression: n_unique() counted a null group as if it were a protein."""
    frame = pl.DataFrame({"Protein.Group": ["P1;P2", "P2", None, "", "P3"]})
    assert lib._determine_proteins(frame) == 3


def test_proteins_tolerates_whitespace_around_separators():
    frame = pl.DataFrame({"Protein.Group": [" P1 ; P2 ", "P1"]})
    assert lib._determine_proteins(frame) == 2


def test_proteins_none_when_column_missing():
    assert lib._determine_proteins(pl.DataFrame({"Other": ["x"]})) is None


# ------------------------------------------------------------------- precursors

def test_precursors_counts_distinct_sequence_charge_pairs():
    frame = pl.DataFrame({
        "Modified.Sequence": ["AK", "AK", "AK", "BK"],
        "Precursor.Charge": [2, 2, 3, 2],
    })
    assert lib._determine_precursors(frame) == 3


def test_precursors_ignores_rows_with_nulls():
    frame = pl.DataFrame({
        "Modified.Sequence": ["AK", None, "BK"],
        "Precursor.Charge": [2, 2, None],
    })
    assert lib._determine_precursors(frame) == 1


@pytest.mark.parametrize(
    "frame",
    [
        pl.DataFrame({"Modified.Sequence": ["AK"]}),
        pl.DataFrame({"Precursor.Charge": [2]}),
    ],
    ids=["no-charge-column", "no-sequence-column"],
)
def test_precursors_none_without_both_columns(frame):
    assert lib._determine_precursors(frame) is None


# ------------------------------------------------------------- carbamidomethyl

def test_carbamidomethylation_detected():
    assert lib._determine_carbamidomethylated(modified(["AC(UniMod:4)DEK", "PEPTIDEK"])) is True


def test_carbamidomethylation_absent():
    assert lib._determine_carbamidomethylated(modified(["PEPTIDEK", "A(UniMod:35)K"])) is False


@pytest.mark.parametrize("accession", ["UniMod:40", "UniMod:41", "UniMod:400"])
def test_unimod_4_is_not_matched_as_a_prefix(accession):
    """Regression: a substring check made UniMod:40 look like carbamidomethyl."""
    assert lib._determine_carbamidomethylated(modified([f"PEP({accession})TIDEK"])) is False


def test_carbamidomethylation_none_when_column_missing():
    assert lib._determine_carbamidomethylated(pl.DataFrame({"Other": ["x"]})) is None


# ------------------------------------------------------------------------- PTMs

def test_mods_listed_without_carbamidomethyl_and_sorted_numerically():
    frame = modified([
        "A(UniMod:35)C(UniMod:4)K",
        "B(UniMod:21)K",
        "C(UniMod:1)K",
        "D(UniMod:21)K",
    ])
    assert lib._determine_mods(frame) == ["UniMod:1", "UniMod:21", "UniMod:35"]


def test_mods_empty_when_only_carbamidomethyl_present():
    assert lib._determine_mods(modified(["AC(UniMod:4)DEK"])) == []


def test_mods_empty_when_column_missing():
    assert lib._determine_mods(pl.DataFrame({"Other": ["x"]})) == []


# ------------------------------------------------------------------------- tags

@pytest.mark.parametrize(
    "sequence, expected",
    [
        ("PEPT(dimethyl)IDEK", ["dimethyl"]),
        ("PEPT(Dimethyl)IDEK", ["dimethyl"]),
        ("PEPT[dimethyl]IDEK", ["dimethyl"]),
        ("PEPT(mTRAQ)IDEK", ["mtraq"]),
        ("PEPT(diethyl)IDEK", ["diethyl"]),
        ("PEPT(PSMtag)IDEK", ["PSMtag"]),
    ],
    ids=["paren", "mixed-case", "bracket", "mtraq", "diethyl", "psmtag"],
)
def test_tags_read_from_modification_annotations(sequence, expected):
    assert lib._determine_tags(modified([sequence])) == expected


def test_tag_matched_alongside_other_text_in_the_annotation():
    assert lib._determine_tags(modified(["PEPT(Dimethyl K8)IDEK"])) == ["dimethyl"]


def test_multiple_tags_sorted():
    sequences = ["PEPT(mTRAQ)IDEK", "PEPT(Dimethyl)IDEK"]
    assert lib._determine_tags(modified(sequences)) == ["dimethyl", "mtraq"]


@pytest.mark.parametrize(
    "sequence",
    ["PEPTIDESILACK", "ELVISMTRAQK", "SAMPLEPSMTAGK", "ADIETHYLK", "KDIMETHYLR"],
    ids=["silac", "mtraq", "psmtag", "diethyl", "dimethyl"],
)
def test_amino_acid_runs_are_not_mistaken_for_tags(sequence):
    """Regression: tag names were matched anywhere in the sequence.

    SILAC, MTRAQ, PSMTAG, DIETHYL and DIMETHYL are all spellable in one-letter
    amino-acid codes, so these unmodified peptides were reported as labelled
    libraries. In a million-precursor library the SILAC collision alone is
    expected several times over, and one hit mislabels the entire file.
    """
    assert lib._determine_tags(modified([sequence])) == ["LF"]


def test_one_false_looking_peptide_does_not_outvote_the_library():
    sequences = [f"PEPTIDE{i}K" for i in range(500)] + ["PEPTIDESILACK"]
    assert lib._determine_tags(modified(sequences)) == ["LF"]


def test_unimod_annotations_alone_are_label_free():
    assert lib._determine_tags(modified(["AC(UniMod:4)DEK"])) == ["LF"]


def test_label_free_is_the_fallback():
    assert lib._determine_tags(modified(["PEPTIDEK"])) == ["LF"]


def test_tags_empty_when_column_missing():
    assert lib._determine_tags(pl.DataFrame({"Other": ["x"]})) == []


# ------------------------------------------------------------------ determinism

@pytest.fixture
def rare_modification_frame():
    """One carbamidomethylated sequence hidden among 3000 that are not.

    The old implementation scored an arbitrary 1000-row slice of
    df[col].unique(), which has no ordering guarantee -- so whether this rare
    sequence was seen varied between runs on identical input.
    """
    sequences = [f"PEP(UniMod:35)TIDE{i}K" for i in range(3000)]
    sequences.append("RARE(UniMod:4)PEPTIDEK")
    return modified(sequences)


def test_rare_modification_is_never_missed(rare_modification_frame):
    results = {lib._determine_carbamidomethylated(rare_modification_frame) for _ in range(20)}
    assert results == {True}


def test_ptm_list_is_stable_across_runs(rare_modification_frame):
    results = {tuple(lib._determine_mods(rare_modification_frame)) for _ in range(20)}
    assert results == {("UniMod:35",)}


def test_protease_is_stable_across_runs():
    rng = random.Random(11)
    seqs = [p + rng.choice("KR") for p in peptides(3000, seed=11)]
    frame = stripped(seqs)
    assert {lib._determine_protease(frame) for _ in range(20)} == {"Trypsin"}


# ------------------------------------------------------------------ file access

def test_find_missing_columns_reports_canonical_names():
    frame = pl.DataFrame({"Modified.Sequence": ["AK"], "Precursor.Charge": [2]})
    assert sorted(lib._find_missing_columns(frame)) == ["Protein.Group", "Stripped.Sequence"]


def test_find_missing_columns_accepts_any_alias():
    frame = pl.DataFrame({
        "ModifiedPeptide": ["AK"],
        "StrippedPeptide": ["AK"],
        "ProteinGroup": ["P1"],
        "PrecursorCharge": [2],
    })
    assert lib._find_missing_columns(frame) == []


def test_read_library_df_reads_tsv_and_selects_known_columns(tmp_path):
    path = tmp_path / "library.tsv"
    path.write_text(
        "Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge\tIgnored\n"
        "A(UniMod:4)K\tAK\tP1\t2\tjunk\n",
        encoding="utf-8",
    )
    frame = lib._read_library_df(str(path))
    assert set(frame.columns) == {
        "Modified.Sequence", "Stripped.Sequence", "Protein.Group", "Precursor.Charge",
    }


def test_read_library_df_rejects_unknown_extension(tmp_path):
    path = tmp_path / "library.xyz"
    path.write_text("whatever", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        lib._read_library_df(str(path))


def test_read_library_df_rejects_file_without_expected_columns(tmp_path):
    path = tmp_path / "library.csv"
    path.write_text("alpha,beta\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected columns"):
        lib._read_library_df(str(path))


def test_hash_file_matches_hashlib(tmp_path):
    path = tmp_path / "library.tsv"
    payload = b"some library contents\n" * 1000
    path.write_bytes(payload)
    assert lib._hash_file(str(path)) == hashlib.sha256(payload).hexdigest()


def test_hash_file_none_for_missing_path(tmp_path):
    assert lib._hash_file(str(tmp_path / "nope.tsv")) is None


# ------------------------------------------------- a library missing a mass

def with_masses(rows):
    """rows: (modified, stripped, [mod masses], charge) -> a library frame."""
    from app import mods as m
    built = []
    for modified_seq, stripped, extra, charge in rows:
        neutral = sum(m.RESIDUE_MASSES[r] for r in stripped) + m.WATER + sum(extra)
        built.append((modified_seq, stripped, float(charge),
                      (neutral + charge * m.PROTON) / charge))
    return pl.DataFrame(
        built,
        schema=["Modified.Sequence", "Stripped.Sequence", "Precursor.Charge", "Precursor.Mz"],
        orient="row",
    )


def carbamidomethyl_library(mass):
    return with_masses([
        ("AC(UniMod:4)DEK", "ACDEK", [mass], 2),
        ("PEC(UniMod:4)PTIDEK", "PECPTIDEK", [mass], 2),
        ("AC(UniMod:4)DEC(UniMod:4)K", "ACDECK", [mass, mass], 2),
        ("PEPTIDEK", "PEPTIDEK", [], 2),
        ("ELVISLIVESK", "ELVISLIVESK", [], 3),
    ])


def test_a_declared_modification_with_no_mass_is_reported():
    """Some of these libraries dropped carbamidomethyl's 57.0215 Da while
    keeping every "(UniMod:4)" in place. Nothing downstream can tell from the
    annotations alone, and every search run against such a library is wrong by
    the missing mass on every cysteine."""
    report = lib._mod_report(carbamidomethyl_library(0.0))
    assert report.note is not None
    assert "UniMod:4" in report.note and "57.02146" in report.note


def test_the_expected_mass_is_stored_so_the_row_can_show_it():
    detail = lib._mod_report(carbamidomethyl_library(0.0)).details[0]
    assert detail["mass"] == pytest.approx(0.0, abs=1e-4)
    assert detail["expected_mass"] == pytest.approx(57.02146)


def test_a_library_that_carries_the_mass_is_not_flagged():
    report = lib._mod_report(carbamidomethyl_library(57.021464))
    assert report.note is None
    assert report.details[0]["mass"] == pytest.approx(57.02146, abs=1e-4)


def test_the_mod_table_counts_precursors_not_sequences():
    """One peptide at two charges is two precursors."""
    frame = with_masses([
        ("AC(UniMod:4)DEK", "ACDEK", [57.021464], 2),
        ("AC(UniMod:4)DEK", "ACDEK", [57.021464], 3),
    ])
    assert lib._mod_report(frame).details[0]["precursors"] == 2


def test_an_accession_with_no_known_mass_is_still_found():
    """The UniMod table only checks masses. An accession it does not list is
    still reported, with the mass the library gives it."""
    report = lib._mod_report(with_masses([
        ("PEPT(UniMod:9999)IDEK", "PEPTIDEK", [42.0], 2),
        ("AC(UniMod:9999)DEK", "ACDEK", [42.0], 2),
    ]))
    detail = report.details[0]
    assert report.ptms == ["UniMod:9999"]
    assert detail["mass"] == pytest.approx(42.0, abs=1e-4)
    assert detail["expected_mass"] is None
    assert report.note is None


def test_a_massless_k_gg_is_flagged_like_carbamidomethyl():
    report = lib._mod_report(with_masses([
        ("PEPTK(UniMod:121)IDEK", "PEPTKIDEK", [0.0], 2),
        ("AK(UniMod:121)DEK", "AKDEK", [0.0], 2),
    ]))
    assert "UniMod:121" in (report.note or "")


def test_the_flag_does_not_depend_on_the_modification_being_common():
    """Nine precursors out of a library is enough: a median residual over every
    row would never notice them."""
    rows = [("AC(UniMod:4)DEK", "ACDEK", [0.0], 2)]
    rows += [(f"PEPTID{r}K", f"PEPTID{r}K", [], 2) for r in "ACDEFGHIKLMNPQRSTVWY"]
    assert "UniMod:4" in (lib._mod_report(with_masses(rows)).note or "")


# --------------------------------------------------------------- label-free

def test_an_unidentifiable_modification_still_reports_label_free():
    """A label we cannot name -- "(tag)" in a library with no resolvable mass --
    leaves the field at LF rather than blank. It is a starting point the user
    edits, and the mod detail table shows the modification either way."""
    assert lib._determine_tags(modified(["PEPT(tag)IDEK"])) == ["LF"]


def test_a_unimod_ptm_on_its_own_is_label_free():
    """Oxidation is a modification, not a label."""
    assert lib._determine_tags(modified(["PEPT(UniMod:35)IDEK"])) == ["LF"]


def test_a_named_tag_wins_over_an_unidentified_one():
    assert lib._determine_tags(modified(["PEPT(Dimethyl)IDEK", "PEPT(tag)IDEK"])) == ["dimethyl"]


def test_a_mass_that_is_present_but_wrong_is_not_called_missing():
    """UniMod:4 weighing what oxidation weighs is a mislabel, not a dropped mass.
    Calling it "missing" would send someone looking for the wrong fault."""
    note = lib._mod_report(carbamidomethyl_library(15.994915)).note or ""
    assert "UniMod lists it as +57.02146" in note
    assert "missing" not in note


def test_a_massless_modification_is_still_called_missing():
    note = lib._mod_report(carbamidomethyl_library(0.0)).note or ""
    assert "missing from its precursor m/z" in note


# ------------------------------------------------- one row per precursor

HEADER = "Modified.Sequence\tStripped.Sequence\tProtein.Group\tPrecursor.Charge\tProduct.Mz\n"


def write_fragments(path, precursors, fragments=6):
    """A library the way they are written: one row per fragment, every
    precursor-level column repeated on each."""
    lines = [HEADER]
    for modified_seq, stripped, group, charge in precursors:
        for f in range(fragments):
            lines.append(f"{modified_seq}\t{stripped}\t{group}\t{charge}\t{200.0 + f}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return str(path)


def test_fragment_rows_are_collapsed_when_read(tmp_path):
    path = write_fragments(tmp_path / "lib.tsv", [
        ("AC(UniMod:4)DEK", "ACDEK", "P1", 2),
        ("AC(UniMod:4)DEK", "ACDEK", "P1", 3),
        ("PEPTIDEK", "PEPTIDEK", "P2", 2),
    ])
    df = lib._read_library_df(path)
    assert df.height == 3
    assert lib._determine_precursors(df) == 3


def test_a_precursor_under_two_protein_groups_still_counts_once(tmp_path):
    """Collapsing keeps distinct rows, not strictly one per precursor -- a
    target that shares its sequence with a decoy is listed under both groups.
    Every count must still come out right."""
    path = write_fragments(tmp_path / "lib.tsv", [
        ("PEPTIDEK", "PEPTIDEK", "P1", 2),
        ("PEPTIDEK", "PEPTIDEK", "DECOY_P1", 2),
    ])
    df = lib._read_library_df(path)
    assert lib._determine_precursors(df) == 1
    assert lib._determine_proteins(df) == 2


def test_rows_come_back_in_file_order(tmp_path):
    """The mass fit's sample is seeded against row order; a collapse that
    shuffled rows would make the same file give different answers."""
    letters = "ADEFGHILMNPQSTVWY"
    peptides = [a + b + c + "K" for a in letters for b in letters for c in letters[:4]]
    path = write_fragments(tmp_path / "lib.tsv", [(p, p, "P1", 2) for p in peptides], fragments=3)
    assert lib._read_library_df(path)["Modified.Sequence"].to_list() == peptides

