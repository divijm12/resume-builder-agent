"""Pytest configuration -- puts agents/ and review/backend/ on sys.path so
every test file can just `import tailor`, `import cover_letter`, etc.
without repeating path-manipulation boilerplate. Auto-loaded by pytest,
no explicit import needed anywhere."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
sys.path.insert(0, str(REPO_ROOT / "agents"))
sys.path.insert(0, str(REPO_ROOT / "review" / "backend"))
