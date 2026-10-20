"""Runtime settings. Everything is overridable through environment variables (or a local .env)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    # shortcut: minimal KEY=VALUE parser without quoting/escapes; switch to python-dotenv if .env grows
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

DATA_DIR = Path(os.environ.get("HDP_DATA_DIR", ROOT / "data"))
QUALITY_THRESHOLD = float(os.environ.get("HDP_QUALITY_THRESHOLD", "0.85"))
MIN_CELL_SIZE = 5  # aggregates below this are suppressed to limit re-identification


def pseudonymization_key() -> bytes:
    key = os.environ.get("HDP_PSEUDONYMIZATION_KEY", "")
    if len(key) < 32:
        raise RuntimeError(
            "HDP_PSEUDONYMIZATION_KEY must be set to a secret of at least 32 characters "
            '(generate one with: python -c "import secrets; print(secrets.token_hex(32))")'
        )
    return key.encode()
