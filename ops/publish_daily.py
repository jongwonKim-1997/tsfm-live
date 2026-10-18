"""Bounded KV upload and public readback for the commercial-source daily board."""

import json
import re
import ssl
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi
from local_run import private_path, read_runtime_env
from tsfm_live.daily_public import MODEL_IDS, indicator_configs
from tsfm_live.ledger import canonical_bytes

ENV_KEYS = {
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_KV_NAMESPACE_ID",
    "CLOUDFLARE_API_TOKEN",
}
PUBLIC_URL = "https://tsfm-live.pages.dev/api/v1/daily_dashboard.json"
USER_AGENT = "TSFM-Live-DailyPublisher/1.0 (+https://tsfm-live.pages.dev)"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "redirect_refused", headers, fp)


def validate(view):
    if (
        view.get("schema_version") != "daily-public-v1"
        or view.get("device") != "cuda"
        or view.get("frequency") != "1d"
        or view.get("issue_frequency", "1d") not in {"1d", "1h"}
        or view.get("inference_mode") != "zero_shot"
        or view.get("input_basis") != "own_daily_levels_only"
        or view.get("public_ledger_eligible") is not False
    ):
        raise ValueError("invalid_daily_projection")
    configs = {r["id"]: r for r in indicator_configs()}
    rows = view.get("indicators", [])
    if len(rows) != len(configs) or {r["id"] for r in rows} != set(configs):
        raise ValueError("unapproved_indicators")
    for row in rows:
        cfg = configs[row["id"]]
        if (
            row.get("public_export") is not True
            or row.get("license_id") != cfg["license_id"]
            or row.get("source_id") != cfg["source"]["adapter"]
        ):
            raise ValueError("unapproved_source")
        for key in ("forecasts", "previous_forecasts", "forecast_history"):
            for forecast in row.get(key, []):
                if (
                    forecast.get("model_id") not in MODEL_IDS
                    or forecast.get("model_license") != "apache-2.0"
                ):
                    raise ValueError("unapproved_model")

    def scan(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if any(
                    s in k.lower() for s in ("token", "secret", "password", "api_key")
                ) or k.lower() in {
                    "context",
                    "raw_evidence",
                    "raw_file",
                    "env_file",
                    "cache_dir",
                    "authorization",
                }:
                    raise ValueError("private_field")
                scan(v)
        elif isinstance(value, list):
            for v in value:
                scan(v)

    scan(view)
    body = canonical_bytes(view)
    if len(body) > 2_000_000:
        raise ValueError("payload_too_large")
    return body


def publish_daily(view, *, root, env_file, opener=None, sleep=time.sleep):
    body = validate(view)
    values = read_runtime_env(
        private_path(Path(env_file), Path(root).resolve()), ENV_KEYS
    )
    if set(values) != ENV_KEYS:
        raise ValueError("incomplete_publishing_configuration")
    account, namespace, token = (
        values[k]
        for k in (
            "CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_KV_NAMESPACE_ID",
            "CLOUDFLARE_API_TOKEN",
        )
    )
    if not all(
        re.fullmatch(r"[a-fA-F0-9]{32}", v) for v in (account, namespace)
    ) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]{1,4096}", token):
        raise ValueError("invalid_publishing_configuration")
    open_request = (
        opener
        or build_opener(
            HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
            NoRedirect(),
        ).open
    )
    request = Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account}/storage/kv/namespaces/{namespace}/values/daily-dashboard",
        data=body,
        method="PUT",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with open_request(request, timeout=30) as response:
            raw = response.read(65537)
            if (
                not 200 <= response.status < 300
                or len(raw) > 65536
                or json.loads(raw).get("success") is not True
            ):
                raise ValueError("upload_rejected")
    except Exception:  # noqa: BLE001 -- redact all provider errors that may contain bearer credentials
        raise RuntimeError("daily_upload_failed") from None
    verified = False
    # No authorization header is ever sent to the public readback endpoint.
    for attempt in range(4):
        if attempt:
            sleep(25)
        try:
            with open_request(
                Request(
                    PUBLIC_URL + "?run=" + view["run_id"],
                    headers={
                        "Cache-Control": "no-cache",
                        "User-Agent": USER_AGENT,
                        "Accept": "application/json",
                    },
                ),
                timeout=20,
            ) as response:
                raw = response.read(2_000_001)
                if response.status == 200 and len(raw) <= 2_000_000:
                    verified = canonical_bytes(json.loads(raw)) == body
                    if verified:
                        break
        except (OSError, ValueError, TypeError):
            verified = False
    return {
        "uploaded": True,
        "readback_verified": verified,
        "run_id": view["run_id"],
        "bytes": len(body),
        "key": "daily-dashboard",
    }
