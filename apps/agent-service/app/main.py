"""FastAPI application factory for the agent service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .api.body_limit import RequestBodyLimitMiddleware
from .api.inflight_limit import InFlightLimitMiddleware
from .application.chat_service import ChatApplicationService
from .application.cleanup import CleanupWorker
from .application.configuration_service import ConfigurationApplicationService
from .application.provider_service import ProviderApplicationService
from .application.session_service import SessionApplicationService
from .avatar.registry import ProviderRegistry, build_default_registry
from .evaluation.service import EvaluationService
from .evaluation.runner import EvaluationDatasetRunner
from .graph.runtime import AgentGraphRuntime
from .infrastructure.redis_session_store import RedisSessionStore
from .infrastructure.profile_store import AccountPreferenceStore
from .infrastructure.response_cache import ResponseCache
from .infrastructure.session_store import InMemorySessionStore
from .infrastructure.runtime_configuration import (
    RuntimeConfigurationRepository,
    apply_aliyun_environment,
    apply_iflytek_environment,
    apply_mofa_environment,
    apply_docling_environment,
    apply_embedding_environment,
    apply_futureagi_environment,
    apply_llm_environment,
)
from .mcp.client import CompositeToolClient, LocalToolClient, StreamableHttpToolClient
from .mcp.limits import ToolResultLimiter
from .llm.client import OpenAICompatibleLlm
from .messaging import ReliableMessageBus
from .observability.service import ObservabilityService, build_default_observability
from .rag.service import RagService, build_default_rag_service
from .realtime.audio import MockPcmIngress
from .realtime.limits import RealtimeLimits
from .realtime.media import HttpAsrIngress, HttpTtsOutput, NullAudioOutput
from .realtime.router import router as realtime_router
from .settings import Settings, get_settings


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    providers: ProviderRegistry
    store: Any
    session_service: SessionApplicationService
    provider_service: ProviderApplicationService
    tool_client: CompositeToolClient
    rag: RagService
    observability: ObservabilityService
    graph: AgentGraphRuntime
    llm: OpenAICompatibleLlm
    chat_service: ChatApplicationService
    configuration_service: ConfigurationApplicationService
    evaluation: EvaluationService
    evaluation_runner: EvaluationDatasetRunner
    cleanup: CleanupWorker
    realtime_limits: RealtimeLimits
    message_bus: ReliableMessageBus
    audio_ingress: Any
    audio_output: Any
    profile_store: AccountPreferenceStore
    response_cache: ResponseCache | None


def build_container(
    settings: Settings | None = None,
    *,
    providers: ProviderRegistry | None = None,
    tool_client: CompositeToolClient | None = None,
) -> ServiceContainer:
    settings = settings or get_settings()
    repository = RuntimeConfigurationRepository(settings.runtime_configuration_file)
    persisted = repository.load(settings)
    apply_aliyun_environment(persisted.aliyun)
    apply_mofa_environment(persisted.mofa)
    apply_iflytek_environment(persisted.iflytek)
    apply_llm_environment(persisted.llm)
    apply_embedding_environment(persisted.embedding)
    apply_docling_environment(persisted.docling)
    apply_futureagi_environment(persisted.futureagi)
    settings.provider_enabled["aliyun"] = persisted.aliyun.enabled
    settings.provider_enabled["mofa"] = persisted.mofa.enabled
    settings.provider_enabled["iflytek"] = persisted.iflytek.enabled
    settings.default_provider = persisted.default_provider
    settings.session_ttl_seconds = persisted.session_ttl_seconds
    settings.session_idle_timeout_seconds = persisted.session_ttl_seconds
    settings.cleanup_interval_seconds = persisted.cleanup_interval_seconds
    providers = providers or build_default_registry(settings)
    realtime_limits = RealtimeLimits(
        heartbeat_interval_seconds=float(settings.session_heartbeat_interval_seconds),
        idle_timeout_seconds=settings.realtime_idle_timeout_seconds,
        handshake_timeout_seconds=settings.realtime_handshake_timeout_seconds,
        interrupt_timeout_seconds=settings.realtime_interrupt_timeout_seconds,
    )
    store_kwargs = dict(
        ttl_seconds=settings.session_ttl_seconds,
        max_sessions=settings.session_max_sessions,
        cleanup_batch_size=settings.session_cleanup_batch_size,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
    )
    if settings.session_store_backend.strip().casefold() == "redis":
        store = RedisSessionStore(
            redis_url=settings.redis_url,
            key_prefix=settings.redis_key_prefix,
            operation_timeout_seconds=settings.redis_operation_timeout_seconds,
            **store_kwargs,
        )
    else:
        store = InMemorySessionStore(
            cleanup_outbox_path=settings.session_cleanup_outbox_path,
            **store_kwargs,
        )
    session_service = SessionApplicationService(providers=providers, store=store)
    observability = build_default_observability(
        max_pending_tasks=settings.observability_max_pending_tasks,
        pending_flush_timeout_seconds=settings.observability_pending_flush_timeout_seconds,
    )
    rag = build_default_rag_service(
        observer=observability,
        max_document_bytes=settings.rag_max_document_bytes,
        max_metadata_bytes=settings.rag_max_metadata_bytes,
        max_metadata_items=settings.rag_max_metadata_items,
        max_metadata_depth=settings.rag_max_metadata_depth,
        parse_concurrency=settings.rag_parse_concurrency,
        docling_max_concurrency=settings.docling_max_concurrency,
        store_path=settings.rag_store_path,
        embedding_provider=persisted.embedding.provider,
        embedding_base_url=persisted.embedding.base_url,
        embedding_api_key=persisted.embedding.api_key,
        embedding_model=persisted.embedding.model,
        embedding_dimensions=persisted.embedding.dimensions,
    )
    result_limiter = ToolResultLimiter(
        max_bytes=settings.mcp_max_result_bytes,
        max_items=settings.mcp_max_result_items,
        max_depth=settings.mcp_max_result_depth,
    )
    tool_client = tool_client or CompositeToolClient(
        StreamableHttpToolClient(
            settings.mcp_server_url,
            internal_token=settings.mcp_internal_token or settings.internal_token,
            timeout_seconds=settings.request_timeout_seconds,
            result_limiter=result_limiter,
        ),
        LocalToolClient(result_limiter=result_limiter),
        allow_fallback=settings.mcp_allow_local_fallback,
        remote_budget_seconds=settings.mcp_fast_path_timeout_seconds,
        result_limiter=result_limiter,
    )
    llm = OpenAICompatibleLlm(
        enabled=persisted.llm.enabled,
        base_url=persisted.llm.base_url,
        api_key=persisted.llm.api_key,
        model=persisted.llm.model,
        temperature=persisted.llm.temperature,
        max_tokens=persisted.llm.max_tokens,
    )
    message_bus = ReliableMessageBus(
        url=settings.rabbitmq_url,
        exchange=settings.rabbitmq_exchange,
        queue=settings.rabbitmq_queue,
        outbox_path="data/presentation-outbox.jsonl",
        timeout_seconds=settings.rabbitmq_publish_timeout_seconds,
        max_in_flight=settings.rabbitmq_max_in_flight,
        prefetch_count=settings.rabbitmq_prefetch_count,
        retry_limit=settings.rabbitmq_retry_limit,
    )
    graph = AgentGraphRuntime(
        tool_client=tool_client,
        providers=providers,
        sessions=store,
        rag_service=rag,
        observer=observability,
        provider_cancel_grace_seconds=settings.provider_cancel_grace_seconds,
        max_parallel_tools=settings.mcp_max_parallel_tools,
        llm_client=llm,
        message_bus=message_bus,
    )
    evaluation = EvaluationService(
        max_runs=settings.evaluation_buffer_size,
        input_price_per_1k=settings.eval_input_price_per_1k,
        output_price_per_1k=settings.eval_output_price_per_1k,
        currency=settings.eval_currency,
    )
    evaluation_runner = EvaluationDatasetRunner(service=evaluation, graph=graph, sessions=session_service)
    profile_store = AccountPreferenceStore(
        redis_url=settings.redis_url,
        key_prefix=settings.redis_key_prefix,
        timeout_seconds=settings.redis_operation_timeout_seconds,
    )
    response_cache = ResponseCache(
        redis_url=settings.redis_url,
        key_prefix=settings.redis_key_prefix,
        ttl_seconds=settings.response_cache_ttl_seconds,
        max_bytes=settings.response_cache_max_bytes,
        max_entries=settings.response_cache_max_entries,
        scope=settings.response_cache_scope,
        lock_seconds=settings.response_cache_lock_seconds,
        timeout_seconds=settings.redis_operation_timeout_seconds,
    ) if settings.response_cache_enabled else None
    chat_service = ChatApplicationService(
        graph=graph,
        sessions=session_service,
        max_message_length=settings.max_message_length,
        evaluation=evaluation,
        profile_store=profile_store,
        response_cache=response_cache,
        cache_model=persisted.llm.model or "default",
    )
    cleanup = CleanupWorker(session_service, interval_seconds=settings.cleanup_interval_seconds)
    configuration_service = ConfigurationApplicationService(
        settings=settings,
        providers=providers,
        rag=rag,
        observability=observability,
        store=store,
        cleanup=cleanup,
        repository=repository,
        initial_configuration=persisted,
        llm=llm,
    )
    audio_ingress = (
        HttpAsrIngress(
            endpoint=settings.asr_endpoint,
            api_key=settings.asr_api_key,
            timeout_seconds=settings.asr_timeout_seconds,
            max_response_bytes=settings.asr_max_response_bytes,
            limits=realtime_limits,
        )
        if settings.asr_endpoint.strip()
        else MockPcmIngress(limits=realtime_limits)
    )
    audio_output = (
        HttpTtsOutput(
            endpoint=settings.tts_endpoint,
            api_key=settings.tts_api_key,
            timeout_seconds=settings.tts_timeout_seconds,
            chunk_bytes=settings.tts_chunk_bytes,
            max_response_bytes=settings.tts_max_response_bytes,
        )
        if settings.tts_endpoint.strip()
        else NullAudioOutput()
    )
    return ServiceContainer(
        settings=settings,
        providers=providers,
        store=store,
        session_service=session_service,
        provider_service=ProviderApplicationService(providers),
        tool_client=tool_client,
        rag=rag,
        observability=observability,
        graph=graph,
        llm=llm,
        chat_service=chat_service,
        configuration_service=configuration_service,
        evaluation=evaluation,
        evaluation_runner=evaluation_runner,
        cleanup=cleanup,
        realtime_limits=realtime_limits,
        message_bus=message_bus,
        audio_ingress=audio_ingress,
        audio_output=audio_output,
        profile_store=profile_store,
        response_cache=response_cache,
    )


def create_app(
    settings: Settings | None = None,
    *,
    container: ServiceContainer | None = None,
) -> FastAPI:
    service_container = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await app.state.container.cleanup.start()
        try:
            yield
        finally:
            await app.state.container.cleanup.stop()
            await app.state.container.llm.aclose()
            await app.state.container.message_bus.close()
            close_audio = getattr(app.state.container.audio_ingress, "close", None)
            if callable(close_audio):
                await close_audio()
            close_output = getattr(app.state.container.audio_output, "close", None)
            if callable(close_output):
                await close_output()
            close_store = getattr(app.state.container.store, "close_redis", None)
            if callable(close_store):
                await close_store()
            await app.state.container.profile_store.close()
            if app.state.container.response_cache is not None:
                await app.state.container.response_cache.close()
            await app.state.container.observability.flush()

    app = FastAPI(title="Digital Human Agent", version="0.1.34", lifespan=lifespan)
    app.state.container = service_container
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=service_container.settings.max_request_body_bytes,
    )
    app.add_middleware(
        InFlightLimitMiddleware,
        limit=service_container.settings.agent_max_in_flight_requests,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=service_container.settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "satoken", "X-Internal-Token", "X-User-Id", "X-User-Name", "X-User-Role", "X-Tenant-Id"],
    )
    app.include_router(router)
    app.include_router(realtime_router)
    _include_optional_routers(app, service_container)
    return app


def _include_optional_routers(app: FastAPI, container: ServiceContainer) -> None:
    """Mount optional routers with the same service container as core routes."""
    for module_name, service, extras in (
        ("app.rag.router", container.rag, {}),
        ("app.observability.router", container.observability, {}),
        ("app.evaluation.router", container.evaluation, {"runner": container.evaluation_runner}),
    ):
        try:
            module = __import__(module_name, fromlist=["router"])
            optional_router = module.build_router(service=service, **extras) if hasattr(module, "build_router") else getattr(module, "router", None)
            if optional_router is not None:
                app.include_router(optional_router)
        except ImportError:
            continue


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
