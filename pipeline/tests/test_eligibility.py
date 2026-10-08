from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tsfm_live.calendars import session_bounds, session_closes
from tsfm_live.eligibility import confirmed_history, evaluate_eligibility
from tsfm_live.transforms import inverse_transform, transform

RUN = datetime.fromisoformat("2026-10-07T23:10:00+00:00")
CFG = {"calendar": "ECB", "enabled": True, "target_transform": "log_return_pct", "min_history": 3}


def history(cfg=CFG, run=RUN):
    previous, _ = session_bounds(cfg, run)
    dates = session_closes(cfg, previous.date() - timedelta(days=10), previous.date())[-5:]
    return pd.DataFrame({"close_ts": dates, "value": np.arange(len(dates)) + 100., "published_ts": None})


def test_eligible_and_requires_latest_confirmed_close():
    h = history()
    assert evaluate_eligibility(CFG, h, RUN)["eligible"]
    result = evaluate_eligibility(CFG, h.iloc[:-1], RUN)
    assert not result["eligible"] and result["skip_reason"] == "source_lag"


def test_late_publication_cannot_enter_context():
    h = history()
    h.loc[h.index[-1], "published_ts"] = RUN + timedelta(seconds=1)
    assert len(confirmed_history(h, RUN)) == len(h) - 1
    assert evaluate_eligibility(CFG, h, RUN)["skip_reason"] == "source_lag"


def test_future_and_exact_run_closes_excluded():
    h = history()
    h = pd.concat([h, pd.DataFrame({"close_ts": [RUN, RUN + timedelta(hours=1)],
                                  "value": [999999., 999999.], "published_ts": [None, None]})])
    assert confirmed_history(h, RUN)["value"].max() < 1000
    assert evaluate_eligibility(CFG, h, RUN)["eligible"]


def test_minimum_counts_changes_and_gaps_are_not_bridged():
    h = history()
    assert evaluate_eligibility({**CFG, "min_history": len(h)}, h, RUN)["skip_reason"] == "insufficient_history"
    assert evaluate_eligibility(CFG, h.drop(h.index[-2]), RUN)["skip_reason"] == "history_gap"


@pytest.mark.parametrize("mutation", ["nan", "negative", "duplicate", "unsorted", "preliminary", "naive"])
def test_bad_history_fails_closed(mutation):
    h = history()
    if mutation == "nan":
        h.loc[0, "value"] = np.nan
    elif mutation == "negative":
        h.loc[0, "value"] = -1
    elif mutation == "duplicate":
        h.loc[1, "close_ts"] = h.loc[0, "close_ts"]
    elif mutation == "unsorted":
        h = h.iloc[::-1]
    elif mutation == "preliminary":
        h["is_final"] = False
    elif mutation == "naive":
        h["close_ts"] = pd.to_datetime(h["close_ts"]).dt.tz_localize(None)
    assert evaluate_eligibility(CFG, h, RUN)["skip_reason"] == "source_invalid"


def test_disabled_source_error_and_deadline():
    assert evaluate_eligibility({**CFG, "enabled": False}, None, RUN)["skip_reason"] == "disabled"
    assert evaluate_eligibility(CFG, None, RUN)["skip_reason"] == "source_error"
    assert evaluate_eligibility(CFG, history(), RUN.replace(minute=50))["skip_reason"] == "deadline_missed"


def test_weekend_not_wrongly_called_source_lag():
    run = datetime.fromisoformat("2026-10-09T23:10:00+00:00")
    assert evaluate_eligibility(CFG, history(), run)["skip_reason"] == "outside_horizon"


def test_exact_session_boundary_cannot_skip_an_intervening_close():
    cfg = {**CFG, "calendar": "CRYPTO_UTC23"}
    run = RUN.replace(minute=0)
    assert evaluate_eligibility(cfg, history(cfg, run), run)["skip_reason"] == "source_lag"


def test_transform_units_and_inverse():
    levels = np.array([3.50, 3.51, 3.49])
    np.testing.assert_allclose(transform(levels, "diff_bp"), [1., -2.])
    changes = transform([100, 110], "log_return_pct")
    assert changes[0] == pytest.approx(100 * np.log(1.1))
    assert inverse_transform(100, changes[0], "log_return_pct") == pytest.approx(110)
    assert inverse_transform(3.5, 1, "diff_bp") == pytest.approx(3.51)
    with pytest.raises(ValueError):
        transform([0, 10], "log_return_pct")
    with pytest.raises(ValueError):
        transform([1, np.inf], "diff_bp")
