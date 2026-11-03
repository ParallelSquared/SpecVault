"""What a spectral library looks like on disk, for tests that need one.

In one place because the catalog's idea of a library is one thing, and it
turned out to be spread across nine fixtures: when "has fragment rows" became
part of the definition, every one of them was writing something the catalog
no longer accepts.

A library has one row per *fragment*, repeating the precursor columns -- that
repetition is what makes it spectral, and what tells it apart from a peptide
list or a search report, which describe the same precursors and stop there.
"""
import pathlib
import re

# No Precursor.Mz: it is optional, and a made-up constant for every precursor
# is worse than leaving it out -- the modification masses are solved from it,
# so a fake one makes every library warn that they could not be resolved.
# Tests about m/z write their own file (see test_library_stats.py).
COLUMNS = (
    "Modified.Sequence", "Stripped.Sequence", "Protein.Group", "Precursor.Charge",
    "Fragment.Type", "Fragment.Series.Number", "Fragment.Charge", "Product.Mz",
)

# Two per precursor: enough to be a spectrum, few enough to read in a diff.
FRAGMENTS = (("y", 3, 1, 401.2), ("b", 2, 1, 251.1))

# Modifications as libraries write them: "(UniMod:4)" or "[+57.0215]"
_ANNOTATION = re.compile(r"\([^()]*\)|\[[^\[\]]*\]")


def strip(sequence: str) -> str:
    return _ANNOTATION.sub("", sequence)


def text(*sequences, proteins=None, charges=None) -> str:
    """A library holding one precursor per sequence.

    *proteins* and *charges* line up with *sequences* where given, so a test
    that cares about protein counts or charge states can say so; otherwise
    each precursor gets a protein of its own.
    """
    sequences = sequences or ("PEPTIDK",)
    lines = ["\t".join(COLUMNS)]
    for i, modified in enumerate(sequences):
        protein = proteins[i] if proteins else f"P{i + 1}"
        charge = charges[i] if charges else 2
        for kind, number, fragment_charge, product_mz in FRAGMENTS:
            lines.append("\t".join(str(value) for value in (
                modified, strip(modified), protein, charge,
                kind, number, fragment_charge, product_mz,
            )))
    return "\n".join(lines) + "\n"


def write(path, *sequences, **kwargs) -> pathlib.Path:
    """Write one, making the folder if it is not there."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text(*sequences, **kwargs), encoding="utf-8")
    return path
