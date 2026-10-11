"""Upload only the rights-cleared chart projection to Cloudflare Workers KV.

Credentials are read from a private file after model execution, never exported
to worker environments or embedded in the site. No resource or paid plan is
created here. Configure the existing Pages project's TSFM_DASHBOARD binding.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import ssl
from urllib.request import Request, urlopen

import certifi

from local_run import private_path, read_runtime_env
from tsfm_live.ledger import canonical_bytes


KEY = "hourly-dashboard"
ENV_KEYS = {"CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_KV_NAMESPACE_ID", "CLOUDFLARE_API_TOKEN"}


def publish_dashboard(view, *, root, env_file, opener=urlopen):
    """Send a bounded public hourly snapshot; report no credentials on errors."""
    if (view.get("frequency") != "1h" or view.get("mode") != "local_zero_shot"
            or view.get("public_ledger_eligible") is not False):
        raise ValueError("invalid_public_dashboard")
    rows = view.get("indicators")
    if not isinstance(rows, list):
        raise ValueError("invalid_public_indicators")
    # Explicit provider/rights gate also protects standalone calls to this helper.
    for row in rows:
        if (row.get("public_export") is not True or row.get("license_id") != "CC-BY-NC-4.0"
                or row.get("source_status", {}).get("source_id") != "coinmetrics_hourly"):
            raise ValueError("source_not_authorized_for_public_upload")
    body = canonical_bytes(view)
    if len(body) > 2_000_000:
        raise ValueError("public_dashboard_too_large")
    values = read_runtime_env(private_path(Path(env_file), Path(root).resolve()), ENV_KEYS)
    if set(values) != ENV_KEYS:
        raise ValueError("incomplete_publish_configuration")
    account, namespace = values["CLOUDFLARE_ACCOUNT_ID"], values["CLOUDFLARE_KV_NAMESPACE_ID"]
    if not all(re.fullmatch(r"[a-fA-F0-9]{32}", item) for item in (account, namespace)):
        raise ValueError("invalid_cloudflare_identifier")
    request = Request(f"https://api.cloudflare.com/client/v4/accounts/{account}/storage/kv/namespaces/{namespace}/values/{KEY}",
                      data=body, method="PUT", headers={
                          "Authorization": "Bearer " + values["CLOUDFLARE_API_TOKEN"],
                          "Content-Type": "application/json", "User-Agent": "TSFM-Live/0.1"})
    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with opener(request, timeout=30, context=context) as response:
            result = json.loads(response.read(65536))
        if result.get("success") is not True:
            raise ValueError("cloudflare_upload_rejected")
    except Exception:
        # Provider exceptions may contain request headers. Keep them out of logs.
        raise RuntimeError("public_dashboard_upload_failed") from None
    return {"destination": "cloudflare_kv", "key": KEY, "bytes": len(body),
            "run_id": view.get("run_id"), "indicator_count": len(rows)}
