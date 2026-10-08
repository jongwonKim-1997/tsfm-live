# Build on linux/amd64. Public base manifests verified 2026-10-08.
FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS node
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG CODE_REVISION
ENV TSFM_CODE_REVISION=${CODE_REVISION} \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy \
    TSFM_LIVE_ENABLED=0 \
    HF_HUB_OFFLINE=1 \
    TSFM_DEVICE=cpu \
    TSFM_CACHE_DIR=/scratch/cache \
    HF_HOME=/scratch/huggingface \
    TSFM_PYTHON_CHRONOS=/app/model_envs/chronos/.venv/bin/python \
    TSFM_PYTHON_TIMESFM=/app/model_envs/timesfm/.venv/bin/python \
    TSFM_PYTHON_MOIRAI=/app/model_envs/moirai/.venv/bin/python \
    TSFM_PYTHON_TOTO=/app/model_envs/toto/.venv/bin/python \
    TSFM_PYTHON_TIREX=/app/model_envs/tirex/.venv/bin/python \
    TSFM_PYTHON_SUNDIAL=/app/model_envs/sundial/.venv/bin/python \
    TSFM_OTS_EXECUTABLE=/app/model_envs/ots/.venv/bin/ots
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install --no-install-recommends -y git ca-certificates curl libgomp1 libssl3 fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.12.23 \
    && curl -fsSL https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_linux_amd64.tar.gz -o /tmp/gh.tar.gz \
    && echo 'bb766f710eef8ede859c18578c72c327597cd4c8a85b06001b1f3843c6019386  /tmp/gh.tar.gz' | sha256sum -c - \
    && tar -xzf /tmp/gh.tar.gz -C /tmp \
    && cp /tmp/gh_2.102.0_linux_amd64/bin/gh /usr/local/bin/gh \
    && rm -rf /tmp/gh.tar.gz /tmp/gh_2.102.0_linux_amd64
WORKDIR /app
COPY pipeline /app/pipeline
COPY model_envs /app/model_envs
COPY site/package.json site/package-lock.json /app/site/
COPY ops /app/ops
RUN test -n "$CODE_REVISION" \
    && uv sync --project pipeline --frozen --no-dev \
    && uv python install 3.11.17 \
    && for profile in chronos timesfm moirai toto tirex sundial ots; do \
         uv sync --project "model_envs/$profile" --python 3.11.17 --frozen --no-dev || exit $?; \
       done \
    && npm ci --prefix /app/site --omit=dev \
    && uv cache clean
ENV PATH=/app/pipeline/.venv/bin:${PATH}
ENTRYPOINT ["python", "/app/ops/runtime.py"]
