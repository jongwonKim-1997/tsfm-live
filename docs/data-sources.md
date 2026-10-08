# Data sources and provenance

Reviewed: **2026-10-08 (Asia/Seoul)**. This is the implementation's source-use assessment, not a blanket legal conclusion. A publicly accessible endpoint does not establish redistribution rights. `return_only` also does not establish rights to derived data. Disabled indicators perform no network requests.

| Indicator | Source / identity | State | Display policy | Outstanding condition |
|---|---|---|---|---|
| kospi | ECOS candidate `802Y001 / 0001000` | Disabled | return_only | Key, series identity, KRX rights, final publication timing |
| kosdaq | ECOS, exact codes unverified | Disabled | return_only | Same checks as KOSPI |
| spx | Vendor pending | Disabled | return_only | Automated retrieval, derived-data use, timely official close |
| ndq | Vendor pending | Disabled | return_only | Automated retrieval, derived-data use, timely official close |
| usdkrw | ECOS Seoul close candidate | Disabled | return_only | Closing-rate identity and session definition, key, rights |
| eurusd | ECB USD per EUR reference rate | Enabled, runtime freshness gate | level | Ongoing source/calendar monitoring |
| usdjpy | ECB JPY per EUR divided by USD per EUR | Enabled, runtime freshness gate | level | Ongoing source/calendar monitoring |
| ktb3y | ECOS, exact codes unverified | Disabled | return_only | Final bond-yield definition, close time, key, rights |
| ktb10y | ECOS, exact codes unverified | Disabled | return_only | Same checks as 3Y |
| ust10y | Treasury XML `BC_10YEAR` | Enabled, runtime freshness gate | level | Publication SLA unavailable; check each run |
| wti | Vendor pending | Disabled | return_only | Settlement definition, continuous-contract roll, rights |
| gold | Vendor/benchmark pending | Disabled | return_only | LBMA or alternative licence and timing |
| vix | Cboe VIX history CSV | Disabled | return_only | Public and derived-data use need permission; timing unverified |
| btcusd | Binance `BTCUSDT`, USDT proxy | Disabled | return_only | Applicable public redistribution/derived-data terms |

## ECB

Provider: European Central Bank. Endpoint: [historical reference-rate XML](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml). Schema: dated `Cube@time`, currency `Cube@currency`, numeric `Cube@rate`. The expected schema and pair parameters are included in each source fingerprint. EUR/USD is the USD quote; USD/JPY is **EUR/JPY ÷ EUR/USD**, joined within the same dated Cube, never across different dates.

The [ECB copyright conditions](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html) permit free use of directly obtained information with accurate reproduction and source attribution; modifications must be identified. The application therefore enables storage, level display and redistribution with source attribution and an explicit derived-rate notice. The benchmark's licence does not replace the ECB's conditions.

The [ECB methodology](https://data.ecb.europa.eu/methodology/exchange-rates) describes publication around 16:00 central-European local time, based on the earlier concertation procedure. This implementation labels its event **ECB reference publication convention, 16:00 Europe/Berlin**, not an exchange close or exact provider publication timestamp. Dates follow the [TARGET calendar](https://www.ecb.europa.eu/ecb/contacts/working-hours/html/index.en.html); other ECB office holidays are not automatically TARGET holidays. This is earlier than 08:10 KST the next morning. Missing latest observations still produce `source_lag`.

The XML has no per-observation publication timestamp or preliminary/final status. `published_ts` remains null. Receipt of a published official daily reference is evidence of availability at fetch time, not proof that it can never be revised. Record later revisions through append-only corrections. Historical downloads do not establish point-in-time availability for simulated past runs.

Attribution: `Source: European Central Bank. Log changes and model outputs calculated by TSFM Live.` USD/JPY additionally states its cross-rate formula.

## US Treasury

Provider: U.S. Department of the Treasury. [Official XML API documentation](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) specifies the endpoint:

`https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=YYYY`

The adapter fetches each required year, parses Atom entries, and requires `NEW_DATE` and `BC_10YEAR`. Missing observations are omitted, never filled. Units are yield percent; the scored change is `100 × (next − last)` basis points.

The [Treasury methodology overview](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics/) describes indicative input quotes around 15:30 ET. The rate is a fitted par yield, not the closing traded yield of a specific bond. The official pages reviewed do **not** guarantee the spec's suggested 17:00 ET publication time. Actual presence in the official feed, and an exact latest-session match, are mandatory at every run.

Calendar: SIFMA US full closures, including Columbus Day and Veterans Day, with an operational target boundary at 15:30 ET on ordinary sessions and at the earlier SIFMA close on shortened sessions. The [current SIFMA calendar](https://www.sifma.org/resources/guides-playbook/holiday-schedule) specifies **12:00 ET on 2026-04-03**, unlike a generic 14:00 early-close heading in an annual summary. These boundaries are calendar conventions; they are not fabricated source publication times. `published_ts` stays null.

Storage/display/redistribution decision: allow these official Treasury-produced statistics with attribution, on the assessment that these are U.S. government statistical outputs. [17 USC 105 and the government-work definition](https://www.copyright.gov/title17/92chap1.html) support that assessment; this does not claim that every item on a government website is unrestricted or that a new CC licence owns the underlying facts. No Treasury logos or third-party charts are copied.

Attribution: `Source: U.S. Department of the Treasury. Basis-point changes and model outputs calculated by TSFM Live.`

## ECOS

Provider: Bank of Korea. [Official Open API portal](https://ecos.bok.or.kr/api/) is accessible, but its client-rendered specification and applicable underlying series rights could not be fully verified with this build's evidence. No API key was supplied or created. The spec's KOSPI code is retained only as an explicitly unverified candidate; other codes are null instead of guesses.

A working `StatisticSearch` adapter supports daily pagination, matching returned statistic/item IDs, optional unit checks, key redaction, and the same cache/retry rules. It refuses a network request without both `ECOS_API_KEY` and `series_verified: true`. Enabling requires official metadata confirmation, rights for the original series, a verified final observation convention and evidence that the latest session is published by the daily run. The Seoul FX closing rate must not be replaced by a next-day base rate. KRX trading hours must not be assumed to define bond/FX observation times.

Storage/display/redistribution: **not cleared** for this public benchmark. `return_only` is a future display preference, not a permission grant. No fallback scraping is implemented.

## Cboe

Candidate endpoint: `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`. The parser requires DATE/OPEN/HIGH/LOW/CLOSE, positive closes and the configured session timestamp. The adapter is disabled by configuration and the registry will not fetch it.

[Cboe website terms, section 2](https://www.cboe.com/terms/) distinguish personal non-commercial downloading from broader storage, public display, distribution and derivative works, for which permission is required subject to the stated exceptions. We do not presume this benchmark qualifies for an exception. Public/derived use and reliable final daily publication timing remain unresolved; permission or an appropriate licensed feed is needed.

## Binance

The [official public-market-data guidance](https://developers.binance.com/en/docs/products/spot/rest-api) identifies `https://data-api.binance.vision` for public data. The [official kline documentation](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market) defines the hourly kline fields and timestamps. The adapter requests `/api/v3/klines`, `symbol=BTCUSDT`, `interval=1h`, UTC timezone, paginates in batches of 1,000 and accepts only the **22:00 UTC opening** bar. The provider's inclusive 22:59:59.999 close timestamp maps to the canonical 23:00:00 UTC boundary. Bars not yet closed at fetch time are excluded.

`BTCUSDT` is quoted in **USDT**, not U.S. dollars. The stable `btcusd` ID from the specification is retained, while every catalogue label identifies **Bitcoin / USDT (USD proxy)**. Stablecoin basis risk is part of this proxy's definition.

Storage/display/redistribution: **not cleared** under the applicable Binance terms. API availability and documentation copyright do not settle market-data rights. The indicator remains disabled; the adapter has fixture tests but no public data is republished.

## Equities and commodities

No Stooq, Yahoo, Nasdaq Data Link, EIA/FRED, LBMA or other vendor source is silently substituted. The spec itself requires source-specific verification. For `spx`, `ndq`, `wti`, and `gold`, neither an applicable vendor agreement nor verified complete timing/series evidence was obtained. Their endpoints are therefore unset and indicators disabled. In particular, `return_only` cannot cure prohibited automated access or prohibited derived-data use. WTI roll rules and gold's exact benchmark must be fixed before collecting history. Their placeholder calendars are not authority for future activation.

## Retrieval evidence and remaining verification

All requests retain raw response bytes and a sidecar containing fetched UTC time, redacted URL, SHA-256 and source fingerprint in an **external** cache. HTTPS validation is mandatory; the Mozilla CA bundle supplements the platform trust store on Windows. Failure is never bypassed with disabled TLS validation. Network failures get up to three retries (2, 8, 30 seconds) inside the 180-second per-indicator budget; permanent 4xx errors except 429 fail immediately. There is no stale-response substitution during a live fetch. Operations should retain raw evidence at least 90 days and protect the cache from credential leakage.

Read-only live smoke requests succeeded at the following exact UTC receipt times (2026-10-08 locally):

| Source | Receipt UTC | Coverage parsed from 2024-01-01 | Latest observation | Response SHA-256 |
|---|---|---:|---|---|
| ECB full XML | 2026-10-07T15:40:21.073894Z | 707 per pair | 2026-10-07 | `85cd6e7589b6b05b023d764964d66792e775dddb2fc639713ed400a75ac95ccd` |
| Treasury 2024 XML | 2026-10-07T15:38:31.616468Z | Part of 691 combined | 2024 history | `47f9e2042e2128210ad5d53fd6ee89bfcff661334e2f793782a1a39ca8db8dd4` |
| Treasury 2025 XML | 2026-10-07T15:38:32.915195Z | Part of 691 combined | 2025 history | `305c51b74da9fb4aec2685e715229d966f0e06ea1968c6b7431860b84cae3795` |
| Treasury 2026 XML | 2026-10-07T15:38:34.099841Z | Part of 691 combined | 2026-10-06 | `fe3a112f3dd99d6f4c6d97e4a80eb64132afe98318acdfae2d02e60547580732` |

The latest Treasury observation correctly preceded that day's 15:30 ET event. Both pairs and Treasury had no missing configured sessions over the inspected range. This smoke test proves retrieval/parsing, **not** 14 consecutive timely runs or historical publication availability. Source fingerprints: EURUSD `3922d162da65eb7ce04cb75dbe6da3ffc495b6b63447a8975aa6e658b1921f2b`; USDJPY `1d23e33edbcfcbbf51e44ff20785cb9d11b8a1427534bd4f9244e5481161675f`; UST10Y `76b5434ee7c48f22ba882dcae368b78a7c27f18a37ed906a58f1c3b36a3d771d`.
