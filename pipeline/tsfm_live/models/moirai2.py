from .base import ModelAdapter, checked_context, checked_horizon, output_from_quantiles, path_output, seed_torch


class Moirai2Adapter(ModelAdapter):
    def predict(self, context, quantiles, seed, *, horizon=1):
        horizon = checked_horizon(horizon)
        x = checked_context(context)
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            from uni2ts.model.moirai2 import Moirai2Forecast, Moirai2Module
            module = Moirai2Module.from_pretrained(self.config["hf_repo"], **self.hf_kwargs())
            self._model = Moirai2Forecast(
                module=module, prediction_length=horizon, context_length=len(x),
                target_dim=1, feat_dynamic_real_dim=0, past_feat_dynamic_real_dim=0,
            ).to(self.device(torch)).eval()
        with torch.inference_mode(), self._model.hparams_context(context_length=len(x), prediction_length=horizon):
            result = self._model.predict([x])  # batch, quantiles, horizon; univariate target squeezed
        return path_output([output_from_quantiles(self._model.module.quantile_levels, result[0, :, step], quantiles)
                            for step in range(horizon)], horizon)
