import pytest

from app.webfetch.service import FetchError, FetchResult, WebFetchService


def test_normalize_url_removes_fragment_and_rejects_credentials_or_ports() -> None:
    assert WebFetchService.normalize_url("HTTPS://Example.com/job?id=1#details") == "https://example.com/job?id=1"
    with pytest.raises(FetchError):
        WebFetchService.normalize_url("http://user:pass@example.com/job")
    with pytest.raises(FetchError):
        WebFetchService.normalize_url("http://example.com:8080/job")


async def test_private_addresses_are_blocked() -> None:
    service = WebFetchService()
    with pytest.raises(FetchError, match="blocked"):
        await service._validate_host("http://127.0.0.1/")


def test_source_change_state_is_incremental() -> None:
    service = WebFetchService()
    first = FetchResult("https://example.com/job", "job", "one", "hash-1")
    same = FetchResult("https://example.com/job", "job", "one", "hash-1")
    changed = FetchResult("https://example.com/job", "job", "two", "hash-2")
    assert service.change_state("u1", first) == "first_seen"
    assert service.change_state("u1", same) == "unchanged"
    assert service.change_state("u1", changed) == "incremental"
