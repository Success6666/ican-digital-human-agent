"""Uvicorn entry point for the MCP service."""

from .server import create_app
from .settings import get_settings

app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
