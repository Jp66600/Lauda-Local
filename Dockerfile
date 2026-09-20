# Vellum - imagem opcional (CPU).
# O MVP NAO exige Docker; isto existe para quem quer isolar o ambiente.
#
# Build:
#   docker build -t vellum .
#
# Uso (monte a midia, a saida e o cache de modelos):
#   docker run --rm \
#     -v "$PWD/midia:/data:ro" \
#     -v "$PWD/saida:/saida" \
#     -v "$PWD/models:/app/models" \
#     vellum run /data/entrevista.mp4 -m small -o /saida
#
# UI (http://127.0.0.1:7860):
#   docker run --rm -p 7860:7860 -v "$PWD/models:/app/models" \
#     vellum ui --share
#
# GPU NVIDIA: troque a base por nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04,
# instale python3.12 e rode com --gpus all.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VELLUM_MODELS_DIR=/app/models \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1

# ffmpeg e ffprobe sao dependencias de sistema, nao Python.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt pyproject.toml README.md ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
RUN pip install --no-deps -e . && mkdir -p /app/models /saida

# Modelos ficam em volume: a imagem nao carrega pesos.
VOLUME ["/app/models", "/saida"]
EXPOSE 7860

ENTRYPOINT ["vellum"]
CMD ["--help"]
