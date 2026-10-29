"""What a spectral library holds, summarised: its precursors, its fragments and
its digest. Shown in the library details panel; everything here is read from
the file, and only what the file actually has is reported -- a library with no
c or z ions has no row for them, one with no ion mobility says so.

Unlike the rest of the analysis this needs fragment rows, so it reads the file
lazily and lets polars stream the aggregations rather than holding every
fragment in memory at once.
"""
from typing import Dict, List, Optional

import polars as pl

FRAGMENT_ALIASES = {
    "type": ["Fragment.Type", "FragmentType"],
    "number": ["Fragment.Series.Number", "FragmentSeriesNumber"],
    "charge": ["Fragment.Charge", "FragmentCharge"],
    "loss": ["Fragment.Loss.Type", "FragmentLossType"],
    "mz": ["Product.Mz", "ProductMz", "FragmentMz"],
}
ION_MOBILITY_ALIASES = ["IM", "IonMobility"]

_DECOY = "__decoy"


def _pick(available: List[str], names: List[str]) -> Optional[str]:
    return next((n for n in names if n in available), None)


def _percent(count: int, total: int) -> float:
    return round(100 * count / total, 2) if total else 0.0


def _span(series: pl.Series, digits: int) -> Optional[List[float]]:
    series = series.drop_nulls()
    if series.is_empty():
        return None
    return [round(float(series.min()), digits), round(float(series.max()), digits)]


def compute(lf: pl.LazyFrame, available: List[str], modified: str, charge: str,
            stripped: Optional[str], precursor_mz: Optional[str],
            decoy: Optional[pl.Expr], annotation_pattern: str):
    """The precursor and fragment sections, and the target peptides the digest
    section is worked out from.

    *decoy* marks decoy rows, or is None when the library has no decoy column;
    decoys are counted and otherwise left out of every figure.
    """
    fragment = {key: _pick(available, names) for key, names in FRAGMENT_ALIASES.items()}
    mobility = _pick(available, ION_MOBILITY_ALIASES)
    key = [modified, charge]
    peptide = (pl.col(stripped) if stripped
               else pl.col(modified).str.replace_all(annotation_pattern, "")).alias("__peptide")

    wanted = list(dict.fromkeys(c for c in (modified, charge, precursor_mz, mobility, *fragment.values()) if c))
    rows = lf.with_columns(
        (decoy if decoy is not None else pl.lit(False)).alias(_DECOY), peptide,
    ).select(*wanted, "__peptide", _DECOY)
    targets = rows.filter(~pl.col(_DECOY))

    queries = {
        "decoys": rows.filter(pl.col(_DECOY)).select(key).unique().select(pl.len()),
        "precursors": targets.select(
            *[c for c in (modified, charge, precursor_mz, mobility) if c], "__peptide"
        ).unique(subset=key, keep="any"),
    }
    if fragment["type"]:
        queries["per_precursor"] = targets.group_by(key).agg(pl.len().alias("n"))
        queries["types"] = targets.group_by(fragment["type"]).agg(
            pl.len().alias("rows"),
            *([pl.col(fragment["number"]).min().alias("first"),
               pl.col(fragment["number"]).max().alias("last")] if fragment["number"] else []),
        )
        for part in ("charge", "loss"):
            if fragment[part]:
                queries[part] = targets.select(pl.col(fragment[part]).unique())
        if fragment["mz"]:
            queries["mz"] = targets.select(
                pl.col(fragment["mz"]).min().alias("low"), pl.col(fragment["mz"]).max().alias("high"))

    names = list(queries)
    results = dict(zip(names, pl.collect_all([queries[n] for n in names], engine="streaming")))

    precursors = results["precursors"]
    peptides = precursors["__peptide"].drop_nulls().unique()
    lengths = peptides.str.len_chars()
    # Some libraries store the charge as a float; "2.0" is still 2+
    charges = precursors[charge].cast(pl.Int64, strict=False).value_counts().sort(charge)

    mobility_values = None
    if mobility:
        # DIA-NN writes 0 for "no ion mobility", so a zero is an absence, not a value
        values = precursors[mobility].cast(pl.Float64, strict=False)
        mobility_values = _span(values.filter(values != 0), 3)

    section = {
        "precursors": {
            "count": precursors.height,
            "charges": {str(c): _percent(n, precursors.height) for c, n in charges.iter_rows()},
            "mz": _span(precursors[precursor_mz].cast(pl.Float64, strict=False), 2) if precursor_mz else None,
            "length": ({"min": int(lengths.min()), "median": float(lengths.median()), "max": int(lengths.max())}
                       if not lengths.is_empty() else None),
            "ion_mobility": mobility_values,
            "decoys": int(results["decoys"].item()),
        },
        "fragments": _fragments(results, fragment, precursors.height) if fragment["type"] else None,
    }
    return section, peptides


def _fragments(results, fragment, precursors: int) -> Dict:
    per = results["per_precursor"]["n"]
    types = results["types"].sort(fragment["type"])
    return {
        "per_precursor": {"min": int(per.min()), "median": float(per.median()),
                          "mean": round(float(per.mean()), 2), "max": int(per.max())},
        # Only the ion types the library has. The mean is over every precursor,
        # so b and y means add up to the fragments-per-precursor mean.
        "types": [
            {"type": str(row[fragment["type"]]),
             "mean": round(row["rows"] / precursors, 2) if precursors else 0.0,
             "first": row.get("first"), "last": row.get("last")}
            for row in types.iter_rows(named=True)
        ],
        "charges": (sorted(int(c) for c in results["charge"].to_series().drop_nulls())
                    if "charge" in results else None),
        "losses": (sorted(str(x) for x in results["loss"].to_series().drop_nulls())
                   if "loss" in results else None),
        "mz": ([round(float(results["mz"]["low"].item()), 2), round(float(results["mz"]["high"].item()), 2)]
               if "mz" in results else None),
    }


def digest(peptides: pl.Series, protease: str, residues, side: str) -> Dict:
    """Which residues the peptides were cut at, and how many cuts were missed.

    For a C-terminal cutter (trypsin) the cut residue ends the peptide; for an
    N-terminal one (AspN) it starts it. Every site of the protease's residues
    inside the peptide counts as a missed cleavage, KP and RP included.
    Nothing is excluded: a peptide from a protein's C-terminus that does not end
    in K or R is simply counted under "other", and the reader can judge.
    """
    residues = sorted(residues)
    total = peptides.len()
    end = peptides.str.slice(-1, 1) if side == "C" else peptides.str.slice(0, 1)
    shares = {r: _percent(int((end == r).sum()), total) for r in residues}
    inside = peptides.str.head(-1) if side == "C" else peptides.str.tail(-1)
    missed = inside.str.count_matches("[" + "".join(residues) + "]")
    counts = missed.value_counts().sort(missed.name)
    return {
        "protease": protease,
        "terminus": side,
        "residues": shares,
        "other": round(100 - sum(shares.values()), 2) if total else 0.0,
        "missed_cleavages": {str(k): _percent(n, total) for k, n in counts.iter_rows()},
    }
