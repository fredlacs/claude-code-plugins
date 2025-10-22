import pytest


@pytest.fixture(scope="module")
def anyio_backend():
    """Configure anyio to only use asyncio backend."""
    return "asyncio"
