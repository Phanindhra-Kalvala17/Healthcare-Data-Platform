"""Reusable validation helpers: rule evaluation, quarantine split, deduplication and quality reports."""
import pandas as pd


def missing(df: pd.DataFrame, column: str) -> pd.Series:
    col = df[column] if column in df else pd.Series(pd.NA, index=df.index)
    return col.isna() | (col.astype("string").str.strip() == "")


def split_valid(df: pd.DataFrame, checks: list[tuple[str, pd.Series]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """checks: (reason, bad_mask) pairs in priority order. Each rejected row keeps its first failing reason."""
    reason = pd.Series(pd.NA, index=df.index, dtype="string")
    for name, bad in checks:
        reason = reason.mask(reason.isna() & bad.fillna(True).astype(bool), name)
    rejected = df[reason.notna()].assign(_reject_reason=reason[reason.notna()])
    return df[reason.isna()], rejected


def latest_per_key(df: pd.DataFrame, key: str) -> tuple[pd.DataFrame, int]:
    """Keep the most recently ingested version of each record, so corrections in later batches win."""
    deduped = df.sort_values("_ingested_at", kind="stable").drop_duplicates(key, keep="last")
    return deduped, len(df) - len(deduped)


def table_report(table: str, raw: pd.DataFrame, valid: pd.DataFrame, rejected: pd.DataFrame,
                 duplicates: int, required: list[str]) -> dict:
    rows_in = len(raw)
    return {
        "table": table,
        "rows_in": rows_in,
        "rows_valid": len(valid),
        "rows_rejected": len(rejected),
        "duplicates_removed": duplicates,
        "reject_reasons": {str(k): int(v) for k, v in rejected["_reject_reason"].value_counts().items()},
        "missing_pct": {c: round(100 * float(missing(raw, c).mean()), 2) if rows_in else 0.0 for c in required},
        "quality_score": round(1 - len(rejected) / rows_in, 4) if rows_in else 1.0,
    }
