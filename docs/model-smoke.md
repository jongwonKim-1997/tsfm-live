# Local CPU execution validation — 2026-10-08

**Seven TSFM adapters passed real weight-backed inference, exact seeded replay, and a fresh offline worker process.** This is a synthetic-input execution test, not a live forecast record, a financial accuracy comparison, or completion of the shadow-live launch gates.

Machine: AMD Ryzen 7 5800X (8 cores, 16 logical processors), 32 GB installed RAM, Windows 11 Pro. Model environments: private CPython 3.11.17, four CPU threads. No GPU was used. All model and package pins are in `models.yaml` and six separate `model_envs/*/uv.lock` files.

Every model received the identical 512-value synthetic context, seed 20261008, and one-step horizon. Every output contained 13 finite, nondecreasing quantiles. Toto and Sundial used 1000 actual model-generated draws each. The same adapter was run twice and then executed in a new offline process; all three outputs matched exactly on this machine.

| Entrant | First adapter call (s) | Loaded repeat (s) | Fresh offline worker (s) | Peak process RSS (MiB) | Quantile method |
|---|---:|---:|---:|---:|---|
| chronos-2 | 5.70 | 0.10 | 7.53 | 841 | interpolated |
| chronos-bolt-base | 4.76 | 0.08 | 7.67 | 1170 | interpolated |
| timesfm-2.5-200m | 2.05 | 0.29 | 4.73 | 2071 | interpolated |
| moirai-2.0-r-small | 3.58 | 0.02 | 6.47 | 437 | interpolated |
| toto-open-base-1.0 | 22.32 | 12.01 | 21.61 | 1618 | sampled |
| tirex | 1.73 | 0.49 | 5.76 | 559 | interpolated |
| sundial-base-128m | 11.22 | 10.15 | 13.14 | 1347 | sampled |

First-call timings start after Torch is imported and include adapter package loading and weight initialization. Fresh-worker timings include process startup and package imports. Weight downloads were completed before inference timing. Peak RSS is the process high-water resident set after the two adapter calls; it is not GPU memory or total system memory. Some smoke processes ran concurrently, so this is a validation measurement rather than a controlled performance benchmark.

The measured fresh-worker times sum to 66.9 seconds for one context across all seven models. Multiplying by 14 indicators gives about 15.6 minutes of model work on this synthetic workload. This is an estimate, not a measured full daily run; real contexts, ingestion, scheduling, publishing, cache pressure and other workloads still need shadow-period validation. Every measured worker was below the 120-second per-model limit.

## Issues found and repaired

- Moirai 2.0 squeezes the univariate target axis; the live array is three-dimensional despite the general four-dimensional API annotation. The adapter now handles the actual shape.
- Toto's legacy Lightning import requires `pkg_resources`. Its isolated environment now pins `setuptools==75.8.0` and has a regenerated lock.
- Toto model initialization consumes RNG state. Sample models now reseed after loading weights, which makes cold and loaded-model draws identical.
- The Windows process memory harness required a correctly typed HANDLE; measurements were rerun after repairing it.
- Moirai's ANTLR dependency exceeded Windows build-path limits in the deeply nested default cache. A shorter writable cache resolved the build without changing model code or system settings.

## Remaining gates

TabPFN remains disabled: authenticated local licence acceptance and a runnable adapter are still pending. The seven verified models are enabled in the catalog, but require their worker interpreter environment variables and prewarmed cache on any new scheduler host. All `launch_ready` fields remain false. Nothing from this test was written to `ledger/` or presented as live financial output.

The 365-day shadow backtest, six models operating daily, 14 consecutive timely public lock-ins, and at least 90 calendar days of shadow-live history remain separate requirements. A Windows CPU success does not establish Linux or GPU reproducibility.

Reproduce using `model_envs/smoke.py` with the profile interpreter and the same pinned cache; instructions are in `model_envs/README.md`. Full measured outputs, seed/context hash, hardware metadata, environment lock hashes and adapter source hashes are in [model-smoke.json](model-smoke.json).
