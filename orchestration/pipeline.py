"""Local orchestrator: landing -> Bronze -> Silver -> Gold, with retries, run records and alerts.

Mirrors the Step Functions state machine planned for Phase 2.
Usage: python -m orchestration.pipeline [--generate N] [--seed S] [--data-dir PATH]
"""
import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

import pandas as pd

from config import settings
from ingestion import batch
from ingestion.sources import synthetic
from processing import gold, silver

log = logging.getLogger("orchestration")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": pd.Timestamp.now(tz="UTC").isoformat(), "level": record.levelname,
            "logger": record.name, "msg": record.getMessage(), **getattr(record, "ctx", {}),
        }, default=str)


def with_retry(name, fn, attempts: int = 3, base_delay: float = 1.0):
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except OSError as exc:  # transient I/O (locked file, network FS); anything else is a bug: fail fast
            if attempt == attempts:
                raise
            log.warning("step failed, retrying", extra={"ctx": {"step": name, "attempt": attempt, "error": repr(exc)}})
            time.sleep(base_delay * 2 ** (attempt - 1))


def alert(data_dir: Path, run_id: str, message: str, details=None) -> None:
    # shortcut: alerts go to a local JSONL file + log; Phase 2 publishes to SNS
    entry = {"ts": pd.Timestamp.now(tz="UTC").isoformat(), "run_id": run_id, "message": message, "details": details}
    with open(data_dir / "alerts.jsonl", "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    log.error(message, extra={"ctx": {"run_id": run_id, "details": details}})


def run(data_dir=None, generate_patients: int | None = None, seed: int = 42) -> dict:
    data_dir = Path(data_dir or settings.DATA_DIR)
    landing = data_dir / "landing"
    (data_dir / "runs").mkdir(parents=True, exist_ok=True)
    run_id = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    record = {"run_id": run_id, "started_at": pd.Timestamp.now(tz="UTC").isoformat(), "status": "running", "steps": []}

    steps = []
    if generate_patients:
        steps.append(("generate", lambda: synthetic.generate(landing, generate_patients, seed)))
    steps += [
        ("bronze", lambda: batch.ingest(landing, data_dir)),
        ("silver", lambda: silver.build(data_dir)),
        ("gold", lambda: gold.build(data_dir, settings.pseudonymization_key())),
    ]
    t_run = time.perf_counter()
    try:
        for name, fn in steps:
            t0 = time.perf_counter()
            try:
                result = with_retry(name, fn)
            except Exception as exc:
                record["steps"].append({"step": name, "status": "failed", "seconds": round(time.perf_counter() - t0, 3), "error": repr(exc)})
                raise
            record["steps"].append({"step": name, "status": "succeeded", "seconds": round(time.perf_counter() - t0, 3), "result": result})
            log.info("step succeeded", extra={"ctx": {"run_id": run_id, "step": name}})

        reports = next(s["result"] for s in record["steps"] if s["step"] == "silver")
        breaches = {t: r["quality_score"] for t, r in reports.items() if r["quality_score"] < settings.QUALITY_THRESHOLD}
        record["status"] = "succeeded_with_quality_alerts" if breaches else "succeeded"
        if breaches:
            alert(data_dir, run_id, "data quality below threshold", {"threshold": settings.QUALITY_THRESHOLD, "scores": breaches})
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = repr(exc)
        alert(data_dir, run_id, "pipeline run failed", repr(exc))
        raise
    finally:
        record["finished_at"] = pd.Timestamp.now(tz="UTC").isoformat()
        record["duration_seconds"] = round(time.perf_counter() - t_run, 3)
        (data_dir / "runs" / f"{run_id}.json").write_text(json.dumps(record, indent=1, default=str))
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the local healthcare data pipeline")
    parser.add_argument("--generate", type=int, metavar="N", help="generate N synthetic patients into landing first")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        record = run(args.data_dir, args.generate, args.seed)
    except Exception:
        return 1
    print(json.dumps({"run_id": record["run_id"], "status": record["status"], "seconds": record["duration_seconds"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
