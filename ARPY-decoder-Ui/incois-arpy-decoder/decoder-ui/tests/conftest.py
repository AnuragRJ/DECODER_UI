"""Suite-wide isolation of runtime state.

``service/event_bus.py`` resolves ``DATA_DIR`` **once, at import time**, from
``ARGO_UI_DATA_DIR`` (falling back to the repository's ``decoder-ui/data``). Several
test modules set that variable themselves before importing the service, which works
only while the module that happens to be imported *first* is one of them: pytest
imports test modules in filesystem order, so a module that imports the service
without isolating (or any collection-order change) hands the whole session the
repository's runtime directory. The observed consequence was real: test runs
appended forward-test records for synthetic floats into
``data/fleet_status/prediction_forward_log.jsonl``, a file that a deployment started
without ``ARGO_UI_DATA_DIR`` would serve as its own history.

Setting the variable here - conftest is imported before any test module - makes the
isolation independent of collection order. ``setdefault`` keeps an explicit override
honoured when someone deliberately points a run at a real data directory.
"""

from __future__ import annotations

import os
import tempfile
import shutil

if not os.environ.get("ARGO_UI_DATA_DIR"):
    _TMP = tempfile.mkdtemp(prefix="decoder-ui-suite-data-")
    os.environ["ARGO_UI_DATA_DIR"] = _TMP

    def _cleanup() -> None:  # pragma: no cover - best-effort housekeeping
        shutil.rmtree(os.environ.get("ARGO_UI_DATA_DIR", ""), ignore_errors=True)

    import atexit

    atexit.register(_cleanup)
