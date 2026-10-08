from datetime import date

import numpy as np
import pandas as pd

from tsfm_live.calendars import session_closes
from tsfm_live.shadow import simulate


def test_shadow_is_partial_no_tsfms_and_no_lookahead(tmp_path):
    cfg = {"id": "fixture", "enabled": True, "calendar": "CRYPTO_UTC23",
           "target_transform": "log_return_pct", "min_history": 30}
    closes = session_closes(cfg, date(2025, 1, 1), date(2026, 1, 5))
    values = 100 * np.exp(np.sin(np.arange(len(closes)) / 10) / 10)
    frame = pd.DataFrame({"close_ts": closes, "value": values, "published_ts": None})
    result = simulate([cfg], {"fixture": frame}, date(2026, 1, 5), days=3)
    assert result["run_count"] == 3
    assert result["indicators"][0]["counts"]["scored"] == 3
    assert result["tsfm_models_executed"] == [] and not result["is_live"]
    assert not result["ledger_written"] and not result["pi_scale_validated"]
    assert "NOT A LIVE RECORD" in result["warning"]
    # The median of both zero-mean baselines stays zero irrespective of actuals;
    # loss responds to a changed outcome, but the diagnostic writes no files.
    assert result["indicators"][0]["baseline_metrics"]["rw0"]["n"] == 3
    assert list(tmp_path.iterdir()) == []


def test_shadow_reports_disabled_and_missing_sources():
    base = {"id": "missing", "enabled": True, "calendar": "CRYPTO_UTC23",
            "target_transform": "log_return_pct", "min_history": 30}
    result = simulate([base, {**base, "id": "disabled", "enabled": False}], {}, date(2026, 1, 5), days=2)
    assert result["indicators"][0]["counts"] == {"source_error": 2}
    assert result["indicators"][1]["counts"] == {"disabled": 2}
    assert result["indicators"][0]["baseline_metrics"]["rw0"]["mean_crps"] is None
