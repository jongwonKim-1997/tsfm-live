"""Published protocol constants. Never change without an ADR."""
RUN_TIME_LOCAL = "08:10"
LOCKIN_DEADLINE_LOCAL = "08:50"
TZ = "Asia/Seoul"
CONTEXT_LEN = 512
SEED = 20261008
MODEL_TIMEOUT_S = 120
QUANTILES = [0.025, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.975]
EWMA_LAMBDA = 0.94
REGIME_LOOKBACK = 250
REGIME_PCTL = 0.80
CALL_EPS = 0.01
WINDOWS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
MIN_N_CELL = 10
MIN_N_RANK = 60
MIN_N_PI = 30
RANK_COVERAGE = 0.75
BOOT_B = 1000
BOOT_BLOCK = 5
BOOT_SEED = 7
PI_SCALE = 0.20
ACTUAL_GRACE_DAYS = 5

def constants():
    return {key: value for key, value in globals().items() if key.isupper()}
