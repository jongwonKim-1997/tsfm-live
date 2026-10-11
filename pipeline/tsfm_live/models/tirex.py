from .base import ModelAdapter, checked_context, checked_horizon, output_from_quantiles, path_output, seed_torch


class TiRexAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed, *, horizon=1):
        horizon = checked_horizon(horizon)
        x = checked_context(context)
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            from tirex import load_model
            self._model = load_model(
                self.config["hf_repo"], device=self.device(torch), backend="torch",
                compile=False, hf_kwargs=self.hf_kwargs(),
            ).eval()
        with torch.inference_mode():
            q, _ = self._model.forecast(context=x, prediction_length=horizon, batch_size=1, output_type="numpy")
        return path_output([output_from_quantiles(self._model.config.quantiles, q[0, step], quantiles)
                            for step in range(horizon)], horizon)
