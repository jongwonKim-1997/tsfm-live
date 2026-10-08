from .base import ModelAdapter, checked_context, output_from_quantiles, seed_torch


class TiRexAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed):
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
            q, _ = self._model.forecast(context=x, prediction_length=1, batch_size=1, output_type="numpy")
        return output_from_quantiles(self._model.config.quantiles, q[0, 0], quantiles)
