"""Tests for app/mods.py -- where modifications sit, what they weigh, and
which tag that makes them.

The mass tests build libraries backwards: pick the masses, compute the m/z the
precursor would have, and check the solver recovers what went in.
"""
import json

import polars as pl
import pytest

from app import mods


def mz_for(stripped, mod_masses, charge):
    """The m/z a precursor would have, given the masses on it."""
    neutral = sum(mods.RESIDUE_MASSES[r] for r in stripped) + mods.WATER + sum(mod_masses)
    return (neutral + charge * mods.PROTON) / charge


def library(rows):
    """rows: (modified, stripped, [mod masses], charge) -> the four series."""
    frame = pl.DataFrame(
        [(m, s, float(z), mz_for(s, masses, z)) for m, s, masses, z in rows],
        schema=["modified", "stripped", "charge", "mz"], orient="row",
    )
    return frame["modified"], frame["stripped"], frame["charge"], frame["mz"]


# ------------------------------------------------------------------ sites

def sites_of(*sequences):
    return {(s.name, s.site): s.precursors for s in mods.mod_sites(pl.Series(sequences))}


def test_site_is_the_residue_in_front_of_the_annotation():
    assert sites_of("PEPTC(UniMod:4)IDEK") == {("UniMod:4", "C"): 1}


def test_annotation_before_the_first_residue_is_the_n_terminus():
    assert sites_of("(tag)PEPTIDEK") == {("tag", "N-term"): 1}


def test_annotation_behind_the_first_residue_belongs_to_that_residue():
    """K(H_DM_mod) is a modification on K. That is how these libraries are
    written, and it is what makes a label on every amino acid visible."""
    assert sites_of("K(H_DM_mod)LGEPIR") == {("H_DM_mod", "K"): 1}


def test_a_label_on_every_residue_shows_up_on_every_residue():
    counts = sites_of("K(mod)AAA", "L(mod)AAA", "S(mod)AAA")
    assert counts == {("mod", "K"): 1, ("mod", "L"): 1, ("mod", "S"): 1}


def test_stacked_annotations_both_belong_to_the_residue_they_follow():
    assert sites_of("K(H_DM_mod)(dimethyl)LGEPIR") == {
        ("H_DM_mod", "K"): 1, ("dimethyl", "K"): 1,
    }


def test_square_brackets_are_read_too():
    assert sites_of("PEPTC[UniMod:4]IDEK") == {("UniMod:4", "C"): 1}


def test_counts_are_precursors_not_occurrences():
    """Two tags on one peptide is one precursor carrying the tag on K."""
    assert sites_of("AK(tag)DK(tag)E") == {("tag", "K"): 1}


def test_the_same_mod_on_two_residues_counts_on_each():
    assert sites_of("AK(tag)DC(tag)E") == {("tag", "K"): 1, ("tag", "C"): 1}


def test_sites_are_sorted_by_precursors():
    counts = mods.mod_sites(pl.Series(["K(m)A", "K(m)D", "C(m)A"]))
    assert [(s.site, s.precursors) for s in counts] == [("K", 2), ("C", 1)]


def test_no_modifications_gives_no_sites():
    assert mods.mod_sites(pl.Series(["PEPTIDEK"])) == []


def test_empty_input_gives_no_sites():
    assert mods.mod_sites(pl.Series([], dtype=pl.String)) == []


# ------------------------------------------------------------------ masses

def test_a_single_modification_mass_is_recovered():
    series = library([("AC(mod)DEK", "ACDEK", [57.021464], 2)])
    assert mods.derive_masses(*series)["mod"] == pytest.approx(57.021464, abs=1e-4)


def test_two_modifications_are_separated_even_though_they_never_appear_alone():
    """The dimethyl libraries are like this: every precursor carries both an
    N-terminal label and a dimethyl, so neither can be worked out on its own.
    Only the varying ratio between them makes the system solvable."""
    series = library([
        ("(nterm)AK(dim)DEK(dim)", "AKDEK", [36.07567, 28.03130, 28.03130], 2),
        ("(nterm)AK(dim)DE", "AKDE", [36.07567, 28.03130], 2),
        ("(nterm)PK(dim)DEK(dim)R", "PKDEKR", [36.07567, 28.03130, 28.03130], 3),
        ("(nterm)PEPK(dim)R", "PEPKR", [36.07567, 28.03130], 2),
    ])
    found = mods.derive_masses(*series)
    assert found["nterm"] == pytest.approx(36.07567, abs=1e-4)
    assert found["dim"] == pytest.approx(28.03130, abs=1e-4)


def test_two_modifications_locked_in_one_ratio_are_not_separable():
    """Always exactly one of each means any split of the combined mass fits.
    Reporting nothing is the honest answer; reporting half each is not."""
    series = library([
        ("(a)AK(b)DE", "AKDE", [36.07567, 28.03130], 2),
        ("(a)PK(b)DER", "PKDER", [36.07567, 28.03130], 2),
    ])
    assert mods.derive_masses(*series) == {}


def test_a_mass_that_does_not_explain_the_data_is_withheld():
    """One annotation name carrying two different masses -- a channel-multiplexed
    library -- has no single answer, and the residual says so."""
    series = library([
        ("AK(dim)DE", "AKDE", [28.03130], 2),
        ("AK(dim)DE", "AKDE", [36.07567], 2),
        ("PK(dim)DER", "PKDER", [28.03130], 2),
        ("PK(dim)DER", "PKDER", [36.07567], 2),
    ])
    assert mods.derive_masses(*series) == {}


def test_unmodified_libraries_have_no_masses_to_find():
    assert mods.derive_masses(*library([("PEPTIDEK", "PEPTIDEK", [], 2)])) == {}


def test_precursors_with_unknown_residues_are_left_out():
    """U and X have no mass here, so their equations are meaningless -- but the
    rest of the library still solves."""
    series = library([("AC(mod)DEK", "ACDEK", [57.021464], 2)])
    modified = pl.concat([series[0], pl.Series(["UC(mod)DEK"])])
    stripped = pl.concat([series[1], pl.Series(["UCDEK"])])
    charge = pl.concat([series[2], pl.Series([2.0])])
    mz = pl.concat([series[3], pl.Series([400.0])])
    assert mods.derive_masses(modified, stripped, charge, mz)["mod"] == pytest.approx(57.0215, abs=1e-4)


def test_unimod_four_is_not_confused_with_unimod_forty():
    series = library([
        ("AC(UniMod:4)DEK", "ACDEK", [57.021464], 2),
        ("AC(UniMod:40)DEK", "ACDEK", [79.956815], 2),
    ])
    found = mods.derive_masses(*series)
    assert found["UniMod:4"] == pytest.approx(57.021464, abs=1e-4)
    assert found["UniMod:40"] == pytest.approx(79.956815, abs=1e-4)


def test_fragment_rows_do_not_change_the_answer():
    """A library repeats each precursor once per fragment. The fit sees each
    precursor once, so the repetition costs nothing and changes nothing."""
    rows = [
        ("(nterm)AK(dim)DEK(dim)", "AKDEK", [36.07567, 28.03130, 28.03130], 2),
        ("(nterm)AK(dim)DE", "AKDE", [36.07567, 28.03130], 2),
        ("(nterm)PK(dim)DEK(dim)R", "PKDEKR", [36.07567, 28.03130, 28.03130], 3),
    ]
    once = mods.derive_masses(*library(rows))
    twelve = mods.derive_masses(*library(rows * 12))
    assert once.keys() == twelve.keys()
    assert all(once[k] == pytest.approx(twelve[k], abs=1e-9) for k in once)


def peptides(count, start=0):
    """Distinct stripped peptides, so each is its own precursor."""
    letters = "ADEFGHILMNPQSTVWY"
    return ["".join(letters[(i // len(letters) ** p) % len(letters)] for p in range(3)) + "K"
            for i in range(start, start + count)]


def test_a_rare_modification_survives_the_sample(monkeypatch):
    """The cap is per modification. Carbamidomethyl on 9 precursors out of
    40,000 is the broken-library case the missing-mass warning exists for, and
    a library-wide sample would almost never contain it."""
    monkeypatch.setattr(mods, "SAMPLE_PER_MOD", 5)
    rows = [(f"(common){p}", p, [42.010565], 2) for p in peptides(200)]
    rows += [(f"(rare){p}", p, [79.966331], 2) for p in peptides(2, start=500)]
    found = mods.derive_masses(*library(rows))
    assert found["rare"] == pytest.approx(79.966331, abs=1e-4)
    assert found["common"] == pytest.approx(42.010565, abs=1e-4)


def test_a_two_channel_modification_is_still_caught_when_sampled(monkeypatch):
    """Two channels under one name, written in two blocks. The first N in the
    file would all be one channel and fit perfectly; a random sample shows both
    and fails the residual check, which is the right answer."""
    monkeypatch.setattr(mods, "SAMPLE_PER_MOD", 20)
    rows = [(f"(dim){p}", p, [28.03130], 2) for p in peptides(60)]
    rows += [(f"(dim){p}", p, [36.07567], 2) for p in peptides(60, start=60)]
    assert "dim" not in mods.derive_masses(*library(rows))


# ------------------------------------------------------------------ conflicts

def test_one_sequence_at_two_masses_is_a_conflict():
    modified, _, charge, mz = library([
        ("AK(dim)DE", "AKDE", [28.03130], 2),
        ("AK(dim)DE", "AKDE", [36.07567], 2),
    ])
    assert mods.mass_conflicts(modified, charge, mz) == 1


def test_a_consistent_library_has_no_conflicts():
    modified, _, charge, mz = library([
        ("AK(dim)DE", "AKDE", [28.03130], 2),
        ("PK(dim)DER", "PKDER", [28.03130], 2),
    ])
    assert mods.mass_conflicts(modified, charge, mz) == 0


def test_the_same_sequence_at_two_charges_is_not_a_conflict():
    modified, _, charge, mz = library([
        ("AK(dim)DE", "AKDE", [28.03130], 2),
        ("AK(dim)DE", "AKDE", [28.03130], 3),
    ])
    assert mods.mass_conflicts(modified, charge, mz) == 0


# ------------------------------------------------------------------ tags

def tags_for(mass, site=None):
    return mods.tag_names(mods.identify_tag(mass, site))


def test_the_psmtag_mass_measured_from_the_catalog_is_psmtag():
    """308.11609 is what the libraries in this catalog actually carry; the
    definition says 308.1160923903."""
    assert tags_for(308.11609) == ["PSMtag"]


@pytest.mark.parametrize(
    "mass, expected, reason",
    [
        (310.122802, "2", "d2, which lives in PSMtag_9plex"),
        (312.127048, "4", "the d4 channel"),
        (308.116092, "0", "the unlabelled channel"),
    ],
)
def test_psmtag_channels_are_named(mass, expected, reason):
    matched = mods.identify_tag(mass)
    assert {c.channel for c in matched} == {expected}, reason


def test_a_channel_outside_the_loaded_definitions_is_not_claimed():
    """PSMtag_9plex_D16v2's channel 16 is 0.0088 Da from the one we load. We do
    not recognise it, and saying so beats reporting the neighbour."""
    assert mods.identify_tag(324.163450) == []
    assert [c.channel for c in mods.identify_tag(324.154667)] == ["16"]


def test_every_psmtag_set_resolves_to_the_plain_tag_name():
    assert tags_for(316.142931) == ["PSMtag"]


@pytest.mark.parametrize(
    "mass, site, expected",
    [
        (28.031300, "N-term", "dimethyl"),   # light
        (36.075670, "N-term", "dimethyl"),   # heavy: H_DM_mod, or UniMod:330
        (140.094963, "K", "mtraq"),
        (56.062600, "K", "diethyl"),
        (6.020129, "K", "SILAC-K"),          # 13C(6), UniMod:188
        (6.020129, "R", "SILAC-R"),          # the same mass, the other residue
        (8.014199, "K", "SILAC-K"),          # 13C(6)15N(2), UniMod:259
        (10.008269, "R", "SILAC-R"),         # 13C(6)15N(4), UniMod:267
    ],
)
def test_the_other_tags_are_matched_by_mass(mass, site, expected):
    assert expected in tags_for(mass, site)


def test_the_same_mass_on_two_residues_is_two_different_labels():
    """13C(6) weighs 6.020129 whichever residue carries it. Only the site tells
    the Lys label from the Arg one, which is why identification takes both."""
    assert tags_for(6.020129, "K") == ["SILAC-K"]
    assert tags_for(6.020129, "R") == ["SILAC-R"]


def test_the_site_never_rejects_an_unambiguous_match():
    """H_DM_mod sits on twenty-two different residues in the predicted
    libraries. A definition that says "nK" must not stop us naming it on the
    other twenty, or the mod table hides the very thing it is there to show."""
    assert tags_for(36.075670, "S") == ["dimethyl"]   # dimethyl's rules say nK
    assert tags_for(8.014199, "R") == ["SILAC-K"]     # nothing else weighs this


def test_without_a_site_an_ambiguous_mass_returns_both():
    assert tags_for(6.020129) == ["SILAC-K", "SILAC-R"]


# ------------------------------------------------------- what a mod should weigh

@pytest.mark.parametrize(
    "accession, mass",
    [
        ("UniMod:1", 42.010565),
        ("UniMod:4", 57.021464),
        ("UniMod:7", 0.984016),
        ("UniMod:35", 15.994915),
        ("UniMod:121", 114.042927),   # K-gg
        ("UniMod:330", 36.075670),
    ],
)
def test_known_accessions_have_their_unimod_mass(accession, mass):
    assert mods.expected_mass(accession) == pytest.approx(mass)


def test_an_accession_we_do_not_know_goes_unchecked():
    assert mods.expected_mass("UniMod:99999") is None
    assert mods.expected_mass("tag") is None


def test_a_weightless_annotation_is_not_identified_as_anything():
    """SILAC channel 0 is a real channel and stays in the definition file, but
    nothing can be recognised by weighing nothing -- and a library that drops a
    modification's mass while keeping its annotation produces exactly that."""
    assert mods.identify_tag(0.0, "K") == []
    assert all(c.mass >= mods.MIN_MATCHABLE_MASS for c in mods.TAG_CHANNELS)


@pytest.mark.parametrize(
    "rules, site, allowed",
    [
        ("nK", "N-term", True),
        ("K", "N-term", False),
        ("nK", "K", True),
        ("nK", "N", False),   # asparagine is not the N-terminus
        ("R", "K", False),
    ],
)
def test_site_rules_are_read_correctly(rules, site, allowed):
    assert mods.site_allows(rules, site) is allowed


def test_carbamidomethyl_is_not_a_tag():
    assert tags_for(57.021464) == []


def test_an_unknown_label_is_not_forced_onto_the_nearest_channel():
    assert tags_for(309.5) == []


def test_a_missing_mass_identifies_nothing():
    assert mods.identify_tag(None) == []


def test_channels_sharing_a_mass_do_not_share_a_site():
    """Otherwise a modification would match two tags with nothing to separate
    them -- which is exactly what the site rules are for."""
    channels = mods.TAG_CHANNELS
    clashes = [
        (a.tag, a.channel, b.tag, b.channel)
        for i, a in enumerate(channels) for b in channels[i + 1:]
        if abs(a.mass - b.mass) <= mods.MASS_TOLERANCE
        and set(a.sites.replace("n", "")) & set(b.sites.replace("n", ""))
    ]
    assert clashes == []


def test_no_two_channels_of_different_mass_fall_inside_the_tolerance():
    """If this fails, some library will be reported as an ambiguous match."""
    channels = mods.TAG_CHANNELS
    clashes = [
        (a.definition, a.channel, b.definition, b.channel)
        for i, a in enumerate(channels) for b in channels[i + 1:]
        if abs(a.mass - b.mass) <= mods.MASS_TOLERANCE and round(a.mass, 4) != round(b.mass, 4)
    ]
    assert clashes == []


# ------------------------------------------------------------------ the table

def test_the_vocabulary_comes_from_the_definitions():
    """Adding a definition is all it should take to add a tag."""
    assert mods.TAG_OPTIONS == sorted(set(mods.TAG_DEFINITIONS.values()))


def test_each_tag_is_defined_once():
    """The smaller plex sets are subsets of the ones loaded; loading both would
    only produce two answers to the same question."""
    values = list(mods.TAG_DEFINITIONS.values())
    assert len(values) == len(set(values))


def test_a_missing_directory_is_not_fatal(tmp_path):
    """Without the definition files, tags still match by name."""
    assert mods.load_tag_channels(tmp_path / "absent") == []


def test_a_malformed_definition_does_not_take_the_others_down(tmp_path):
    (tmp_path / "PSMtag_9plex.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "dimethyl.json").write_text(json.dumps({
        "name": "dimethyl", "base_mass": 28.0313, "delta": [0.0],
        "channel_names": ["0"],
    }), encoding="utf-8")
    loaded = mods.load_tag_channels(tmp_path)
    assert [(c.tag, c.channel) for c in loaded] == [("dimethyl", "0")]


def test_the_bundled_definitions_load():
    assert len(mods.TAG_CHANNELS) > 20
    assert {c.tag for c in mods.TAG_CHANNELS} == set(mods.TAG_OPTIONS)
