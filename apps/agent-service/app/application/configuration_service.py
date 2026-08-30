"""Expose a non-sensitive runtime configuration view for operators."""

from __future__ import annotations

import asyncio
from typing import Any

from ..observability.service import ObservabilityService
from ..rag.service import RagService
from ..avatar.registry import ProviderRegistry
from ..settings import Settings
from ..infrastructure.runtime_configuration import MofaRuntimeConfiguration, RuntimeConfiguration, RuntimeConfigurationRepository, apply_mofa_environment


class ConfigurationApplicationService:
    def __init__(
        self,
        *,
        settings: Settings,
        providers: ProviderRegistry,
        rag: RagService,
        observability: ObservabilityService,
        store: Any,
        cleanup: Any,
        repository: RuntimeConfigurationRepository,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.rag = rag
        self.observability = observability
        self.store = store
        self.cleanup = cleanup
        self.repository = repository
        self._update_lock = asyncio.Lock()

    async def view(self) -> dict[str, Any]:
        provider_health = await self.providers.health()
        parser = getattr(self.rag.parser, "config", None)
        return {
            "environment": self.settings.environment,
            "defaultProvider": self.settings.default_provider,
            "session": {
                "ttlSeconds": self.settings.session_ttl_seconds,
                "cleanupIntervalSeconds": self.settings.cleanup_interval_seconds,
            },
            "llm": {
                "mode": "deterministic-fallback",
                "configured": False,
                "detail": "未配置业务模型，当前使用可验收的确定性响应器",
            },
            "embedding": {
                "provider": "hash-local",
                "configured": True,
                "detail": "本地特征哈希向量，后续可替换为远程 Embedding 服务",
            },
            "rag": {
                "parser": "Docling",
                "enabled": bool(getattr(parser, "enabled", True)),
                "artifactsConfigured": bool(getattr(parser, "artifacts_path", None)),
                "ocrBackend": getattr(parser, "ocr_backend", "auto"),
                "ocrLanguages": list(getattr(parser, "ocr_languages", ())),
                "tableMode": getattr(parser, "table_mode", "accurate"),
                "localModels": _docling_models(parser),
                "maxDocumentBytes": self.settings.rag_max_document_bytes,
                "maxMetadataBytes": self.settings.rag_max_metadata_bytes,
                "maxMetadataItems": self.settings.rag_max_metadata_items,
                "maxMetadataDepth": self.settings.rag_max_metadata_depth,
            },
            "mcp": {
                "maxResultBytes": self.settings.mcp_max_result_bytes,
                "maxResultItems": self.settings.mcp_max_result_items,
                "maxResultDepth": self.settings.mcp_max_result_depth,
                "localFallback": self.settings.mcp_allow_local_fallback,
            },
            "observability": self.observability.health().model_dump(mode="json"),
            "mofa": _mofa_view(self.settings),
            "providers": [item.model_dump(mode="json") for item in provider_health],
            "runtimeEditable": [
                "defaultProvider",
                "session.ttlSeconds",
                "session.cleanupIntervalSeconds",
                "mofa.enabled",
                "mofa.appId",
                "mofa.appSecret",
                "mofa.authorization",
                "mofa.gatewayUrl",
                "mofa.sdkUrl",
                "mofa.cryptoUrl",
            ],
        }

    async def update(self, payload: Any) -> dict[str, Any]:
        async with self._update_lock:
            current = RuntimeConfiguration.from_settings(self.settings)
            changes: dict[str, Any] = {}
            if payload.default_provider is not None:
                changes["default_provider"] = payload.default_provider
            if payload.session is not None:
                if payload.session.ttl_seconds is not None:
                    changes["session_ttl_seconds"] = payload.session.ttl_seconds
                if payload.session.cleanup_interval_seconds is not None:
                    changes["cleanup_interval_seconds"] = payload.session.cleanup_interval_seconds
            if payload.mofa is not None:
                current_mofa = current.mofa
                next_mofa = current_mofa.model_copy(update=payload.mofa.model_dump(exclude_none=True, by_alias=False))
                changes["mofa"] = next_mofa
            next_configuration = current.model_copy(update=changes)

            if next_configuration.default_provider not in self.providers.names():
                raise ValueError(f"未找到 Provider {next_configuration.default_provider}")
            provider = self.providers.get(next_configuration.default_provider)
            health = await provider.health()
            if not health.configured or health.status in {"unavailable", "error"}:
                raise ValueError(f"Provider {next_configuration.default_provider} 当前不可用")

            self.repository.save(next_configuration)
            self.settings.default_provider = next_configuration.default_provider
            self.settings.session_ttl_seconds = next_configuration.session_ttl_seconds
            self.settings.session_idle_timeout_seconds = next_configuration.session_ttl_seconds
            self.settings.cleanup_interval_seconds = next_configuration.cleanup_interval_seconds
            self.store.ttl_seconds = next_configuration.session_ttl_seconds
            self.store.idle_timeout_seconds = next_configuration.session_ttl_seconds
            self.cleanup.interval_seconds = next_configuration.cleanup_interval_seconds
            self.providers.set_session_ttl(next_configuration.session_ttl_seconds)
            apply_mofa_environment(next_configuration.mofa)
            mofa_provider = self.providers.get("mofa")
            if hasattr(mofa_provider, "enabled"):
                mofa_provider.enabled = next_configuration.mofa.enabled
            return await self.view()


def _docling_models(parser: Any) -> list[str]:
    """Return a human-readable list of the enabled local parsing models."""

    if parser is None or not getattr(parser, "enabled", True):
        return ["未启用本地 Docling 模型"]
    models = ["Layout Heron"]
    if getattr(parser, "do_table_structure", True):
        mode = "accurate" if getattr(parser, "table_mode", "accurate") == "accurate" else "fast"
        models.append(f"TableFormer（{mode}）")
    if getattr(parser, "do_ocr", True):
        backend = str(getattr(parser, "ocr_backend", "onnxruntime")).upper()
        languages = "、".join(getattr(parser, "ocr_languages", ())) or "默认语言"
        models.append(f"RapidOCR / {backend}（{languages}）")
    return models


def _mofa_view(settings: Settings) -> dict[str, Any]:
    app_id = getattr(settings, "mofa_app_id", None) or __import__("os").getenv("MOFA_APP_ID", "")
    app_secret = getattr(settings, "mofa_app_secret", None) or __import__("os").getenv("MOFA_APP_SECRET", "")
    configured = bool(app_id and app_secret)
    return {
        "enabled": __import__("os").getenv("MOFA_AVATAR_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
        "configured": configured,
        "appId": _mask(app_id),
        "appSecret": "已配置" if app_secret else "未配置",
        "authorization": _mask(__import__("os").getenv("MOFA_AUTHORIZATION", "")),
        "gatewayUrl": __import__("os").getenv("MOFA_GATEWAY_URL", "") or "星云默认网关",
        "sdkUrl": __import__("os").getenv("MOFA_SDK_URL", "") or "星云官方 SDK",
        "cryptoUrl": __import__("os").getenv("MOFA_CRYPTO_URL", "") or "CryptoJS 官方 CDN",
        "detail": "凭证由服务端托管，浏览器只接收短时会话参数",
    }


def _mask(value: str) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••{value[-4:]}"
