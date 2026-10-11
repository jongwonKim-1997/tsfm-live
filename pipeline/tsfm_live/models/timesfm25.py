from .base import ModelAdapter, checked_context, checked_horizon, output_from_quantiles, path_output, seed_torch


class TimesFMAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed, *, horizon=1):
        horizon = checked_horizon(horizon)
        x = checked_context(context)
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            import timesfm
            self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                self.config["hf_repo"], torch_compile=False, **self.hf_kwargs(),
            )
            # Official package auto-selects hardware at construction. Explicitly
            # move its module and update its batching metadata for CPU default.
            self._model.model.device = torch.device(self.device(torch))
            self._model.model.device_count = 1
            self._model.model.to(self._model.model.device)
            self._model.compile(timesfm.ForecastConfig(
                max_context=512, max_horizon=128, per_core_batch_size=1,
                normalize_inputs=True, use_continuous_quantile_head=True,
                force_flip_invariance=True, infer_is_positive=False,
                fix_quantile_crossing=True,
            ))
        with torch.inference_mode():
            _, q = self._model.forecast(horizon=horizon, inputs=[x])
        # The first tuple element is the median (channel 5). The full head's
        # channel 0 is the separately trained mean; channels 1: are q0.1..q0.9.
        return path_output([output_from_quantiles([i / 10 for i in range(1, 10)], q[0, step, 1:],
                                                  quantiles, mean=q[0, step, 0])
                            for step in range(horizon)], horizon)
