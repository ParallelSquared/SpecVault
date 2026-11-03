"""The column spellings each tool writes, and that all of them are read.

The aliases come from JMod's own table, which reads DIA-NN, JMod, Spectronaut
and FragPipe libraries -- the list that has actually met these files. These
tests are the guard on it: a spelling dropped from COLUMN_ALIASES or
FRAGMENT_ALIASES turns into a real library being refused as "not a spectral
library", which is the worst way for this to fail, because the refusal is
confident and the file is fine.

FragPipe is the one that would have been refused before the table arrived: it
writes ModifiedPeptideSequence, which nothing here recognised.
"""
import pytest

from app.routers import libraries as lib

# Two fragments for one precursor, written the way each tool writes it.
DIALECTS = {
    "diann": [
        ("Modified.Sequence", ["AC(UniMod:4)DEK"] * 2),
        ("Stripped.Sequence", ["ACDEK"] * 2),
        ("Protein.Group", ["P1"] * 2),
        ("Precursor.Charge", [2, 2]),
        ("Precursor.Mz", [333.1, 333.1]),
        ("Fragment.Type", ["y", "b"]),
        ("Fragment.Series.Number", [3, 2]),
        ("Fragment.Charge", [1, 1]),
        ("Product.Mz", [401.2, 251.1]),
    ],
    "spectronaut": [
        ("ModifiedPeptide", ["_AC[Carbamidomethyl (C)]DEK_"] * 2),
        ("StrippedPeptide", ["ACDEK"] * 2),
        ("ProteinGroup", ["P1"] * 2),
        ("PrecursorCharge", [2, 2]),
        ("PrecursorMz", [333.1, 333.1]),
        ("FragmentType", ["y", "b"]),
        ("FragmentNumber", [3, 2]),
        ("FragmentCharge", [1, 1]),
        ("FragmentMz", [401.2, 251.1]),
        ("RelativeIntensity", [1.0, 0.5]),
        ("iRT", [23.4, 23.4]),
    ],
    "fragpipe": [
        ("ModifiedPeptideSequence", ["AC[160]DEK"] * 2),
        ("PeptideSequence", ["ACDEK"] * 2),
        ("ProteinId", ["P1"] * 2),
        ("PrecursorCharge", [2, 2]),
        ("PrecursorMz", [333.1, 333.1]),
        ("FragmentType", ["y", "b"]),
        ("FragmentSeriesNumber", [3, 2]),
        ("FragmentCharge", [1, 1]),
        ("ProductMz", [401.2, 251.1]),
        ("LibraryIntensity", [1.0, 0.5]),
        ("NormalizedRetentionTime", [23.4, 23.4]),
    ],
}


def write(path, columns):
    rows = len(columns[0][1])
    lines = ["\t".join(name for name, _ in columns)]
    for i in range(rows):
        lines.append("\t".join(str(values[i]) for _, values in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture(params=sorted(DIALECTS))
def dialect(request, tmp_path):
    name = request.param
    return name, write(tmp_path / f"{name}.tsv", DIALECTS[name])


# ------------------------------------------------------- every dialect reads

def test_the_file_is_accepted_as_a_library(dialect):
    name, path = dialect
    frame = lib._read_library_df(path)
    assert len(frame) == 1, f"{name}: two fragment rows are one precursor"


def test_the_precursor_is_counted(dialect):
    _, path = dialect
    assert lib._determine_precursors(lib._read_library_df(path)) == 1


def test_the_protein_is_counted(dialect):
    """ProteinId is FragPipe's spelling and was not recognised, so its
    libraries catalogued with no protein count and a missing-column warning."""
    _, path = dialect
    assert lib._determine_proteins(lib._read_library_df(path)) == 1


def test_nothing_is_reported_missing(dialect):
    name, path = dialect
    missing = lib._find_missing_columns(lib._read_library_df(path))
    assert missing == [], f"{name} is missing {missing}"


# -------------------------------------------------------- and is still read

def test_fragments_are_found_whatever_they_are_called(dialect):
    _, path = dialect
    available = lib._scan_library(path).collect_schema().names()
    assert any(name in available for name in lib.FRAGMENT_COLUMNS)


def test_the_stats_find_their_columns(dialect):
    """Not just accepted -- actually read. The details panel is empty if the
    fragment columns are spelled a way library_stats does not know."""
    name, path = dialect
    stats = lib._build_library_stats(path)
    assert stats is not None, name
    assert stats.get("fragments"), f"{name}: no fragment section"


# -------------------------------------------- underscores as terminus markers

class TestUnderscoreWrappedSequences:
    """FragPipe and Spectronaut write _[527.18773]PEPTIDEK, the underscores
    marking the termini. An N-terminal label is recognised by sitting at the
    start of the sequence, so behind the _ it was silently dropped -- in the
    library that showed it, all 64,510 sequences were written this way and not
    one N-terminal label made the table."""

    def write(self, tmp_path, *sequences):
        columns = [
            ("ModifiedPeptideSequence", [s for s in sequences for _ in range(2)]),
            ("PrecursorCharge", [2] * 2 * len(sequences)),
            ("FragmentType", ["y", "b"] * len(sequences)),
            ("ProductMz", [401.2, 251.1] * len(sequences)),
        ]
        return lib._read_library_df(write(tmp_path / "lib.tsv", columns))

    def sites(self, frame):
        return {(m.name, m.site): m.precursors
                for m in lib.mods.mod_sites(lib._precursor_sequences(frame))}

    def test_the_n_terminal_label_is_found(self, tmp_path):
        frame = self.write(tmp_path, "_[527.18773]INEAVEC(UniMod:4)LLSLK[527.18773]")
        sites = self.sites(frame)
        assert sites[("527.18773", "N-term")] == 1
        assert sites[("527.18773", "K")] == 1
        assert sites[("UniMod:4", "C")] == 1

    def test_it_counts_the_same_as_an_unwrapped_sequence(self, tmp_path):
        wrapped = self.sites(self.write(tmp_path, "_[527.18773]PEPTIDEK[527.18773]_"))
        plain = self.sites(self.write(tmp_path, "[527.18773]PEPTIDEK[527.18773]"))
        assert wrapped == plain

    def test_underscores_inside_a_mod_name_are_kept(self, tmp_path):
        """Only the outer ones go. A label named H_DM_mod is still H_DM_mod --
        stripping every underscore would rename it, and an unrecognised name
        is an unidentified tag."""
        sites = self.sites(self.write(tmp_path, "_(H_DM_mod)PEPTIDEK(H_DM_mod)_"))
        assert ("H_DM_mod", "N-term") in sites
        assert ("H_DM_mod", "K") in sites

    def test_the_peptide_has_no_underscores_when_worked_out(self, tmp_path):
        """Without a stripped column the peptide is derived from the modified
        sequence, and the markers would make every one two residues longer
        and start with _ -- which the digest section reads as its N-terminus."""
        path = write(tmp_path / "nostripped.tsv", [
            ("ModifiedPeptideSequence", ["_[527.18773]PEPTIDEK_"] * 2),
            ("PrecursorCharge", [2, 2]),
            ("FragmentType", ["y", "b"]),
            ("ProductMz", [401.2, 251.1]),
        ])
        stats = lib._build_library_stats(path)
        assert stats["precursors"]["length"]["min"] == len("PEPTIDEK")


# ------------------------------------------- the alias table stays in step

def test_fragpipes_modified_sequence_is_recognised():
    """Named on its own because it is the one that would be refused outright
    rather than merely analysed poorly: without it there are no precursors."""
    assert "ModifiedPeptideSequence" in lib.COLUMN_ALIASES["Modified.Sequence"]


def test_the_dotted_spelling_wins_when_a_file_has_both(tmp_path):
    """_get_column takes the first alias present, so the order in the table
    decides. A file carrying two spellings of one thing should read as the
    DIA-NN one rather than by accident."""
    path = write(tmp_path / "both.tsv", [
        ("Modified.Sequence", ["AK"]),
        ("ModifiedPeptide", ["_AK_"]),
        ("Precursor.Charge", [2]),
        ("Product.Mz", [201.1]),
    ])
    frame = lib._read_library_df(path)
    assert lib._get_column(frame, "Modified.Sequence") == "Modified.Sequence"
