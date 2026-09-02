FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8

WORKDIR /app
COPY requirements.txt ./
RUN pip3 install --upgrade pip \
    && pip3 install -r requirements.txt
COPY app.py ./

ENV ASR_MODEL_DIR=/models \
    ASR_MODEL_SIZE=tiny \
    ASR_DEVICE=auto \
    ASR_COMPUTE_TYPE=auto \
    ASR_LANGUAGE=zh \
    ASR_BEAM_SIZE=1 \
    ASR_MAX_AUDIO_BYTES=10485760

EXPOSE 7000
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7000"]
