# Isolated model runtimes

Each directory is a virtual uv project with an exact Python 3.11 dependency lock. `uv sync --frozen --project model_envs/chronos --python 3.11` installs a profile. Replace `chronos` with `timesfm`, `moirai`, `toto`, `tirex`, or `sundial`. CPU Torch wheels are selected explicitly. Do not combine these dependency sets with the pipeline's environment.

Configure these interpreter paths in the scheduler environment:

| Profile | Environment variable | Windows executable | Linux executable |
|---|---|---|---|
| chronos (2 and Bolt) | `TSFM_PYTHON_CHRONOS` | `model_envs/chronos/.venv/Scripts/python.exe` | `model_envs/chronos/.venv/bin/python` |
| timesfm | `TSFM_PYTHON_TIMESFM` | corresponding profile path | corresponding profile path |
| moirai | `TSFM_PYTHON_MOIRAI` | corresponding profile path | corresponding profile path |
| toto | `TSFM_PYTHON_TOTO` | corresponding profile path | corresponding profile path |
| tirex | `TSFM_PYTHON_TIREX` | corresponding profile path | corresponding profile path |
| sundial | `TSFM_PYTHON_SUNDIAL` | corresponding profile path | corresponding profile path |

Set `PYTHONPATH` to the repository's absolute `pipeline` directory. The subprocess entry point is `python -m tsfm_live.models.worker`. It accepts one object on stdin:

```json
{"config":{"id":"rw0"},"context":[1,2,3],"quantiles":[0.025,0.5,0.975],"seed":20261008}
```

Success is `{"ok":true,"output":{"quantiles":{...},"mean":0.0,"quantile_method":"native","n_samples":null}}`. Failure is `{"ok":false,"output":null,"error":"..."}` with nonzero exit code. Vendor logs and traceback go to stderr. The orchestrator must enforce a hard timeout and terminate the process; the worker has no retry or synthetic fallback.

Weights are not bundled. Warm only the configured HF revision into an external `HF_HOME` cache before scheduling. For a manual smoke, a copy of the model config may set `local_files_only=false`; scheduled configs use `local_files_only=true` and `HF_HUB_OFFLINE=1`. A successful lock or environment install is not an inference validation. Record actual runtime evidence before changing `runtime_verified` or enabling a disabled entrant.

TabPFN has no environment profile because its optional adapter and authenticated custom-licence flow remain pending; do not silently use its online client.

Reproduce a real CPU smoke using the profile interpreter:

```powershell
model_envs/chronos/.venv/Scripts/python.exe model_envs/smoke.py chronos-2 --cache-dir C:/path/outside/repository/hf-cache --report-dir C:/path/to/shadow-smoke --warm-cache
```

Omit `--warm-cache` after warming to test fully offline. The script uses the same 512-value deterministic synthetic context for every entrant and repeats the real model twice. It records 13 quantiles, exact replay, adapter timings, dependency versions and peak process resident memory. Reports are expressly barred from `ledger/`. This is an execution check, not an accuracy backtest or live publication record. CPU threads default to four (`TSFM_TORCH_THREADS`); different thread/hardware settings require fresh reproducibility measurements.

On Windows, if Moirai's `antlr4-python3-runtime` source build exceeds path limits, set `UV_CACHE_DIR` to a shorter writable cache directory before `uv sync`. Toto's legacy Lightning dependency needs `setuptools==75.8.0`; the profile pins it because later setuptools removes `pkg_resources`.

The separate `ots/` profile is an optional operations tool, not a model entrant. It locks OpenTimestamps client 0.7.2 and library 0.4.5. See [ledger verification](../ledger/README.md) for proof semantics, setup and commands. Its frozen installation succeeded on Python 3.11.17, but the Windows CLI failed to locate native OpenSSL through python-bitcoinlib; an installation is not a successful runtime check or a timestamp. Linux containers must supply OpenSSL, and independent verification additionally requires a synchronized Bitcoin Core mainnet node. No proof was submitted during implementation.
