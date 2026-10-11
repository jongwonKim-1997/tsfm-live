import copy
import io
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_dashboard import publish_dashboard


VIEW = {"mode": "local_zero_shot", "frequency": "1h", "public_ledger_eligible": False,
        "run_id": "test", "indicators": [{"id": "btc", "public_export": True,
        "license_id": "CC-BY-NC-4.0", "source_status": {"source_id": "coinmetrics_hourly"}}]}


def config(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    path = tmp_path / "private.env"
    path.write_text("CLOUDFLARE_ACCOUNT_ID=" + "a" * 32 + "\nCLOUDFLARE_KV_NAMESPACE_ID=" + "b" * 32
                    + "\nCLOUDFLARE_API_TOKEN=secret-fixture\n")
    return root, path


def test_only_public_projection_is_sent_to_configured_kv(tmp_path):
    root, path = config(tmp_path)
    requests = []
    def opener(request, **kwargs):
        requests.append(request)
        assert kwargs["timeout"] == 30
        return io.BytesIO(b'{"success":true}')
    receipt = publish_dashboard(VIEW, root=root, env_file=path, opener=opener)
    assert json.loads(requests[0].data) == VIEW
    assert requests[0].method == "PUT"
    assert requests[0].get_header("Authorization") == "Bearer secret-fixture"
    assert "secret-fixture" not in json.dumps(receipt)


@pytest.mark.parametrize("mutation", ["upbit", "no_license", "private", "daily"])
def test_ineligible_payload_never_reaches_network(tmp_path, mutation):
    view = copy.deepcopy(VIEW)
    if mutation == "upbit":
        view["indicators"][0]["source_status"]["source_id"] = "upbit_hourly"
    elif mutation == "no_license":
        view["indicators"][0].pop("license_id")
    elif mutation == "private":
        view["indicators"][0]["public_export"] = False
    else:
        view["frequency"] = "1d"
    with pytest.raises(ValueError):
        publish_dashboard(view, root=tmp_path, env_file=tmp_path / "missing", opener=lambda *a, **kw: pytest.fail())


def test_upload_errors_do_not_leak_request_credentials(tmp_path):
    root, path = config(tmp_path)
    def broken(*args, **kwargs):
        raise RuntimeError("Authorization: secret-fixture")
    with pytest.raises(RuntimeError, match="^public_dashboard_upload_failed$") as error:
        publish_dashboard(VIEW, root=root, env_file=path, opener=broken)
    assert "secret-fixture" not in str(error.value)
