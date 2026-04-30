"""Conformance tests for DataSource implementations."""
import pytest
from app.intelligence.base import DataSource


class StubSource(DataSource):
    @property
    def name(self):
        return "stub"

    @property
    def capabilities(self):
        return ["get_test", "scrape_article"]

    def supports(self, method):
        return method in self._capabilities_set

    @property
    def _capabilities_set(self):
        return set(self.capabilities)

    async def fetch(self, method, **kwargs):
        return {"src": self.name, "method": method, "kwargs": kwargs}


def make_stub_source():
    return StubSource()


SOURCE_FACTORIES = [
    pytest.param(make_stub_source, id="stub"),
]


@pytest.fixture(params=SOURCE_FACTORIES)
def source(request) -> DataSource:
    return request.param()


def test_source_name_is_string(source):
    assert isinstance(source.name, str)
    assert len(source.name) > 0


def test_source_capabilities_is_list(source):
    caps = source.capabilities
    assert isinstance(caps, list)
    assert all(isinstance(c, str) for c in caps)


def test_source_supports_returns_bool(source):
    for cap in source.capabilities:
        assert source.supports(cap) is True
    assert source.supports("definitely_not_a_method") is False


@pytest.mark.asyncio
async def test_source_fetch_supported_method(source):
    if not source.capabilities:
        return
    method = source.capabilities[0]
    result = await source.fetch(method, foo="bar")
    assert result is not None
