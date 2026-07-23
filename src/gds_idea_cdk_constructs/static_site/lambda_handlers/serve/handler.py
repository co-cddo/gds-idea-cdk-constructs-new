"""Serve Lambda handler — proxies static files from S3 with authZ via cognito-auth.

This handler sits behind an ALB and:
- If auth is configured (COGNITO_AUTH_SECRET_NAME set): decodes user from ALB
  headers, checks authorization, exposes /.auth/user endpoint
- If no auth (AuthType.NONE): serves files directly from S3

Environment variables:
    CONTENT_BUCKET: S3 bucket name containing built site content
    INDEX_DOCUMENT: Default document for directory requests (e.g. 'index.html')
    ERROR_DOCUMENT: Document to serve for 404s (optional)
    COGNITO_AUTH_SECRET_NAME: Secret name for authZ checks (unset for public sites)
    CACHE_MAX_SIZE: Max number of S3 objects to cache in memory (default: 128)
"""

import base64
import json
import mimetypes
import os
from functools import lru_cache

import boto3

s3 = boto3.client("s3")

CONTENT_BUCKET = os.environ["CONTENT_BUCKET"]
INDEX_DOCUMENT = os.environ.get("INDEX_DOCUMENT", "index.html")
ERROR_DOCUMENT = os.environ.get("ERROR_DOCUMENT")
COGNITO_AUTH_SECRET_NAME = os.environ.get("COGNITO_AUTH_SECRET_NAME")

_cache_max_size = os.environ.get("CACHE_MAX_SIZE")
CACHE_MAX_SIZE = int(_cache_max_size) if _cache_max_size else 128

# Only import and initialise cognito-auth when authentication is configured
_lambda_auth = None
_authoriser = None

if COGNITO_AUTH_SECRET_NAME:
    from cognito_auth import Authoriser
    from cognito_auth.lambda_auth import LambdaAuth

    _lambda_auth = LambdaAuth()
    _authoriser = Authoriser.from_config()

# Binary content types that need base64 encoding for ALB responses
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".avif",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".pdf",
    ".zip",
    ".gz",
    ".br",
    ".mp4",
    ".webm",
    ".ogg",
    ".mp3",
    ".svg",
}


def handler(event, context):
    """Handle ALB request."""
    path = event.get("path", "/")
    print(f"Request path: {path}")

    # Health check endpoint
    if path == "/health":
        return _response(200, "OK", "text/plain")

    # Authenticated path
    if COGNITO_AUTH_SECRET_NAME:
        try:
            user = _lambda_auth.get_auth_user(event)
        except Exception as e:
            print(f"ERROR: Authentication failed: {e}")
            return _response(401, "Authentication failed", "text/plain")

        if path == "/.auth/user":
            return _serve_user(user)

        if not _authoriser.is_authorised(user):
            return _response(403, "Forbidden", "text/plain")

    elif path == "/.auth/user":
        return _response(404, "No authentication configured", "text/plain")

    # Serve static file from S3
    s3_key = _resolve_s3_key(path.lstrip("/"))
    return _serve_file(s3_key)


def _serve_user(user):
    """Return user data as JSON."""
    user_data = {
        "sub": user.sub,
        "email": user.email,
        "name": user.name,
        "given_name": user.given_name,
        "family_name": user.family_name,
        "groups": user.groups,
        "is_admin": user.is_admin,
        "email_domain": user.email_domain,
        "email_verified": user.email_verified,
    }
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(user_data),
        "isBase64Encoded": False,
    }


def _resolve_s3_key(path):
    """Map a URL path to an S3 object key."""
    if not path or path.endswith("/"):
        return f"{path}{INDEX_DOCUMENT}"

    _, ext = os.path.splitext(path)
    if not ext:
        return f"{path}/{INDEX_DOCUMENT}"

    return path


def _serve_file(s3_key):
    """Fetch a file from S3 (with in-memory caching) and return as ALB response."""
    content = _get_s3_content(CONTENT_BUCKET, s3_key)

    if content is None:
        return _serve_error_page()

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": content["content_type"],
            "Cache-Control": _cache_control(os.path.splitext(s3_key)[1]),
        },
        "body": content["body"],
        "isBase64Encoded": content["is_base64_encoded"],
    }


@lru_cache(maxsize=CACHE_MAX_SIZE)
def _get_s3_content(bucket, key):
    """Read an S3 object and cache the result in Lambda memory.

    Cached across warm invocations — reduces S3 GET calls for frequently
    accessed files. Cache is evicted when the Lambda execution environment
    is recycled.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        Dict with body, content_type, is_base64_encoded — or None if not found.
    """
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        print(f"ERROR: Failed to read s3://{bucket}/{key}: {e}")
        return None

    content_type = obj.get("ContentType", "application/octet-stream")
    if content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(key)
        if guessed:
            content_type = guessed

    body_bytes = obj["Body"].read()
    _, ext = os.path.splitext(key)
    is_binary = ext.lower() in BINARY_EXTENSIONS

    if is_binary:
        body = base64.b64encode(body_bytes).decode("utf-8")
    else:
        body = body_bytes.decode("utf-8")

    return {
        "body": body,
        "content_type": content_type,
        "is_base64_encoded": is_binary,
    }


def _serve_error_page():
    """Serve the configured error document, or a generic 404."""
    if ERROR_DOCUMENT:
        try:
            obj = s3.get_object(Bucket=CONTENT_BUCKET, Key=ERROR_DOCUMENT)
            body = obj["Body"].read().decode("utf-8")
            return _response(404, body, "text/html")
        except Exception:
            pass
    return _response(404, "Not Found", "text/plain")


def _cache_control(extension):
    """Return appropriate Cache-Control header based on file type."""
    long_cache = {".js", ".css", ".woff", ".woff2", ".ttf", ".otf"}
    if extension.lower() in long_cache:
        return "public, max-age=31536000, immutable"
    if extension.lower() in {".html", ".htm"}:
        return "public, max-age=0, must-revalidate"
    return "public, max-age=3600"


def _response(status_code, body, content_type):
    """Build a simple ALB response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": content_type},
        "body": body,
        "isBase64Encoded": False,
    }
