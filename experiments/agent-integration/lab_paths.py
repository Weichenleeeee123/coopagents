"""Repository-relative locations for retained, untracked experiment data."""
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPOSITORY_ROOT / ".local" / "agent-integration"
EVIDENCE_ROOT = DATA_ROOT / "evidence"
RUNTIME_ROOT = DATA_ROOT / "runtime"
