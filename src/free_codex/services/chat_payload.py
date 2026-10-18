"""Provider-neutral OpenAI Chat payload normalization.

The implementation originated as the NIM compatibility normalizer.  It now
normalizes common Responses/Chat tool and content structures once for every
OpenAI-compatible provider.  The old ``nim_chat_payload`` module remains as a
backward-compatible import surface.
"""

from .nim_chat_payload import (
    arguments_to_string,
    normalize_chat_payload_for_nim,
    normalize_content_blocks,
    normalize_messages,
    normalize_one_tool,
    normalize_parameters,
    normalize_single_message,
    normalize_tool_call,
    normalize_tool_choice,
    normalize_tools_list,
)


def normalize_chat_payload(payload):
    """Normalize a generic OpenAI-compatible Chat Completions payload."""
    return normalize_chat_payload_for_nim(payload)


__all__ = [
    "normalize_chat_payload",
    "arguments_to_string",
    "normalize_content_blocks",
    "normalize_messages",
    "normalize_one_tool",
    "normalize_parameters",
    "normalize_single_message",
    "normalize_tool_call",
    "normalize_tool_choice",
    "normalize_tools_list",
]
