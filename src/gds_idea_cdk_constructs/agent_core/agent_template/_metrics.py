"""Token usage extraction and OpenTelemetry reporting."""

import logging

from opentelemetry import trace

logger = logging.getLogger("agent")


def _get_attr(obj, key, default=None):
    """Get a value from a dict or object attribute."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def extract_and_record_usage(
    result_obj,
    session_id: str,
    model_id: str,
) -> dict:
    """Extract token metrics from a Strands result and record to OTel.

    Returns:
        Dict with keys ``input``, ``output``, ``total`` (all default 0).
    """
    usage = {"input": 0, "output": 0, "total": 0}

    try:
        metrics = _get_attr(result_obj, "metrics")
        accumulated = _get_attr(metrics, "accumulated_usage") if metrics else None

        if not accumulated:
            logger.warning("No accumulated_usage in result metrics")
            return usage

        usage["input"] = accumulated.get("inputTokens", 0)
        usage["output"] = accumulated.get("outputTokens", 0)
        usage["total"] = accumulated.get(
            "totalTokens", usage["input"] + usage["output"]
        )

        logger.info(
            "TOKEN_USAGE | Session=%s | In=%d | Out=%d | Total=%d",
            session_id,
            usage["input"],
            usage["output"],
            usage["total"],
        )

        _record_otel_span(usage, model_id)

    except Exception:
        logger.warning("Error extracting Strands metrics", exc_info=True)

    return usage


def _record_otel_span(usage: dict, model_id: str) -> None:
    """Attach token metrics to the current OTel span."""
    span = trace.get_current_span()
    if not span.is_recording():
        logger.warning("OTel span not recording — tokens won't reach dashboard")
        return

    span.set_attribute("gen_ai.system", "bedrock")
    span.set_attribute("gen_ai.request.model", model_id)
    span.set_attribute("gen_ai.usage.input_tokens", usage["input"])
    span.set_attribute("gen_ai.usage.output_tokens", usage["output"])
    span.set_attribute("gen_ai.usage.total_tokens", usage["total"])
