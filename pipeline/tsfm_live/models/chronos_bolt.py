from .base import ModelAdapter, checked_context, output_from_quantiles, seed_torch


class ChronosBoltAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed):
        x = checked_context(context)
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            from chronos import BaseChronosPipeline
            self._model = BaseChronosPipeline.from_pretrained(
                self.config["hf_repo"], device_map=self.device(torch),
                torch_dtype=torch.float32, **self.hf_kwargs(),
            )
        with torch.inference_mode():
            q, _ = self._model.predict_quantiles(
                torch.tensor(x, dtype=torch.float32), prediction_length=1,
                quantile_levels=list(self._model.quantiles),
            )
        return output_from_quantiles(self._model.quantiles, q[0, 0], quantiles)
