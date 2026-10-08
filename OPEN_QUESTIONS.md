# Outstanding deployment and observation work

These are unresolved requirements, not claims of completion.

1. Complete Cloudflare account email verification and choose the final public origin. Verify real hosted CORS/cache headers and social images.
2. Cloud deployment is deferred by the owner, who chose local execution first. If later authorized, connect an approved Google Cloud billing account and agree a cost budget. Build/test the Linux image, verify the required local ephemeral-disk quota, private model/raw buckets and least-privilege service accounts.
3. Configure a scoped GitHub publishing credential in Secret Manager and require both `pipeline` and `site` checks on `main`. Complete one staging publication and a deliberately rejected historical-ledger edit.
4. Configure an owner-authorized operations webhook destination. Force each alert type in staging and inspect delivery. No notification recipient has been selected yet.
5. Run the full 365-day seven-model historical replay using the [resumable private replay runner](docs/historical-replay.md). Existing 365-day evidence validates baselines/calendars only; the measured seven-model replay covers one historical date. The long run has not been started.
6. Accumulate 14 consecutive timely daily lock-ins and at least seven real daily cards; verify proofs and manual recovery from a fresh clone.
7. Accumulate 90 calendar days of prospective shadow operation before launch. Review PI scale once, with an ADR; have a second operator rehearse retry/correction steps.
8. Obtain source access/terms for the 11 disabled indicators and evaluate TabPFN-TS access/licensing. Their absence is explicit in the configuration and UI.

Brand and contact are resolved: TSFM Live / jdk12987@gmail.com. The repository and Google Cloud project have been created; that does not imply the cloud runner or hosted site is active.
