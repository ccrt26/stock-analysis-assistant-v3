from __future__ import annotations

import hashlib

import pandas as pd


def _stable_unit_interval(*parts: object) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64)


def rank_by_column(
    frame: pd.DataFrame,
    column: str,
    *,
    dataset_version: str,
    ascending: bool = False,
    seed: int = 20260817,
) -> pd.DataFrame:
    """Rank within formation dates, using a stable hash for score ties."""
    ranked = frame.copy()
    ranked["_tie_key"] = [
        _stable_unit_interval(seed, row.formation_date, row.ts_code, dataset_version)
        for row in ranked[["formation_date", "ts_code"]].itertuples(index=False)
    ]
    ranked = ranked.sort_values(
        ["formation_date", column, "_tie_key"],
        ascending=[True, ascending, True],
        kind="mergesort",
    )
    ranked["rank"] = ranked.groupby("formation_date", sort=False).cumcount() + 1
    return ranked.drop(columns="_tie_key").reset_index(drop=True)


def rank_random(
    frame: pd.DataFrame,
    *,
    draw: int,
    seed: int = 20260817,
    dataset_version: str = "selection-lab-v1",
) -> pd.DataFrame:
    """Produce a deterministic random-ranking baseline for one draw."""
    randomized = frame.copy()
    randomized["score"] = [
        _stable_unit_interval(seed, draw, dataset_version, row.formation_date, row.ts_code)
        for row in randomized[["formation_date", "ts_code"]].itertuples(index=False)
    ]
    return rank_by_column(
        randomized,
        "score",
        dataset_version=f"{dataset_version}:random:{seed}:{draw}",
    )
