"""Local Chinese ASR service backed by faster-whisper."""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel


@dataclass(frozen=True)
class AsrSettings:
    model_size: str = os.getenv("ASR_MODEL_SIZE", "tiny").strip() or "tiny"
    model_dir: str = os.getenv("ASR_MODEL_DIR", "/models").strip() or "/models"
    requested_device: str = os.getenv("ASR_DEVICE", "auto").strip().lower() or "auto"
    requested_compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "auto").strip().lower() or "auto"
    language: str = os.getenv("ASR_LANGUAGE", "zh").strip().lower() or "zh"
    beam_size: int = max(1, int(os.getenv("ASR_BEAM_SIZE", "1")))
    max_audio_bytes: int = max(640, int(os.getenv("ASR_MAX_AUDIO_BYTES", "10485760")))
    api_key: str = os.getenv("ASR_INTERNAL_TOKEN", "").strip()


class AsrEngine:
    def __init__(self, settings: AsrSettings) -> None:
        self.settings = settings
        self._model: WhisperModel | None = None
        self._device = "unloaded"
        self._compute_type = "unloaded"
        self._load_error: str | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            attempts: list[tuple[str, str]] = []
            if self.settings.requested_device in {"auto", "cuda", "gpu"}:
                compute = self.settings.requested_compute_type
                attempts.append(("cuda", "float16" if compute in {"", "auto"} else compute))
            if self.settings.requested_device in {"auto", "cpu"}:
                compute = self.settings.requested_compute_type
                attempts.append(("cpu", "int8" if compute in {"", "auto", "float16", "int8_float16"} else compute))
            if not attempts:
                attempts.append(("cpu", "int8"))
            errors: list[str] = []
            for device, compute_type in attempts:
                try:
                    self._model = WhisperModel(
                        self.settings.model_size,
                        device=device,
                        compute_type=compute_type,
                        download_root=self.settings.model_dir,
                    )
                    self._device = device
                    self._compute_type = compute_type
                    self._load_error = None
                    return
                except Exception as exc:  # GPU libraries may be unavailable; CPU is the fallback.
                    errors.append(f"{device}/{compute_type}: {type(exc).__name__}: {exc}")
            self._load_error = "；".join(errors)[-2_000:]
            raise RuntimeError(f"ASR 模型加载失败：{self._load_error}")

    async def transcribe(self, pcm: bytes) -> str:
        if len(pcm) > self.settings.max_audio_bytes:
            raise ValueError("音频超过 ASR 大小限制")
        if len(pcm) % 2:
            raise ValueError("PCM16 音频长度必须为偶数")
        if not pcm:
            return ""
        await asyncio.to_thread(self.load)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        # 单实例串行推理，避免并发请求争抢模型显存并造成尾延迟抖动。
        async with self._inference_lock:
            try:
                segments, _ = await asyncio.to_thread(self._transcribe_sync, samples)
            except Exception:
                # CTranslate2 可能在首次真正推理时才发现 CUDA 动态库缺失。
                # auto 模式切换 CPU 并重试当前 utterance，避免返回一次性 503。
                if self._device != "cuda" or self.settings.requested_device != "auto":
                    raise
                await asyncio.to_thread(self._fallback_to_cpu)
                segments, _ = await asyncio.to_thread(self._transcribe_sync, samples)
        return "".join(segment.text for segment in segments).strip()

    def _fallback_to_cpu(self) -> None:
        old_model = self._model
        self._model = None
        self._device = "unloaded"
        self._compute_type = "unloaded"
        del old_model
        cpu_compute = "int8" if self.settings.requested_compute_type in {"", "auto", "float16", "int8_float16"} else self.settings.requested_compute_type
        self._model = WhisperModel(
            self.settings.model_size,
            device="cpu",
            compute_type=cpu_compute,
            download_root=self.settings.model_dir,
        )
        self._device = "cpu"
        self._compute_type = cpu_compute
        self._load_error = "CUDA 运行库不可用，已自动回退 CPU"

    def _transcribe_sync(self, samples: np.ndarray) -> tuple[list[Any], Any]:
        if self._model is None:
            raise RuntimeError("ASR 模型尚未加载")
        segments, info = self._model.transcribe(
            samples,
            language=self.settings.language,
            task="transcribe",
            beam_size=self.settings.beam_size,
            best_of=1,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 250},
            condition_on_previous_text=False,
        )
        return list(segments), info

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "local-asr",
            "model": self.settings.model_size,
            "language": self.settings.language,
            "device": self._device,
            "computeType": self._compute_type,
            "modelLoaded": self.loaded,
            "loadError": self._load_error,
        }


settings = AsrSettings()
engine = AsrEngine(settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Warm the model without blocking the HTTP server startup thread.
    asyncio.create_task(asyncio.to_thread(_warm_model))
    yield


def _warm_model() -> None:
    try:
        engine.load()
    except Exception:
        # The next request retries loading, including CPU fallback.
        return


app = FastAPI(title="Local Chinese ASR", version="0.1.53", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return engine.status()


@app.post("/transcribe")
async def transcribe(request: Request) -> JSONResponse:
    if settings.api_key:
        authorization = request.headers.get("authorization", "")
        if authorization != f"Bearer {settings.api_key}":
            return JSONResponse({"error": "asr_unauthorized"}, status_code=401)
    body = await request.body()
    try:
        text = await engine.transcribe(body)
    except ValueError as exc:
        return JSONResponse({"error": "asr_invalid_audio", "detail": str(exc)}, status_code=413)
    except Exception as exc:
        return JSONResponse({"error": "asr_unavailable", "detail": str(exc)[-500:]}, status_code=503)
    return JSONResponse({"text": text, "language": settings.language, "device": engine._device})


__all__ = ["app"]
