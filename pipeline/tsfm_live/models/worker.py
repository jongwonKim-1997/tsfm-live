"""One JSON request per process, suitable for an isolated pinned environment.

Parent owns the hard process deadline. Package messages are redirected to stderr;
stdout contains exactly one JSON response. No exception falls back to a baseline.
"""
from contextlib import redirect_stdout
from dataclasses import asdict
import json
import os
import sys
import traceback


def main():
    try:
        request = json.load(sys.stdin)
        if request["config"].get("local_files_only", True):
            # Some vendor convenience loaders make auxiliary Hub probes without
            # forwarding local_files_only. Enforce offline mode before imports.
            os.environ["HF_HUB_OFFLINE"] = "1"
        with redirect_stdout(sys.stderr):
            import numpy as np
            from . import create_entrant
            from .base import checked_horizon
            horizon = checked_horizon(request.get("horizon", 1))
            config = dict(request["config"])
            interval = request.get("interval_seconds", 86400)
            if isinstance(interval, bool) or not isinstance(interval, int) or interval not in {3600, 86400}:
                raise ValueError("unsupported_time_interval")
            config["time_interval_seconds"] = interval
            adapter = create_entrant(config)
            options = {} if horizon == 1 else {"horizon": horizon}
            result = adapter.predict(
                np.asarray(request["context"], dtype=float),
                request["quantiles"], int(request["seed"]), **options,
            )
        response = {"ok": True, "output": asdict(result)}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        response = {"ok": False, "output": None, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(response, allow_nan=False, separators=(",", ":")))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
