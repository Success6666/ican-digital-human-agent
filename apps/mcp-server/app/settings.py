"""MCP server configuration."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator, model_validator

_DEFAULT_INTERNAL_TOKEN = "dev-internal-token"
_PRODUCTION_TOKEN_MIN_LENGTH = 32
_PRODUCTION_TOKEN_PLACEHOLDERS = frozenset(
    {
        _DEFAULT_INTERNAL_TOKEN,
        "replace-with-a-long-random-token",
        "replace-with-a-different-long-random-token",
    }
)


class Settings(BaseModel):
    service_name: str = "mcp-server"
    environment: str = "development"
    host: str = "0.0.0.0"
    port: int = 9000
    internal_token: str = Field(default="dev-internal-token", alias="MCP_INTERNAL_TOKEN")
    streamable_http_path: str = Field(default="/mcp", alias="MCP_STREAMABLE_HTTP_PATH")
    max_request_body_size: int = Field(default=4 * 1024 * 1024, alias="MCP_MAX_REQUEST_BODY_SIZE")
    stateless_http: bool = Field(default=False, alias="MCP_STATELESS_HTTP")

    model_config = {"populate_by_name": True}

    @field_validator("port", "max_request_body_size")
    @classmethod
    def positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @model_validator(mode="after")
    def validate_production_token(self) -> "Settings":
        environment = self.environment.strip().casefold()
        if environment in {"prod", "production"} and _unsafe_production_token(self.internal_token):
            raise ValueError("MCP_INTERNAL_TOKEN must be replaced in production")
        return self

    @classmethod
    def from_env(cls) -> "Settings":
        values: dict[str, object] = {}
        for field_name, field in cls.model_fields.items():
            raw = os.getenv(field.alias or field_name.upper())
            if raw is not None:
                values[field_name] = raw
        if not values.get("internal_token"):
            values["internal_token"] = os.getenv("AGENT_INTERNAL_TOKEN", _DEFAULT_INTERNAL_TOKEN)
        return cls.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def _unsafe_production_token(value: str) -> bool:
    normalized = value.strip().casefold() if value else ""
    return (
        not normalized
        or normalized in _PRODUCTION_TOKEN_PLACEHOLDERS
        or len(value.strip()) < _PRODUCTION_TOKEN_MIN_LENGTH
    )
