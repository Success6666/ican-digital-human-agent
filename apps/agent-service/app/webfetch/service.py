"""Bounded Playwright fetching with SSRF protection and source fingerprints."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, urlunparse


class FetchError(ValueError):
    """Raised when a URL cannot be fetched under the service policy."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    title: str
    text: str
    content_hash: str
    metadata: dict[str, Any] = field(default_factory=dict)


class WebFetchService:
    """Fetch dynamic job pages without exposing internal network targets."""

    def __init__(
        self,
        *,
        timeout_ms: int = 15_000,
        max_text_chars: int = 120_000,
        max_redirects: int = 3,
        browser_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.max_text_chars = max_text_chars
        self.max_redirects = max_redirects
        self.browser_factory = browser_factory
        self._fingerprints: dict[tuple[str, str], str] = {}

    async def fetch(self, url: str) -> FetchResult:
        normalized = self.normalize_url(url)
        await self._validate_host(normalized)
        browser = await self._open_browser()
        context = page = None
        try:
            context = await browser.new_context(
                java_script_enabled=True,
                accept_downloads=False,
                service_workers="block",
            )
            page = await context.new_page()
            await page.goto(normalized, wait_until="domcontentloaded", timeout=self.timeout_ms)
            final_url = self.normalize_url(page.url)
            await self._validate_host(final_url)
            title = (await page.title()).strip()[:500]
            text = (await page.locator("body").inner_text(timeout=self.timeout_ms)).strip()
            text = " ".join(text.split())[: self.max_text_chars]
            if not text:
                raise FetchError("page contains no readable text")
            return FetchResult(
                url=final_url,
                title=title,
                text=text,
                content_hash=sha256(text.encode("utf-8")).hexdigest(),
                metadata={"source_url": final_url, "title": title},
            )
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(f"web fetch failed ({type(exc).__name__})") from exc
        finally:
            if page is not None:
                await page.close()
            if context is not None:
                await context.close()
            await browser.close()

    def change_state(self, owner_id: str, result: FetchResult) -> str:
        """Return first_seen, unchanged, or incremental for an owner/source pair."""

        key = (owner_id, result.url)
        previous = self._fingerprints.get(key)
        self._fingerprints[key] = result.content_hash
        if previous is None:
            return "first_seen"
        return "unchanged" if previous == result.content_hash else "incremental"

    async def search_company(self, company: str) -> FetchResult:
        """Search through a configured search page and return bounded snippets."""

        if not company.strip():
            return []
        query = company.strip().replace(" ", "+")
        return await self.fetch(f"https://www.baidu.com/s?wd={query}")

    @staticmethod
    def normalize_url(url: str) -> str:
        parsed = urlparse(url.strip())
        if parsed.scheme.lower() not in {"http", "https"}:
            raise FetchError("only http and https URLs are supported")
        if parsed.username or parsed.password or not parsed.hostname:
            raise FetchError("URL must not contain credentials")
        if parsed.port and parsed.port not in {80, 443}:
            raise FetchError("non-standard ports are not allowed")
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.hostname.lower(),
                parsed.path or "/",
                "",
                parsed.query,
                "",
            )
        )

    async def _validate_host(self, url: str) -> None:
        hostname = urlparse(url).hostname
        if not hostname:
            raise FetchError("URL hostname is required")
        try:
            addresses = {ipaddress.ip_address(hostname)}
        except ValueError:
            try:
                infos = await __import__("asyncio").to_thread(
                    socket.getaddrinfo, hostname, None, type=socket.SOCK_STREAM
                )
            except OSError as exc:
                raise FetchError("URL hostname cannot be resolved") from exc
            addresses = {ipaddress.ip_address(item[4][0]) for item in infos}
        if any(
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
            for address in addresses
        ):
            raise FetchError("URL resolves to a blocked network address")

    async def _open_browser(self) -> Any:
        if self.browser_factory is not None:
            return await _maybe_await(self.browser_factory())
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise FetchError("Playwright is not installed") from exc
        manager = await async_playwright().start()
        browser = await manager.chromium.launch(headless=True)
        original_close = browser.close

        async def close() -> None:
            await original_close()
            await manager.stop()

        browser.close = close
        return browser


async def _maybe_await(value: Any) -> Any:
    import inspect

    return await value if inspect.isawaitable(value) else value
