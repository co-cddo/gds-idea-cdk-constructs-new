"""Structured JSON logging for CloudWatch.

Configures stdout-based JSON logging so Docker/CloudWatch captures
structured output. Must be imported before any other application modules
to ensure handlers are set before third-party loggers initialise.
"""

import json
import logging
import os
import sys

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


class _JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for CloudWatch Logs Insights."""

    def format(self, record):
        entry = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging() -> logging.Logger:
    """Configure root logger and return a module-level logger.

    - Clears pre-existing handlers (avoids duplicates from SDK imports).
    - Writes JSON to stdout (required for Docker log drivers).
    - Suppresses noisy boto/urllib3 loggers.
    """
    level = getattr(logging, LOG_LEVEL, logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(_JsonFormatter(datefmt="%Y-%m-%d %H:%M:%S"))

    root.addHandler(handler)
    root.setLevel(level)

    # Suppress noisy SDK loggers
    for name in ("boto3", "botocore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    return logging.getLogger("agent")
