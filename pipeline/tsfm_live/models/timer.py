"""Pinned Timer point forecasts; no fabricated probability distribution."""
from .base import (
    ForecastOutput, ModelAdapter, as_numpy, checked_context, checked_horizon,
    path_output, seed_torch,
)

AUDITED_REVISION = "70077a71acce1b4c00d98332fcaabc694255d8e5"


class TimerAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed, *, horizon=1):
        horizon = checked_horizon(horizon)
        x = checked_context(context)
        if len(x) % 96 or not 96 <= len(x) <= 2880:
            raise ValueError("timer_context_requires_whole_96_point_patches")
        if (self.config["hf_revision"] != AUDITED_REVISION
                or self.config.get("remote_code_audit") != "timer-2026-10-19"):
            raise RuntimeError("remote_code_revision_not_audited")
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            from transformers import AutoModelForCausalLM
            self._model = AutoModelForCausalLM.from_pretrained(
                self.config["hf_repo"], trust_remote_code=True,
                code_revision=AUDITED_REVISION, torch_dtype=torch.float32,
                **self.hf_kwargs(),
            ).to(self.device(torch)).eval()
        series = torch.tensor(x, dtype=torch.float32, device=self.device(torch))[None, :]
        with torch.inference_mode():
            prediction = self._model.generate(series, max_new_tokens=horizon)
        values = as_numpy(prediction).reshape(-1)
        if len(values) != horizon:
            raise ValueError("timer_path_length_mismatch")
        return path_output([
            ForecastOutput({}, None, "point", None, point=float(value)) for value in values
        ], horizon)
