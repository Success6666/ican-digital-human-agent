"""FastAPI application factory for the agent service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .api.body_limit import RequestBodyLimitMiddleware
from .application.chat_service import ChatApplicationService
from .application.cleanup import CleanupWorker
from .application.configuration_service import ConfigurationApplicationService
from .application.provider_service import ProviderApplicationService
from .application.session_service import SessionApplicationService
from .avatar.registry import ProviderRegistry, build_default_registry
from .evaluation.service import EvaluationService
from .graph.runtime import AgentGraphRuntime
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
from .observability.service import ObservabilityService, build_default_observability
from .rag.service import RagService, build_default_rag_service
from .realtime.limits import RealtimeLimits
from .realtime.router import router as realtime_router
from .settings import Settings, get_settings


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    providers: ProviderRegistry
    store: InMemorySessionStore
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
    cleanup: CleanupWorker
    realtime_limits: RealtimeLimits


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
    store = InMemorySessionStore(
        ttl_seconds=settings.session_ttl_seconds,
        max_sessions=settings.session_max_sessions,
        cleanup_batch_size=settings.session_cleanup_batch_size,
        idle_timeout_seconds=settings.session_idle_timeout_seconds,
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
    graph = AgentGraphRuntime(
        tool_client=tool_client,
        providers=providers,
        sessions=store,
        rag_service=rag,
        observer=observability,
        provider_cancel_grace_seconds=settings.provider_cancel_grace_seconds,
        max_parallel_tools=settings.mcp_max_parallel_tools,
        llm_client=llm,
    )
    evaluation = EvaluationService(
        max_runs=settings.evaluation_buffer_size,
        input_price_per_1k=settings.eval_input_price_per_1k,
        output_price_per_1k=settings.eval_output_price_per_1k,
        currency=settings.eval_currency,
    )
    chat_service = ChatApplicationService(
        graph=graph,
        sessions=session_service,
        max_message_length=settings.max_message_length,
        evaluation=evaluation,
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
        cleanup=cleanup,
        realtime_limits=realtime_limits,
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
            await app.state.container.observability.flush()

    app = FastAPI(title="Digital Human Agent", version="0.1.15", lifespan=lifespan)
    app.state.container = service_container
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=service_container.settings.max_request_body_bytes,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=service_container.settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "satoken", "X-Internal-Token", "X-User-Id", "X-User-Name", "X-User-Role"],
    )
    app.include_router(router)
    app.include_router(realtime_router)
    _include_optional_routers(app, service_container)
    return app


def _include_optional_routers(app: FastAPI, container: ServiceContainer) -> None:
    """Mount optional routers with the same service container as core routes."""
    for module_name, service in (
        ("app.rag.router", container.rag),
        ("app.observability.router", container.observability),
        ("app.evaluation.router", container.evaluation),
    ):
        try:
            module = __import__(module_name, fromlist=["router"])
            optional_router = module.build_router(service=service) if hasattr(module, "build_router") else getattr(module, "router", None)
            if optional_router is not None:
                app.include_router(optional_router)
        except ImportError:
            continue


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
