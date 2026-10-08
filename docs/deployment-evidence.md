# Preview deployment evidence

Verified on 2026-10-08. This is a static shadow preview, not a live forecast launch.

- Public site: <https://tsfm-live.pages.dev/>
- Korean home: <https://tsfm-live.pages.dev/ko/>
- Source: <https://github.com/jongwonKim-1997/tsfm-live>
- Initial implementation: PR #1, merged as `de42c783b7d611aae83c0e1069e579a9cb70e0e8` after both required CI jobs passed. The Linux pipeline ran 217 tests successfully.
- Cloudflare Pages is connected to `main`. Root `site`; build `npm run build`; output `dist`; Node `24.21.0`; `ASTRO_TELEMETRY_DISABLED=1`; `TSFM_PUBLIC_ORIGIN=https://tsfm-live.pages.dev`.
- The owner approved the Cloudflare GitHub App for this repository only.
- Active GitHub ruleset `24717497` (`main-ledger-integrity`) targets the default branch, requires PRs and up-to-date `pipeline` and `site` checks from GitHub Actions, prevents deletion and force pushes, and has no bypass actors.
- Hosted HTML and JSON return `X-Robots-Tag: noindex, nofollow`. The JSON API returns `Access-Control-Allow-Origin: *` and `Cache-Control: public, max-age=300`.
- Production contains no sample or historical forecast records. Populated review data is kept in a separate local preview.

The Google Cloud project `tsfm-live-20261008` exists without connected billing, deployed jobs or schedules. The owner chose manual local CPU execution. No Windows scheduled task or notification recipient is configured.

Real-weight model inference and the one-date historical integration are documented separately in [model smoke](model-smoke.md) and [integration smoke](integration-smoke.md). Public lock-ins, alerts, external timestamp proofs, 14 timely daily runs and 90 days of prospective observation remain unverified.
