"""Modifications in a spectral library: where they sit, how many precursors
carry them, and what they weigh.

The library tells us everything we need. A precursor's m/z and charge give its
neutral mass; subtracting the mass of its bare residues leaves the mass of its
modifications. Do that across the whole library and the result is one linear
equation per precursor, which solves for every modification's mass at once.
Nothing has to be looked up for that to work.

There is a short table of UniMod masses below, but it is only used to check the
answer: a modification it does not list is still found, counted and weighed,
and simply goes unchecked.

That matters because libraries do not agree on names. The same DIA-NN export
writes the N-terminal label as "H_DM_mod" in one file and "UniMod:330" in
another; both come out at +36.0756 Da here, which is how we recognise them as
the same thing. It is also how a library that labels its tag as nothing more
descriptive than "(tag)" still gets reported as PSMtag.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

import polars as pl

# Monoisotopic residue masses. I and L are identical by mass, which is fine --
# nothing here needs to tell them apart.
RESIDUE_MASSES = {
    "G": 57.021464, "A": 71.037114, "S": 87.032028, "P": 97.052764,
    "V": 99.068414, "T": 101.047679, "C": 103.009185, "L": 113.084064,
    "I": 113.084064, "N": 114.042927, "D": 115.026943, "Q": 128.058578,
    "K": 128.094963, "E": 129.042593, "M": 131.040485, "H": 137.058912,
    "F": 147.068414, "R": 156.101111, "Y": 163.063329, "W": 186.079313,
}
WATER = 18.0105646863
PROTON = 1.00727646688

# Parentheses and square brackets are the only annotation formats we use.
ANNOTATION_PATTERN = r"\([^()]*\)|\[[^\[\]]*\]"
# A residue (or the start of the peptide) together with every annotation that
# follows it, so that the site of each annotation is the residue in front of it.
SITE_GROUP_PATTERN = r"(?:^|[A-Z])(?:\([^()]*\)|\[[^\[\]]*\])+"
_NAME_PATTERN = re.compile(r"\(([^()]*)\)|\[([^\[\]]*)\]")

N_TERM = "N-term"

# How close a derived mass has to be to a known one to count as a match.
#
# Masses solved from real libraries land within 0.0001 Da of their definition,
# so this has fifty times the room it needs, while staying far inside the
# roughly 2 Da that separates neighbouring channels.
MASS_TOLERANCE = 0.005

# A solved system always returns numbers; only the residual says whether they
# mean anything. Two labels that always appear together in a fixed ratio are
# not separable, and the fit will happily split their combined mass between
# them at whatever ratio it likes. Real libraries sit under 0.005 Da.
MAX_MEDIAN_RESIDUAL = 0.05

# Precursors fitted per modification. Each one is an exact equation, so a
# thousand pins a mass down many times over. On a 28-million-row library the
# fit went from twenty seconds to under three, nearly all of which is now just
# collapsing fragment rows into precursors. The cap is per modification
# rather than library-wide so that a rare one survives: carbamidomethyl on 9
# precursors out of 40,000 would almost never be in a library-wide sample of a
# thousand, and that rare, broken case is exactly what the missing-mass warning
# is for. The sample is random rather than the first thousand in the file, so
# that a modification carried in two channels shows both and fails the
# residual check instead of passing on whichever channel happens to come first.
SAMPLE_PER_MOD = 1000

# The tags this catalog recognises, and the only place they are read from.
MASS_TAGS_DIR = Path(__file__).parent / "mass_tags"

# One definition per tag, the widest of each, mapped to what the catalog calls
# it: the smaller plex sets are subsets of these, so loading them too would only
# give two answers to the same question. SILAC-K and SILAC-R are built from
# UniMod -- 13C(6) on either residue, plus 13C(6)15N(2) on Lys and 13C(6)15N(4)
# on Arg.
TAG_DEFINITIONS = {
    "PSMtag_9plex.json": "PSMtag",
    "dimethyl.json": "dimethyl",
    "diethyl_6plex.json": "diethyl",
    "mTRAQ.json": "mtraq",
    "SILAC-K.json": "SILAC-K",
    "SILAC-R.json": "SILAC-R",
}

# The vocabulary the catalog filters by, taken from the definitions themselves
# so that adding a definition is all it takes to add a tag.
TAG_OPTIONS = sorted(set(TAG_DEFINITIONS.values()))

N_TERM_RULE = "n"

# A channel that weighs nothing cannot be recognised by weight. SILAC channel 0
# is a real channel and stays in the definition file, but an annotation that
# adds no mass is matched by every zero -- including the broken libraries below
# that declare a modification and leave its mass out. Identifying those as a
# SILAC light channel would be worse than saying nothing.
MIN_MATCHABLE_MASS = 0.5


class TagChannel(NamedTuple):
    """One channel of one tag: what the catalog calls it, which channel, what
    it weighs, and where the label can sit."""
    tag: str          # a TAG_OPTIONS name, e.g. "PSMtag"
    channel: str      # "0", "2", "4", ...
    mass: float
    sites: str        # the definition's rules: "n" for the N-terminus, plus residues


def load_tag_channels(directory: Optional[Path] = None) -> List[TagChannel]:
    """Every tag channel we recognise, as base_mass + delta.

    A missing or unreadable file is not fatal: without it, tags are still
    matched by the names a library spells out, just not by mass.
    """
    directory = Path(directory) if directory else MASS_TAGS_DIR
    channels: List[TagChannel] = []
    for filename, tag in TAG_DEFINITIONS.items():
        try:
            with open(directory / filename, encoding="utf-8") as handle:
                data = json.load(handle)
            base = float(data["base_mass"])
            deltas = [float(d) for d in data["delta"]]
            names = [str(n) for n in data["channel_names"]]
            sites = str(data.get("rules", ""))
        except (OSError, ValueError, KeyError, TypeError):
            continue  # a malformed definition should not take the catalog down
        for name, delta in zip(names, deltas):
            mass = base + delta
            if mass >= MIN_MATCHABLE_MASS:
                channels.append(TagChannel(tag, name, mass, sites))
    return channels


TAG_CHANNELS = load_tag_channels()


# What a named modification is supposed to weigh, from unimod.org -- the ones
# these libraries use, plus K-gg. This only checks masses; it does not decide
# what gets found. An accession that is not listed here is still reported with
# the mass the library gives it, there is just nothing to compare that to.
UNIMOD_MASSES = {
    "UniMod:1": 42.010565,    # Acetyl
    "UniMod:4": 57.021464,    # Carbamidomethyl
    "UniMod:7": 0.984016,     # Deamidated
    "UniMod:35": 15.994915,   # Oxidation
    "UniMod:121": 114.042927, # GG, the K-gg ubiquitin remnant
    "UniMod:330": 36.075670,  # Dimethyl:2H(6)13C(2)
}


def expected_mass(name: str) -> Optional[float]:
    """What a modification of this name should weigh, if we know. A library
    that disagrees with this is telling us something is wrong with it."""
    return UNIMOD_MASSES.get(name)


class ModSite(NamedTuple):
    """One modification at one kind of site: the N-terminus, or a residue."""
    name: str          # as the library spells it
    site: str          # "N-term", or a single residue letter
    precursors: int    # how many precursors carry it there


def mod_sites(sequences: pl.Series) -> List[ModSite]:
    """Which modifications sit where, and on how many precursors.

    The site is the residue in front of the annotation, so K(H_DM_mod) is a
    modification on K. A label that reaches the peptide N-terminus is written
    in front of the first residue and gets "N-term"; one written behind it
    reports as being on whichever residue it follows, which is what makes a
    label on every amino acid visible as exactly that.
    """
    if sequences.is_empty():
        return []

    frame = pl.DataFrame({
        "precursor": pl.int_range(0, sequences.len(), eager=True),
        "group": sequences.str.extract_all(SITE_GROUP_PATTERN),
    }).explode("group", empty_as_null=False).drop_nulls("group")
    if frame.is_empty():
        return []

    # Distinct groups are few -- "K(dimethyl)", "(tag)", "C(UniMod:4)" -- so
    # parsing them in Python costs nothing however large the library is.
    parsed = []
    for group in frame["group"].unique().to_list():
        site = N_TERM if group[0] in "([" else group[0]
        for paren, bracket in _NAME_PATTERN.findall(group):
            parsed.append((group, paren or bracket, site))
    if not parsed:
        return []

    lookup = pl.DataFrame(
        parsed, schema={"group": pl.String, "name": pl.String, "site": pl.String}, orient="row"
    )
    counted = (
        frame.join(lookup, on="group")
        .group_by("name", "site")
        .agg(pl.col("precursor").n_unique().alias("precursors"))
        .sort(["precursors", "name", "site"], descending=[True, False, False])
    )
    return [ModSite(*row) for row in counted.iter_rows()]


def derive_masses(
    modified: pl.Series, stripped: pl.Series, charge: pl.Series, mz: pl.Series,
    names: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Each modification's mass in Da, solved from the precursors' m/z.

    Every precursor contributes one equation: the masses of the modifications
    it carries, weighted by how many of each, sum to its observed neutral mass
    minus the mass of its bare residues. Solving them together is what lets
    this work on a library where no precursor carries only one kind of
    modification -- in the dimethyl libraries every single precursor has both
    an N-terminal label and a dimethyl, so working them out one at a time is
    impossible.

    A modification whose mass does not then explain the precursors carrying it
    is left out, so the caller sees no mass rather than a wrong one. The same
    goes for the whole library when the system has no single solution: two
    modifications that always appear together in the same ratio cannot be told
    apart, and a fiction is worse than a blank.
    """
    # One row per precursor. A library has a row per fragment, so the columns
    # handed in repeat each precursor a dozen or more times over.
    frame = pl.DataFrame({
        "modified": modified, "stripped": stripped,
        "charge": charge.cast(pl.Float64, strict=False), "mz": mz.cast(pl.Float64, strict=False),
    }).drop_nulls().unique(maintain_order=True)
    names = sorted(names) if names is not None else _annotation_names(frame["modified"])
    if not names:
        return {}

    # Unmodified precursors contribute nothing to the fit -- every count in
    # their equation is zero -- so only carriers are kept, SAMPLE_PER_MOD of
    # each, chosen by a fixed random order so the same file always gives the
    # same answer. One filter over the frame rather than a copy per modification.
    order = pl.int_range(pl.len()).shuffle(seed=0).alias("_order")
    carries = [pl.col("modified").str.contains(_count_pattern(n)) for n in names]
    frame = frame.with_columns(order).filter(pl.any_horizontal([
        carrier & (pl.col("_order").rank("ordinal").over(carrier) <= SAMPLE_PER_MOD)
        for carrier in carries
    ])).drop("_order")

    residues = pl.sum_horizontal([
        pl.col("stripped").str.count_matches(letter, literal=True) * mass
        for letter, mass in RESIDUE_MASSES.items()
    ])
    standard = pl.sum_horizontal([
        pl.col("stripped").str.count_matches(letter, literal=True)
        for letter in RESIDUE_MASSES
    ])
    frame = frame.with_columns(
        (pl.col("mz") * pl.col("charge") - pl.col("charge") * PROTON - residues - WATER).alias("delta"),
        *[
            pl.col("modified").str.count_matches(_count_pattern(name)).cast(pl.Float64).alias(f"n{i}")
            for i, name in enumerate(names)
        ],
    ).filter(
        # A residue with no mass (U, O, X, B, Z) makes the equation meaningless
        (standard == pl.col("stripped").str.len_chars())
        & (pl.col("charge") > 0)
        & pl.col("delta").is_finite()
    )
    if frame.is_empty():
        return {}

    # Normal equations for the least-squares fit, accumulated by polars in a
    # single pass rather than row by row in Python.
    k = len(names)
    sums = frame.select(
        *[(pl.col(f"n{i}") * pl.col(f"n{j}")).sum().alias(f"a{i}_{j}")
          for i in range(k) for j in range(i, k)],
        *[(pl.col(f"n{i}") * pl.col("delta")).sum().alias(f"b{i}") for i in range(k)],
    ).row(0, named=True)

    ata = [[sums[f"a{min(i, j)}_{max(i, j)}"] for j in range(k)] for i in range(k)]
    atb = [sums[f"b{i}"] for i in range(k)]
    solution = _solve(ata, atb)
    if solution is None:
        return {}

    # Check each answer against the precursors that actually carry it. A single
    # median over the whole library is no check at all for a rare modification:
    # one carried by nine precursors out of 370,000 can be fitted at any mass
    # it likes and the median, dominated by the other 369,991, will not budge.
    predicted = pl.sum_horizontal([pl.col(f"n{i}") * solution[i] for i in range(k)])
    error = (pl.col("delta") - predicted).abs()
    residuals = frame.select(
        *[error.filter(pl.col(f"n{i}") > 0).median().alias(f"r{i}") for i in range(k)]
    ).row(0, named=True)
    return {
        name: solution[i] for i, name in enumerate(names)
        if residuals[f"r{i}"] is not None and residuals[f"r{i}"] <= MAX_MEDIAN_RESIDUAL
    }


def _annotation_names(modified: pl.Series) -> List[str]:
    """The distinct modification names in the sequences, without delimiters."""
    found = (
        modified.unique().str.extract_all(ANNOTATION_PATTERN)
        .explode(empty_as_null=False).drop_nulls().unique()
    )
    return sorted({annotation[1:-1].strip() for annotation in found.to_list()})


def _count_pattern(name: str) -> str:
    """Matches the annotation for *name* in either bracket style, and only as a
    whole annotation -- so "UniMod:4" does not also count "UniMod:40"."""
    escaped = re.escape(name)
    return rf"\({escaped}\)|\[{escaped}\]"


def _solve(matrix, vector) -> Optional[List[float]]:
    """Gauss-Jordan with partial pivoting. None if the system is singular.

    The system is one row per modification, so it is single digits square in
    every library we have seen; a dependency on numpy would not earn its keep.
    """
    k = len(vector)
    augmented = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(augmented[r][col]))
        if abs(augmented[pivot][col]) < 1e-9:
            return None
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        for row in range(k):
            if row == col:
                continue
            factor = augmented[row][col] / augmented[col][col]
            for c in range(col, k + 1):
                augmented[row][c] -= factor * augmented[col][c]
    return [augmented[i][k] / augmented[i][i] for i in range(k)]


def mass_conflicts(modified: pl.Series, charge: pl.Series, mz: pl.Series) -> int:
    """How many sequence-and-charge pairs appear at more than one mass.

    When a library carries several label channels under one set of annotation
    names, the identical modified sequence shows up once per channel, each at
    its own m/z. No single mass per modification exists to be found, and this
    is the difference between saying so and reporting an average of the two as
    though it meant something.
    """
    frame = pl.DataFrame({
        "modified": modified,
        "charge": charge.cast(pl.Float64, strict=False),
        "mz": mz.cast(pl.Float64, strict=False),
    }).drop_nulls().unique()
    if frame.is_empty():
        return 0
    return (
        frame.group_by("modified", "charge")
        .agg(pl.col("mz").n_unique().alias("masses"))
        .filter(pl.col("masses") > 1)
        .height
    )


def site_allows(sites: str, site: str) -> bool:
    """Does a tag's rules string permit this site? Lowercase n is the
    N-terminus; uppercase letters are residues, so N is asparagine."""
    if site == N_TERM:
        return N_TERM_RULE in sites
    return site in sites.replace(N_TERM_RULE, "")


def identify_tag(mass: Optional[float], site: Optional[str] = None) -> List[TagChannel]:
    """The tag channels that explain a modification of this mass.

    The mass does the identifying. The site only breaks ties, and only when
    there are any: 13C(6) weighs 6.020129 Da on lysine and on arginine alike,
    so by mass alone SILAC-K and SILAC-R are one answer -- but we can see which
    residue the annotation actually sits on, and a Lys label is never on an Arg.

    The site never *rejects* an otherwise unambiguous match. A library may put
    a label wherever it likes, and one of these does: H_DM_mod is spread over
    twenty-two different residues in the predicted libraries. Refusing to name
    it anywhere its definition did not anticipate would hide the thing the mod
    table exists to show.
    """
    if mass is None:
        return []
    matches = sorted(
        (c for c in TAG_CHANNELS if abs(c.mass - mass) <= MASS_TOLERANCE),
        key=lambda c: (c.tag, c.mass),
    )
    if site is None or len({c.tag for c in matches}) < 2:
        return matches
    consistent = [c for c in matches if site_allows(c.sites, site)]
    return consistent or matches


def tag_names(matches: List[TagChannel]) -> List[str]:
    """Just the TAG_OPTIONS names from a list of matched channels."""
    return sorted({channel.tag for channel in matches})
