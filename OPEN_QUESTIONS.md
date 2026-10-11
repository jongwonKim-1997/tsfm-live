# Outstanding deployment and observation work

These are unresolved requirements, not claims of completion.

1. Public preview is deployed at [tsfm-live.pages.dev](https://tsfm-live.pages.dev/); API CORS/cache and noindex headers are verified. It remains a shadow preview with no prospective forecast records.
2. Cloud deployment is deferred by the owner, who chose local execution first. If later authorized, connect an approved Google Cloud billing account and agree a cost budget. Build/test the Linux image, verify the required local ephemeral-disk quota, private model/raw buckets and least-privilege service accounts.
3. Configure a scoped GitHub publishing credential in private local configuration (or Secret Manager if cloud execution is later approved). `main` already requires both `pipeline` and `site` checks with no bypass actors. Complete one staging publication and a deliberately rejected historical-ledger edit.
4. Configure an owner-authorized operations webhook destination. Force each alert type in staging and inspect delivery. No notification recipient has been selected yet.
5. Run the full 365-day seven-model historical replay using the [resumable private replay runner](docs/historical-replay.md). Existing 365-day evidence validates baselines/calendars only; the measured seven-model replay covers one historical date. The long run has not been started.
6. Accumulate 14 consecutive timely daily lock-ins and at least seven real daily cards; verify proofs and manual recovery from a fresh clone.
7. Accumulate 90 calendar days of prospective shadow operation before launch. Review PI scale once, with an ADR; have a second operator rehearse retry/correction steps.
8. Complete the provider-specific access, licence and series-definition steps in the [2026-10-11 source recheck](docs/data-sources-recheck.md) and [Korean-source checklist](docs/korea-source-requirements.md). Additional ECB/Treasury series are distinct candidates, not substitutes for the 11 disabled benchmark indicators. Evaluate TabPFN-TS access/licensing separately.
9. Start the [local daily runner](docs/local-daily.md) at 08:10 Asia/Seoul on this computer and retain its private journal. Its reports establish local operation only; public lock-in and website publication still require item 3. Scheduling scripts must be installed explicitly; adding the code does not mean a task is already active.

Brand and contact are resolved: TSFM Live / jdk12987@gmail.com. The repository, protected main branch and Cloudflare preview are active. The Google Cloud project exists without billing or a cloud runner. The daily local loop stores private diagnostic results; live publication remains disabled until its readiness gates and publishing setup are complete.
