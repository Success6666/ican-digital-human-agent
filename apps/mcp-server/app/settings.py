"""MCP server configuration."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    service_name: str = "mcp-server"
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

    @classmethod
    def from_env(cls) -> "Settings":
        values: dict[str, object] = {}
        for field_name, field in cls.model_fields.items():
            raw = os.getenv(field.alias or field_name.upper())
            if raw is not None:
                values[field_name] = raw
        if not values.get("internal_token"):
            values["internal_token"] = os.getenv("AGENT_INTERNAL_TOKEN", "dev-internal-token")
        return cls.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
