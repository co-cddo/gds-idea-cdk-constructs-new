"""Unit tests for the serve Lambda handler's S3 caching behaviour."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def handler_module(monkeypatch):
    """Import the serve handler fresh with required env vars set.

    The handler reads environment variables at import time, so each test
    gets a freshly imported module to avoid state leaking between tests
    (in particular, the lru_cache on _get_s3_content_cached).
    """
    monkeypatch.setenv("CONTENT_BUCKET", "test-bucket")
    monkeypatch.setenv("INDEX_DOCUMENT", "index.html")

    module_name = "gds_idea_cdk_constructs.static_site.lambda_handlers.serve.handler"
    sys.modules.pop(module_name, None)

    with patch("boto3.client") as mock_boto_client:
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3
        module = importlib.import_module(module_name)
        module.s3 = mock_s3
        yield module

    sys.modules.pop(module_name, None)


def _s3_object(body: bytes, content_type: str = "text/html"):
    """Build a mock S3 get_object response."""
    stream = MagicMock()
    stream.read.return_value = body
    return {"Body": stream, "ContentType": content_type}


class _NoSuchKeyError(Exception):
    """Stand-in for the boto3 client's dynamically generated exception."""


def test_get_s3_content_caches_successful_reads(handler_module):
    """Test that a successful S3 read is served from cache on the second call."""
    handler_module.s3.exceptions.NoSuchKey = _NoSuchKeyError
    handler_module.s3.get_object.return_value = _s3_object(b"<html>hello</html>")

    first = handler_module._get_s3_content("test-bucket", "index.html")
    second = handler_module._get_s3_content("test-bucket", "index.html")

    assert first == second
    assert first["body"] == "<html>hello</html>"
    # Only one real S3 call — the second was served from cache
    assert handler_module.s3.get_object.call_count == 1


def test_get_s3_content_does_not_cache_missing_file(handler_module):
    """Test that a missing file is retried on every call, not cached."""
    handler_module.s3.exceptions.NoSuchKey = _NoSuchKeyError
    handler_module.s3.get_object.side_effect = _NoSuchKeyError()

    first = handler_module._get_s3_content("test-bucket", "missing.html")
    second = handler_module._get_s3_content("test-bucket", "missing.html")

    assert first is None
    assert second is None
    # Both calls hit S3 — the miss was never cached
    assert handler_module.s3.get_object.call_count == 2


def test_get_s3_content_picks_up_file_that_appears_after_initial_miss(handler_module):
    """Test the core regression scenario: a file uploaded after a first 404
    is served correctly on the very next request, without waiting for the
    Lambda execution environment to recycle."""
    handler_module.s3.exceptions.NoSuchKey = _NoSuchKeyError
    handler_module.s3.get_object.side_effect = _NoSuchKeyError()

    # First request: file doesn't exist yet (e.g. build hasn't finished)
    result = handler_module._get_s3_content("test-bucket", "index.html")
    assert result is None

    # Build completes, file now exists in S3
    handler_module.s3.get_object.side_effect = None
    handler_module.s3.get_object.return_value = _s3_object(b"<html>built</html>")

    # Second request: should now succeed, not return the stale cached miss
    result = handler_module._get_s3_content("test-bucket", "index.html")
    assert result is not None
    assert result["body"] == "<html>built</html>"


def test_get_s3_content_does_not_cache_generic_errors(handler_module):
    """Test that a transient S3 error is retried on every call, not cached."""
    handler_module.s3.exceptions.NoSuchKey = _NoSuchKeyError
    handler_module.s3.get_object.side_effect = RuntimeError("transient S3 error")

    first = handler_module._get_s3_content("test-bucket", "index.html")
    second = handler_module._get_s3_content("test-bucket", "index.html")

    assert first is None
    assert second is None
    assert handler_module.s3.get_object.call_count == 2


def test_cache_max_size_env_var(monkeypatch):
    """Test that CACHE_MAX_SIZE environment variable is respected."""
    monkeypatch.setenv("CONTENT_BUCKET", "test-bucket")
    monkeypatch.setenv("CACHE_MAX_SIZE", "64")

    module_name = "gds_idea_cdk_constructs.static_site.lambda_handlers.serve.handler"
    sys.modules.pop(module_name, None)

    with patch("boto3.client"):
        module = importlib.import_module(module_name)

    assert module.CACHE_MAX_SIZE == 64
    sys.modules.pop(module_name, None)


def test_cache_max_size_defaults_to_128(monkeypatch):
    """Test that CACHE_MAX_SIZE defaults to 128 when not set."""
    monkeypatch.setenv("CONTENT_BUCKET", "test-bucket")
    monkeypatch.delenv("CACHE_MAX_SIZE", raising=False)

    module_name = "gds_idea_cdk_constructs.static_site.lambda_handlers.serve.handler"
    sys.modules.pop(module_name, None)

    with patch("boto3.client"):
        module = importlib.import_module(module_name)

    assert module.CACHE_MAX_SIZE == 128
    sys.modules.pop(module_name, None)
