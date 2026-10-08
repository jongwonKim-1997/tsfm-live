from datetime import date, datetime, timedelta, timezone

import pytest

from tsfm_live.calendars import session_bounds, session_close_on_date
from tsfm_live.sources import load_indicators


def cfg(name, **extra):
    return {"calendar": name, **extra}


@pytest.mark.parametrize("day", ["2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
                                    "2026-09-24", "2026-09-25", "2025-10-08", "2026-05-01",
                                    "2026-12-31"])
def test_krx_lunar_chuseok_substitute_and_exchange_holidays(day):
    assert session_close_on_date(cfg("XKRX"), date.fromisoformat(day)) is None


@pytest.mark.parametrize("day,hour", [("2026-03-06", 21), ("2026-03-09", 20),
                                      ("2026-10-30", 20), ("2026-11-02", 21)])
def test_nyse_dst(day, hour):
    assert session_close_on_date(cfg("XNYS"), date.fromisoformat(day)).hour == hour


def test_nyse_early_close_and_columbus_not_holiday():
    assert session_close_on_date(cfg("XNYS"), date(2026, 11, 27)).isoformat() == "2026-11-27T18:00:00+00:00"
    assert session_close_on_date(cfg("XNYS"), date(2026, 10, 12)) is not None
    assert session_close_on_date(cfg("XNYS"), date(2026, 11, 26)) is None


@pytest.mark.parametrize("day", ["2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01", "2026-12-25"])
def test_ecb_target_holidays(day):
    assert session_close_on_date(cfg("ECB"), date.fromisoformat(day)) is None


def test_ecb_not_all_german_or_ecb_office_holidays():
    assert session_close_on_date(cfg("ECB"), date(2026, 5, 14)) is not None
    assert session_close_on_date(cfg("ECB"), date(2026, 12, 24)).hour == 15
    assert session_close_on_date(cfg("ECB"), date(2026, 6, 1)).hour == 14


def test_ust_sifma_differs_from_nyse_and_has_noon_good_friday():
    assert session_close_on_date(cfg("UST"), date(2026, 10, 12)) is None
    assert session_close_on_date(cfg("UST"), date(2026, 11, 11)) is None
    assert session_close_on_date(cfg("UST"), date(2026, 11, 27)).isoformat() == "2026-11-27T19:00:00+00:00"
    assert session_close_on_date(cfg("UST"), date(2026, 4, 3)).isoformat() == "2026-04-03T16:00:00+00:00"
    assert session_close_on_date(cfg("UST"), date(2026, 10, 8)).isoformat() == "2026-10-08T19:30:00+00:00"


def test_crypto_exact_close_and_strict_bounds():
    run = datetime(2026, 10, 7, 23, 10, tzinfo=timezone.utc)
    previous, following = session_bounds(cfg("CRYPTO_UTC23"), run)
    assert previous == run.replace(minute=0)
    assert following == previous + timedelta(days=1)
    previous2, following2 = session_bounds(cfg("CRYPTO_UTC23"), previous)
    assert previous2 < previous < following2
    assert following2 == following


@pytest.mark.parametrize("run_date", ["2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"])
def test_friday_to_monday_24h_rule_for_every_configured_calendar(run_date):
    local = datetime.fromisoformat(run_date + "T08:10:00+09:00")
    run = local.astimezone(timezone.utc)
    for indicator in load_indicators():
        previous, following = session_bounds(indicator, run)
        assert previous < run < following
        within = following - run <= timedelta(hours=24)
        if indicator["calendar"] == "CRYPTO_UTC23":
            assert within
        elif local.weekday() in {5, 6}:
            assert not within
        elif local.weekday() == 4:
            assert within
        elif indicator["calendar"] != "XKRX":
            assert within
        else:
            # National Foundation Day substitute holiday, Monday 2026-10-05.
            assert not within


def test_spec_worked_example_columbus_day():
    run = datetime.fromisoformat("2026-10-12T08:10:00+09:00")
    assert session_bounds(cfg("UST"), run)[1] - run > timedelta(hours=24)
    assert session_bounds(cfg("XNYS"), run)[1] - run < timedelta(hours=24)


def test_naive_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        session_bounds(cfg("ECB"), datetime(2026, 10, 8))
