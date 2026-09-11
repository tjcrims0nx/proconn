"""Legacy shim - delegates to clean enterprise app. Prefer: python app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from switch2mod.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
