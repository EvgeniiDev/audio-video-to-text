# Layer order (bottom-up), each invalidated only by its own change:
#   base (OS + ffmpeg) -> weights (~422MB ckpt) -> torch -> pydeps -> runtime (src/)
# Editing src/ rebuilds only the last layer (seconds).
# Bumping requirements.txt rebuilds pydeps+runtime, weights/OS come from cache.
ARG PYTHON_IMAGE=python:3.14-slim

# ---- base: OS deps, rebuilt almost never ----
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg curl ca-certificates tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
 && useradd -m app && mkdir -p /app/data /models /pkg \
 && chown app:app /app/data /models

# ---- weights: model ckpt, plain ADD download (md5-checked) ----
FROM base AS weights
ARG MODEL_NAME=v3_e2e_ctc
ARG GIGAAM_CDN=https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM
# md5 from GigaAM/gigaam/__init__.py::_MODEL_HASHES
ARG MODEL_MD5=367074d6498f426d960b25f49531cf68
ENV MODEL_NAME=${MODEL_NAME} GIGAAM_CDN=${GIGAAM_CDN} MODEL_MD5=${MODEL_MD5}
ADD ${GIGAAM_CDN}/${MODEL_NAME}.ckpt /models/${MODEL_NAME}.ckpt
ADD ${GIGAAM_CDN}/${MODEL_NAME}_tokenizer.model /models/${MODEL_NAME}_tokenizer.model
RUN echo "${MODEL_MD5}  /models/${MODEL_NAME}.ckpt" | md5sum -c - \
 && ls -la /models

# ---- torch: heavy CPU wheels, change only on torch bump ----
FROM weights AS torch
ARG TORCH_VER=2.9.1+cpu
ENV TORCH_VER=${TORCH_VER}
RUN pip install --prefix=/pkg --no-warn-script-location \
      --index-url https://download.pytorch.org/whl/cpu \
      torch==${TORCH_VER} torchaudio==${TORCH_VER}
ENV PYTHONPATH=/pkg/lib/python3.14/site-packages PATH=/pkg/bin:$PATH

# ---- pydeps: PyPI packages + upstream GigaAM code ----
FROM torch AS pydeps
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ARG GIGAAM_REF=main
ENV GIGAAM_REF=${GIGAAM_REF}
WORKDIR /build
COPY requirements.txt ./
# NOTE: silero-vad --no-deps: its torch pin (<2.10) conflicts with CPU
# torch 2.9.1; runtime only needs torch+torchaudio already installed above.
RUN pip install --prefix=/pkg --no-warn-script-location \
      --no-deps silero-vad==6.2.2 \
 && pip install --prefix=/pkg --no-warn-script-location -r requirements.txt \
 && git clone --depth 1 --branch "$GIGAAM_REF" \
      https://github.com/salute-developers/GigaAM /build/GigaAM \
 && pip install --prefix=/pkg --no-warn-script-location --no-deps /build/GigaAM \
 && python -c "import gigaam; print('gigaam OK')"

# ---- runtime: our code only ----
FROM base AS runtime
COPY --from=pydeps /pkg /pkg
COPY --from=weights /models /models
ENV PYTHONPATH=/pkg/lib/python3.14/site-packages PATH=/pkg/bin:$PATH \
    GIGAAM_CACHE=/models MODEL_NAME=v3_e2e_ctc \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY src/ ./src/
COPY static/ ./static/
COPY docker-entrypoint.sh ./
# /models baked read-only; external mount may be root-owned -> app must write.
# /app/data is a host bind (owner varies). Fix perms at start as root below.
RUN chmod 755 /app /app/data && chmod +x docker-entrypoint.sh
VOLUME ["/app/data"]
EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s \
  CMD curl -sf http://127.0.0.1:8099/jobs || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8099", "--workers", "1"]
