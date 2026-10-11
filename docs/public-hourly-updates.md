# Free hourly publication setup

Collection and all seven zero-shot models run on the owner's local CPU. A successful run writes a rights-cleared projection to `site/public/api/v1/local_dashboard.json`. Publishing a repository revision deploys that snapshot. It does not by itself arrange continuous uploads from the PC.

The optional KV route separates hourly JSON updates from static site builds. Cloudflare Pages Free currently allows 500 builds/month, below 24 hourly rebuilds/day for a 30-day month. KV Free includes 1,000 writes/day and 100,000 reads/day; Pages Functions uses the Workers request allowance. The hourly publisher uses about 24 writes/day while the PC is running. No paid plan is required for this configuration, and none has been selected. See [Pages limits](https://developers.cloudflare.com/pages/platform/limits/) and [KV pricing](https://developers.cloudflare.com/kv/platform/pricing/).

## Current status

The upload helper, Pages Function and frontend polling are implemented. **The remote KV namespace, binding and uploader credential have not been provisioned.** A saved browser permission blocks access to the Cloudflare dashboard. Without these settings, the Function falls through to the deployed static snapshot and old plots expire normally; it does not fabricate live updates.

## One-time configuration

1. In the existing Cloudflare account, create a free Workers KV namespace named `tsfm-live-dashboard`.
2. In Pages project `tsfm-live`, Settings → Bindings, add a production KV binding named `TSFM_DASHBOARD` pointing at that namespace. Redeploy after binding. The repository root for Pages is `site`; the function resides under `site/functions/api/v1/local_dashboard.json.js`.
3. Create a token restricted to the target account with Workers KV Storage Edit, with an appropriate expiry. Do not grant DNS, billing or account administration. Cloudflare may scope KV tokens at account rather than individual namespace level; review the actual available scope before approving the token. Keep it on the local PC and out of the model runtime environment, repository, page HTML and chat.
4. Save these literal assignments in a private file outside the repository, for example `work/cloudflare-publish.env` at the workspace root:

```dotenv
CLOUDFLARE_ACCOUNT_ID=<32-character-account-id>
CLOUDFLARE_KV_NAMESPACE_ID=<32-character-namespace-id>
CLOUDFLARE_API_TOKEN=<private-token>
```

5. Run the existing updater with the additional option:

```powershell
.\pipeline\.venv\Scripts\python.exe -X utf8 ops/update_dashboard.py --runtime-env-file ../../work/model-smoke/runtime.env --publish-env-file ../../work/cloudflare-publish.env
```

6. Only after a successful upload, add that option to the existing `TSFM-Local-Dashboard` scheduled action. Keep `pythonw.exe`, hourly minute 10, `IgnoreNew` and the existing private runtime path.

The uploader only accepts hourly Coin Metrics Community rows explicitly marked public with CC-BY-NC-4.0. It rejects Upbit/private data, keeps model inputs private, and reports upload errors without credential text. It publishes the key `hourly-dashboard`. Source or inference failures remain visible as availability status; stale plots expire in the frontend. Publication is separate from the fixed-time benchmark ledger and never claims a public timestamp receipt.

The Function serves KV with a 60-second cache and the page checks for newer JSON every minute. KV propagation and those caches can add a short delay. If the PC is asleep, offline or logged out, new local forecasts and uploads stop. Existing stale data is not labelled live.

Official setup references: [Pages KV bindings](https://developers.cloudflare.com/pages/functions/bindings/#kv-namespaces), [KV write endpoint](https://developers.cloudflare.com/api/resources/kv/subresources/namespaces/subresources/values/methods/update/).
