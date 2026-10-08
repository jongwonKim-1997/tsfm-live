from .base import ModelAdapter, checked_context, output_from_samples, seed_torch


AUDITED_REVISION = "3212e42564493f520593e5414af4367fc4b49226"


class SundialAdapter(ModelAdapter):
    def predict(self, context, quantiles, seed):
        if (self.config["hf_revision"] != AUDITED_REVISION
                or self.config.get("remote_code_audit") != "sundial-2026-10-08"):
            raise RuntimeError("remote_code_revision_not_audited")
        x = checked_context(context)
        torch = seed_torch(seed)
        if self._model is None:
            self.check_package()
            from transformers import AutoModelForCausalLM
            self._model = AutoModelForCausalLM.from_pretrained(
                self.config["hf_repo"], trust_remote_code=True,
                code_revision=AUDITED_REVISION, torch_dtype=torch.float32,
                **self.hf_kwargs(),
            ).to(self.device(torch)).eval()
        seed_torch(seed)
        n = max(1000, self.config.get("n_samples") or 1000)
        series = torch.tensor(x, dtype=torch.float32, device=self.device(torch))[None, :]
        samples = []
        with torch.inference_mode():
            for start in range(0, n, 50):
                result = self._model.generate(series, max_new_tokens=1, num_samples=min(50, n - start))
                samples.append(result[0, :, 0].detach().cpu().numpy())
        import numpy as np
        return output_from_samples(np.concatenate(samples), quantiles)
