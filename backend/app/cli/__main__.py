"""支持 `python -m app.cli ...` 入口."""
from __future__ import annotations

from . import main

if __name__ == "__main__":
    raise SystemExit(main())
