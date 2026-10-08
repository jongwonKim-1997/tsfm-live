# Public copy, data permissions, and operational boundaries

This is an implementation record for review, not a legal opinion. The operator
brand and public operator label are **TSFM Live**, with the owner-provided contact
**jdk12987@gmail.com**. No university affiliation is inferred. The original
specification is retained unchanged as source material.

## Product scope

The public product compares model outputs and realised observations for research
and benchmarking. The implemented scope excludes payments, accounts, donations,
advertising, affiliate links, individual stocks, portfolios, and performance
simulations of transactions. No cookies or analytics are enabled during shadow
operation. Source permissions and model licences are documented separately.

Whether a particular operator or future business model has legal obligations
requires qualified review of the actual facts and applicable law. The software
does not assert that a free service is automatically exempt from regulation.

## Copy lint

Preferred descriptions are “model output”, “model forecast”, “quantile”,
“interval”, “scored”, and “skill vs random walk”.

The specification bans these terms in public product copy:

```
our forecast
our prediction
prediction service
recommend
buy
sell
long
short
target price
outlook
signal
alpha
profit
returns you can expect
```

The linter uses word boundaries for standalone words, so unrelated substrings
are not treated as claims. The mandatory disclaimer is an explicit exception:
its complete, exact text is allowed only in the dedicated disclaimer field.
Removing the exact disclaimer before scanning resolves the specification's
internal conflict: its own required disclaimer contains several banned words.
Public charts, API documentation, cards, and translations remain in scope.
Implementation identifiers such as a chart library's settings are not product
copy; exceptions must be narrow and auditable, never blanket file exclusions.

## Required English disclaimer

> TSFM Live publishes the raw outputs of publicly available time-series models and scores them against realised data for research and benchmarking purposes only. Nothing on this site is investment advice, a recommendation, or an offer to buy or sell any financial instrument. The operators do not trade on these outputs and accept no liability for decisions made using this site. Model outputs are frequently no better than a random walk; see the Methodology and Indicators pages.

## Korean translation

> TSFM Live는 공개된 시계열 모델의 원출력을 게시하고 실제 관측 데이터와 비교해 연구 및 벤치마킹 목적으로만 평가합니다. 이 사이트의 어떤 내용도 투자 조언, 권유 또는 금융상품 매수·매도 제안이 아닙니다. 운영자는 이 출력에 따라 거래하지 않으며, 사이트를 이용한 의사결정에 대한 책임을 지지 않습니다. 모델 출력은 랜덤워크보다 나은 성능을 내지 못하는 경우가 많습니다. 방법론과 지표 페이지를 참고하세요.

The exact rendered translation in the site's locale catalogue is authoritative
for the automated disclaimer-presence test. Any wording change must update this
record and the exact-match lint exception together.

## Data and model permission gates

Each enabled source needs documented storage, derived-data, display, automated
access, redistribution, attribution, and publication-time decisions. A
`return_only` policy hides actual levels; it does not itself create permission
to retrieve or redistribute derived values. Unverified sources stay disabled.
Tokens and private raw responses stay outside the public repository.

Pinned model weights retain their own licences and attribution conditions;
the code licence does not replace them. Any model requiring account terms or
licence acceptance remains disabled until the owner completes that process.
The public ledger licence applies only to records the operator may license,
not upstream model weights, source data, or provider trademarks.

Before public announcement, verify both language footers, operator/contact,
provider attribution, weight licences, no-cookie state, card wording, data
display restrictions, and the documented shadow-live evidence. These checks
are release requirements; they have not been represented as a legal clearance.
