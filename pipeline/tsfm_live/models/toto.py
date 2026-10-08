from .base import ModelAdapter, checked_context, output_from_samples, seed_torch


class TotoAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed):
        x = checked_context(context)
        torch = seed_torch(seed)
        from toto.data.util.dataset import MaskedTimeseries
        from toto.inference.forecaster import TotoForecaster
        if self._model is None:
            self.check_package()
            from toto.model.toto import Toto
            self._model = Toto.from_pretrained(self.config["hf_repo"], **self.hf_kwargs()).to(self.device(torch)).eval()
        # Model construction initializes parameters before loading weights and
        # consumes RNG state. Isolate sampling from cold-versus-warm loading.
        seed_torch(seed)
        series = torch.tensor(x, dtype=torch.float32, device=self.device(torch))[None, :]
        inputs = MaskedTimeseries(
            series=series, padding_mask=torch.ones_like(series, dtype=torch.bool),
            id_mask=torch.zeros_like(series), timestamp_seconds=torch.zeros_like(series),
            time_interval_seconds=torch.full((1,), 86400, device=series.device),
        )
        n = max(1000, self.config.get("n_samples") or 1000)
        with torch.inference_mode():
            forecast = TotoForecaster(self._model.model).forecast(
                inputs, prediction_length=1, num_samples=n, samples_per_batch=50,
            )
        return output_from_samples(forecast.samples[0, 0, 0, :], quantiles)
