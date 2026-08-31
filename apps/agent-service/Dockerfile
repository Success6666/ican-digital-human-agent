FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=0 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8

WORKDIR /app
COPY requirements-container.txt ./
COPY constraints-cpu.txt ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        --constraint constraints-cpu.txt \
        --requirement requirements-container.txt
COPY app ./app
COPY tests ./tests

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
