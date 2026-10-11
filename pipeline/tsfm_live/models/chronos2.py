from .base import ModelAdapter, checked_context, checked_horizon, output_from_quantiles, path_output, seed_torch


class Chronos2Adapter(ModelAdapter):
    def predict(self, context, quantiles, seed, *, horizon=1):
        horizon = checked_horizon(horizon)
        x = checked_context(context)
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            from chronos import Chronos2Pipeline
            self._model = Chronos2Pipeline.from_pretrained(
                self.config["hf_repo"], device_map=self.device(torch),
                torch_dtype=torch.float32, **self.hf_kwargs(),
            )
        with torch.inference_mode():
            # Native head only: package interpolation clamps tails, whereas the
            # protocol requires linear tail extrapolation if outside its grid.
            q, _ = self._model.predict_quantiles(
                [torch.tensor(x, dtype=torch.float32)], prediction_length=horizon,
                quantile_levels=list(self._model.quantiles), cross_learning=False,
            )
        # Upstream calls a median "mean"; do not relabel it as an expectation.
        return path_output([output_from_quantiles(self._model.quantiles, q[0][0, step], quantiles)
                            for step in range(horizon)], horizon)
