# ==========================================================================
# Stream processing
# ==========================================================================

def _handle_reasoning(event: dict):
    """Yield a thinking chunk from a delta event, if present."""
    reasoning = event["delta"]["reasoningContent"]
    text_block = reasoning.get("reasoningText", {})
    if "text" in text_block:
        return {"type": "thinking", "data": text_block["text"]}
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