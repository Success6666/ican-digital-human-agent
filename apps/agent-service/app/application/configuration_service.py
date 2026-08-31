"""Expose a non-sensitive runtime configuration view for operators."""

from __future__ import annotations

import asyncio
from typing import Any

from ..observability.service import ObservabilityService
from ..rag.service import RagService
from ..avatar.registry import ProviderRegistry
from ..settings import Settings
from ..infrastructure.runtime_configuration import (
    RuntimeConfiguration,
    RuntimeConfigurationRepository,
    apply_aliyun_environment,
    apply_iflytek_environment,
    apply_mofa_environment,
)


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
        initial_configuration: RuntimeConfiguration | None = None,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.rag = rag
        self.observability = observability
        self.store = store
        self.cleanup = cleanup
        self.repository = repository
        self._configuration = initial_configuration or repository.load(settings)
        self._update_lock = asyncio.Lock()

    async def view(self) -> dict[str, Any]:
        provider_health = await self.providers.health()
        parser = getattr(self.rag.parser, "config", None)
        configuration = self._configuration
        return {
            "environment": self.settings.environment,
            "defaultProvider": configuration.default_provider,
            "session": {
                "ttlSeconds": configuration.session_ttl_seconds,
                "cleanupIntervalSeconds": configuration.cleanup_interval_seconds,
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
                "storage": "SQLite 持久化向量索引",
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
            "mofa": _mofa_view(configuration.mofa),
            "aliyun": _aliyun_view(configuration.aliyun),
            "iflytek": _iflytek_view(configuration.iflytek),
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
                "aliyun.enabled",
                "aliyun.baseUrl",
                "aliyun.appId",
                "aliyun.instanceId",
                "aliyun.accessKeyId",
                "aliyun.accessKeySecret",
                "iflytek.enabled",
                "iflytek.gatewayUrl",
                "iflytek.appId",
                "iflytek.apiKey",
                "iflytek.apiSecret",
            ],
        }

    async def update(self, payload: Any) -> dict[str, Any]:
        async with self._update_lock:
            current = self._configuration
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
            if payload.aliyun is not None:
                current_aliyun = current.aliyun
                changes["aliyun"] = current_aliyun.model_copy(update=payload.aliyun.model_dump(exclude_none=True, by_alias=False))
            if payload.iflytek is not None:
                current_iflytek = current.iflytek
                changes["iflytek"] = current_iflytek.model_copy(update=payload.iflytek.model_dump(exclude_none=True, by_alias=False))
            next_configuration = current.model_copy(update=changes)

            _validate_provider_credentials(next_configuration)

            if next_configuration.default_provider not in self.providers.names():
                raise ValueError(f"未找到 Provider {next_configuration.default_provider}")
            provider = self.providers.get(next_configuration.default_provider)
            health = await provider.health()
            if not health.configured or health.status in {"unavailable", "error"}:
                raise ValueError(f"Provider {next_configuration.default_provider} 当前不可用")

            self.repository.save(next_configuration)
            self._configuration = next_configuration
            self.settings.default_provider = next_configuration.default_provider
            self.settings.session_ttl_seconds = next_configuration.session_ttl_seconds
            self.settings.session_idle_timeout_seconds = next_configuration.session_ttl_seconds
            self.settings.cleanup_interval_seconds = next_configuration.cleanup_interval_seconds
            self.store.ttl_seconds = next_configuration.session_ttl_seconds
            self.store.idle_timeout_seconds = next_configuration.session_ttl_seconds
            self.cleanup.interval_seconds = next_configuration.cleanup_interval_seconds
            self.providers.set_session_ttl(next_configuration.session_ttl_seconds)
            apply_mofa_environment(next_configuration.mofa)
            apply_aliyun_environment(next_configuration.aliyun)
            apply_iflytek_environment(next_configuration.iflytek)
            mofa_provider = self.providers.get("mofa")
            if hasattr(mofa_provider, "enabled"):
                mofa_provider.enabled = next_configuration.mofa.enabled
            for name, enabled in (("aliyun", next_configuration.aliyun.enabled), ("iflytek", next_configuration.iflytek.enabled)):
                provider_instance = self.providers.get(name)
                if hasattr(provider_instance, "enabled"):
                    provider_instance.enabled = enabled
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


def _mofa_view(configuration: Any) -> dict[str, Any]:
    app_id = configuration.app_id
    app_secret = configuration.app_secret
    configured = bool(app_id and app_secret)
    return {
        "enabled": configuration.enabled,
        "configured": configured,
        "appId": _mask(app_id),
        "appSecret": "已配置" if app_secret else "未配置",
        "authorization": _mask(configuration.authorization),
        "gatewayUrl": configuration.gateway_url or "星云默认网关",
        "sdkUrl": configuration.sdk_url or "星云官方 SDK",
        "cryptoUrl": configuration.crypto_url or "CryptoJS 官方 CDN",
        "detail": "凭证由服务端托管，浏览器只接收短时会话参数",
    }


def _aliyun_view(configuration: Any) -> dict[str, Any]:
    app_id = configuration.app_id
    instance_id = configuration.instance_id
    access_key = configuration.access_key_id
    secret = configuration.access_key_secret
    return {
        "enabled": configuration.enabled,
        "configured": bool(access_key and secret),
        "baseUrl": configuration.base_url or "阿里云默认网关",
        "appId": _mask(app_id),
        "instanceId": _mask(instance_id),
        "accessKeyId": _mask(access_key),
        "accessKeySecret": "已配置" if secret else "未配置",
        "detail": "长期密钥仅保存在服务端，浏览器不接收完整凭证",
    }


def _iflytek_view(configuration: Any) -> dict[str, Any]:
    app_id = configuration.app_id
    api_key = configuration.api_key
    secret = configuration.api_secret
    return {
        "enabled": configuration.enabled,
        "configured": bool(app_id and api_key and secret),
        "gatewayUrl": configuration.gateway_url or "讯飞默认网关",
        "appId": _mask(app_id),
        "apiKey": _mask(api_key),
        "apiSecret": "已配置" if secret else "未配置",
        "detail": "应用凭证由服务端托管，前端只显示配置状态",
    }


def _mask(value: str) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••{value[-4:]}"


def _validate_provider_credentials(configuration: RuntimeConfiguration) -> None:
    if configuration.aliyun.enabled and not (
        configuration.aliyun.access_key_id and configuration.aliyun.access_key_secret
    ):
        raise ValueError("启用阿里云数字人前必须填写 AccessKey ID 和 AccessKey Secret")
    if configuration.mofa.enabled and not (configuration.mofa.app_id and configuration.mofa.app_secret):
        raise ValueError("启用魔珐星云前必须填写 App ID 和 App Secret")
    if configuration.iflytek.enabled and not (
        configuration.iflytek.app_id and configuration.iflytek.api_key and configuration.iflytek.api_secret
    ):
        raise ValueError("启用讯飞数字人前必须填写 App ID、API Key 和 API Secret")
