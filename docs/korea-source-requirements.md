# Korean source access and timing requirements

Reviewed **2026-10-11**. The five Korean indicators remain disabled. This review
checked public official documentation; it did not obtain a key, accept account
terms, submit an application, download authenticated observations, contact a
provider, or enable a series. Successful retrieval and permission to publish are
separate decisions. Existing configuration values are candidates, not verified
metadata.

| Indicator | Practical collection route | What is still required |
|---|---|---|
| KOSPI | ECOS, or the official KRX KOSPI daily index service | Owner-controlled key; exact headline index and daily closing field; metadata and timing evidence; permitted retention/display/redistribution scope |
| KOSDAQ | ECOS, or the official KRX KOSDAQ daily index service | Same checks, independently for KOSDAQ; do not substitute a constituent or an ETF |
| USD/KRW | A specifically identified ECOS or originating-provider daily benchmark | Exact quote direction, observation time, session-date convention, calendar, publication time and rights; a daily benchmark is not automatically the end of the full FX trading session |
| KTB 3Y / 10Y | ECOS with original publisher and yield definition identified | Separate daily item codes and units; afternoon versus morning yield selection; original publication and ECOS availability evidence; retention and display rights |

## ECOS

The Bank of Korea describes API key issuance through the
[official ECOS API portal](https://ecos.bok.or.kr/api/) and development against
its individual specifications. It also explains that ECOS carries statistics
produced by other institutions as well as its own statistics. Consequently,
being available through ECOS is not evidence that every upstream dataset has
identical reuse terms. [Bank of Korea ECOS introduction](https://www.bok.or.kr/portal/bbs/B0000522/view.do?menuNo=201692&nttId=10070977).

The API portal rendered no usable terms or metadata in this research tool.
Current key issuance timing, quotas, exact table/item codes and dataset-specific
reuse permission are **unverified**. Third-party code examples were not used to
declare those facts verified. In particular, the repository's candidate KOSPI
`802Y001` / `0001000` is not approval to set `series_verified: true`.

After the owner obtains a key, the next technical check is a private metadata
request followed by a small observation sample. Record the table/item labels,
daily frequency, units, original producer, revision notes and coverage. Then
confirm at least 301 consecutive usable levels for 300 transformed changes,
and verify that the preceding required session is available at the actual
08:10 KST cutoff. A successful request later in the day cannot establish that
the observation was available that morning.

The adapter expects `ECOS_API_KEY`. Keep it in a private local secret source,
outside the public repository and runtime path file. Do not paste it into chat,
commit it, or log an authenticated request URL: ECOS request paths contain the
key. The existing one-off runtime launcher intentionally filters credentials;
adding a key alone does not activate a disabled indicator.

## KRX index alternative

The official catalog offers KOSPI and KOSDAQ daily index services with coverage
from 2010-01-04. Their specification pages identify request-header
`AUTH_KEY`; the dynamic field/API-ID tables were not exposed to this research
tool. A KRX adapter and an authenticated field-level sample have not been
implemented or verified here. [KOSPI service](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES001_S2.cmd?BO_ID=EREKZauXnMmxyIlqzeDN),
[KOSDAQ service](https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES001_S2.cmd?BO_ID=nimebcamqFNIPNcRrHoO).

The documented access process is membership/login, a key application and
administrator approval, followed by a separate application and approval for
each desired API service. The operator should request the two index services
explicitly. [KRX service procedure](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp).

The Korean API terms shown with effective date **2025-12-26** specify
non-commercial use, no charging third parties for API results, a renewable
one-year key term, at most 10,000 requests per key per day, and no key transfer.
Article 10 requires the screen attribution “한국거래소 통계정보”. Article 11
restricts providing received information to third parties and use after the
agreement ends. Article 12 discusses newly produced value-added information
without itself settling this project's redistribution scope.
[KRX API terms, articles 5–12](https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp).

**Project decision:** ordinary API approval is insufficient evidence for a
public GitHub history, downloadable API or blanket CC BY 4.0 release. Obtain a
specific provider clarification or applicable licence covering the proposed
outputs before public activation. Ask separately about raw levels, daily
returns, forecast quantiles, error metrics, indefinite immutable retention and
third-party downloads. Changing `display_policy` to `return_only` does not
resolve that question. This is an operational evidence requirement, not a
legal conclusion about all derived statistics. No provider inquiry has been
sent.

## Observation time and publication time

**KTB yields.** For KOFIA's final quoted yield series, the published rule
distinguishes 11:30/16:00 KST observations from 12:00/16:30 announcements and
includes 3-year and 10-year government bonds. If the ECOS item is the afternoon
final quoted yield, a 15:30 observation timestamp is incorrect. A different
yield series requires its own definition. ECOS's later ingestion time remains
unverified. [KOFIA implementing rules, article 51(2)–(3)](https://law.kofia.or.kr/service/law/lawFullScreenContent.do?historySeq=1645&seq=137).

**USD/KRW.** The government's 2026 second-half policy page lists July 2026 as
the implementation month for a transition from 09:00–02:00 to weekday
24-hour interbank FX operation, with January 1 and weekends excluded. It also
describes the change as a policy being pursued. This review did **not** verify
a dated operational commencement notice, the currently implemented calendar,
or an ECOS benchmark's treatment of that change. Do not report the timetable
as proof of actual operation. [Official 2026 second-half FX policy](https://whatsnew.mofe.go.kr/mec/ots/dif/view.do?comBaseCd=DIFPERCD&difPer1=DIFPER007&difSer=0051fa4d-ef8b-4373-9875-fb407039aecc&temp=2026&temp2=HALF002).

This makes the existing `XKRX`/15:30 FX placeholder unsuitable for activation
without further evidence. A named 15:30 daily benchmark may still be a valid
target, but must be labelled and calendared as that specific benchmark. Do not
replace it silently with a next-day base rate, dealer midpoint or a different
session's closing rate. Store observation time, known publication time and
actual fetch time separately; an unknown publication timestamp stays unknown.

## Inputs needed from the owner

1. Obtain an ECOS key personally and place it in the agreed private local
   secret location. Confirm the intended use when accepting provider terms.
   If choosing KRX instead, complete both key and per-service approvals.
2. Provide the applicable approval/licence text or a provider response for the
   planned public outputs. A private local retrieval test can be evaluated
   separately from public redistribution; paid access is not authorized.
3. Confirm the intended USD/KRW benchmark once official metadata identifies
   the choices. Keep the originally requested 15:30 measure only if a verified
   series actually represents it. For bonds, use a named maturity and yield
   convention rather than a generic market-close label.

After these inputs, perform the private metadata/sample test, collect real
cutoff-availability evidence, review terms per item and only then propose
configuration changes. No additional account, key, data-download approval or
paid service is required to continue daily local work on the three already
enabled ECB/Treasury indicators.
