# ==========================================================================
# Stream processing
# ==========================================================================

def _handle_reasoning(event: dict):
    """Return a thinking chunk from a reasoning delta event, if it has text.

    Strands streams reasoning as ``reasoningContent: {"text": ...}``. The text can
    also sit under ``reasoningText`` (the shape of a complete message), so both
    are read. Deltas without text, such as the signature, give ``None``.
    """
    reasoning = event["delta"]["reasoningContent"]
    text = reasoning.get("text") or reasoning.get("reasoningText", {}).get("text")
    if text:
        return {"type": "thinking", "data": text}
    return None


def _extract_response_text(result_obj) -> str:
    """Pull the final text response from a Strands result object."""
    message = (
        result_obj.get("message", {})
        if isinstance(result_obj, dict)
        else getattr(result_obj, "message", {})
    )
    if isinstance(message, dict):
        for block in message.get("content", []):
            if "text" in block:
                return block["text"]
    return ""