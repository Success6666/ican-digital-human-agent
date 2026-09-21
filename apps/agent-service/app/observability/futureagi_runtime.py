"""Compatibility boundary for the optional FutureAGI OTel package.

The public ``futureagi`` SDK and the OTel package are separate distributions.
Keeping discovery and registration here prevents optional-import details from
leaking into the provider-neutral telemetry sink.
"""

from __future__ import annotations

import importlib
import inspect
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

_ENV_LOCK = threading.RLock()


@dataclass(frozen=True, slots=True)
class FutureAGIRuntime:
    """Registered provider and tracer returned by ``fi_instrumentation``."""

    module: Any
    provider: Any
    tracer: Any


def register_runtime(
    *,
    api_key: str,
    secret_key: str,
    project: str,
    endpoint: str | None = None,
) -> FutureAGIRuntime:
    """Register a non-global FutureAGI tracer provider.

    ``fi-instrumentation-otel`` accepts credentials through exporter headers,
    while its collector endpoint is read from ``FI_BASE_URL``.  We provide both
    explicitly and restore process environment variables immediately after the
    provider is constructed.  This keeps per-process configuration predictable
    and avoids changing the application's global OpenTelemetry provider.
    """

    module = _load_instrumentation()
    if module is None:
        raise RuntimeError("fi-instrumentation-otel is not installed")
    register = getattr(module, "register", None)
    if not callable(register):
        raise RuntimeError("FutureAGI instrumentation has no register API")

    options: dict[str, Any] = {
        "project_name": project,
        "project_type": _resolve_observe_type(module),
        "set_global_tracer_provider": False,
        "verbose": False,
        "headers": {
            "X-Api-Key": api_key,
            "X-Secret-Key": secret_key,
        },
    }
    options = {
        key: value
        for key, value in options.items()
        if value is not None and _accepts_keyword(register, key)
    }

    with _temporary_environment(api_key, secret_key, endpoint):
        provider = register(**options)
    get_tracer = getattr(provider, "get_tracer", None)
    if not callable(get_tracer):
        raise RuntimeError("FutureAGI register did not return a tracer provider")
    tracer = get_tracer(project)
    if not callable(getattr(tracer, "start_span", None)):
        raise RuntimeError("FutureAGI tracer provider returned an invalid tracer")
    return FutureAGIRuntime(module=module, provider=provider, tracer=tracer)


def _load_instrumentation() -> Any | None:
    """Find a module that really exposes ``register``.

    The ``futureagi`` package is intentionally checked only for compatibility
    with legacy installations; current releases expose no OTel registration
    function and are therefore ignored.
    """

    for name in ("fi_instrumentation", "futureagi"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        if callable(getattr(module, "register", None)):
            return module
    return None


def _resolve_observe_type(module: Any) -> Any | None:
    candidates = [getattr(module, "ProjectType", None)]
    try:
        types_module = importlib.import_module("fi_instrumentation.fi_types")
    except ImportError:
        types_module = None
    if types_module is not None:
        candidates.append(getattr(types_module, "ProjectType", None))
    for project_type in candidates:
        observe = getattr(project_type, "OBSERVE", None)
        if observe is not None:
            return observe
    return None


def _accepts_keyword(function: Any, name: str) -> bool:
    """Keep calls compatible with older registration signatures."""

    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return True
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return True
    return name in {parameter.name for parameter in parameters}


@contextmanager
def _temporary_environment(
    api_key: str,
    secret_key: str,
    endpoint: str | None,
) -> Iterator[None]:
    values = {
        "FI_API_KEY": api_key,
        "FI_SECRET_KEY": secret_key,
    }
    if endpoint:
        values["FI_BASE_URL"] = endpoint
    with _ENV_LOCK:
        previous = {name: os.environ.get(name) for name in values}
        os.environ.update(values)
        try:
            yield
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


async def flush_runtime(runtime: FutureAGIRuntime | None) -> None:
    """Flush buffered provider exports without shutting down the service."""

    if runtime is None:
        return
    force_flush = getattr(runtime.provider, "force_flush", None)
    if callable(force_flush):
        try:
            result = force_flush(timeout_millis=2000)
        except TypeError:
            result = force_flush()
        if inspect.isawaitable(result):
            await result
    module_flush = getattr(runtime.module, "flush", None)
    if callable(module_flush):
        result = module_flush()
        if inspect.isawaitable(result):
            await result


__all__ = ["FutureAGIRuntime", "flush_runtime", "register_runtime"]
