"""Bronze: land source files as-is (all values kept as raw strings) plus lineage columns.

Idempotent: a file whose content hash is already in the manifest is skipped, so re-running is safe.
"""
import hashlib
import json
import logging
import os
from pathlib import Path

import pandas as pd

from healthcare_models.schemas import SOURCE_FILES

log = logging.getLogger(__name__)

READERS = {
    ".csv": lambda p: pd.read_csv(p, dtype=str, keep_default_na=False),
    ".json": lambda p: pd.DataFrame(json.loads(p.read_text())),
    ".parquet": pd.read_parquet,
}


def write_parquet(df: pd.DataFrame, target: Path) -> None:
    """Write via temp file + rename so a crash never leaves a half-written file behind."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, target)


def read_bronze(data_dir, table: str) -> pd.DataFrame:
    files = sorted((Path(data_dir) / "bronze" / table).glob("*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True) if files else pd.DataFrame()


def ingest(landing_dir, data_dir, source_system: str = "synthetic") -> dict[str, int]:
    landing_dir, data_dir = Path(landing_dir), Path(data_dir)
    manifest_path = data_dir / "bronze" / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    new_rows = {table: 0 for table in SOURCE_FILES}

    for table, filename in SOURCE_FILES.items():
        stem = Path(filename).stem
        for path in sorted(p for p in landing_dir.rglob(f"{stem}.*") if p.suffix in READERS):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in manifest:
                log.info("skip already ingested file", extra={"ctx": {"file": str(path), "table": table}})
                continue
            df = READERS[path.suffix](path)
            df["_source_file"] = str(path.relative_to(landing_dir))
            df["_source_system"] = source_system
            df["_batch_id"] = digest[:16]
            df["_ingested_at"] = pd.Timestamp.now(tz="UTC")
            write_parquet(df, data_dir / "bronze" / table / f"{digest[:16]}.parquet")
            manifest[digest] = {"table": table, "file": str(path), "rows": len(df), "ingested_at": str(df["_ingested_at"].iloc[0])}
            manifest_path.write_text(json.dumps(manifest, indent=1))
            new_rows[table] += len(df)
            log.info("ingested file", extra={"ctx": {"file": str(path), "table": table, "rows": len(df)}})
    return new_rows
