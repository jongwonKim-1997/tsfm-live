"""Read the public health JSON at 09:30 KST; exit nonzero on stale state."""
from datetime import datetime
import json
import os
from zoneinfo import ZoneInfo

import requests


def main():
    expected = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    url = os.environ["TSFM_PUBLIC_ORIGIN"].rstrip("/") + "/api/v1/status.json"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    status = response.json()
    if status.get("as_of") != expected:
        print(json.dumps({"severity": "ERROR", "event": "stale_public_status",
                          "expected": expected, "observed": status.get("as_of")}))
        return 1
    print(json.dumps({"event": "public_status_current", "as_of": expected}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
