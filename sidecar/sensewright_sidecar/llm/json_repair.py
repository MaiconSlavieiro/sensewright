"""Zero-latency JSON repair layer for free/reasoning LLM output.

Provides pure functions to strip reasoning wrappers, fix common JSON syntax errors
(trailing commas, smart quotes, NaN/Infinity literals, unescaped control chars),
and extract/parse a JSON object from noisy model output. All functions are
defensive and never raise; on unexpected errors they return the input unchanged
or an empty dict.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

# Re-export the thinking tag regex from scheduler to avoid duplication.
# This is imported at runtime to avoid circular imports if scheduler imports this module.
_THINKING_TAG_RE = re.compile(
    r"<(?:thinking|reasoning|thought|analysis)[^>]*>.*?</(?:thinking|reasoning|thought|analysis)>",
    re.DOTALL | re.IGNORECASE,
)

# Markdown code fence regex (```json ... ``` or ``` ... ```)
_MARKDOWN_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

# Smart quotes mapping
_SMART_QUOTES = {
    "\u201c": '"',  # "
    "\u201d": '"',  # "
    "\u2018": "'",  # '
    "\u2019": "'",  # '
}

# Trailing comma before } or ]
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

# Bare NaN / Infinity / -Infinity outside strings
# Use negative lookbehind to ensure not preceded by word char (for -Infinity)
_NAN_INF_RE = re.compile(r"(?<!\w)(NaN|-?Infinity)\b")


def strip_wrappers(text: str) -> str:
    """Strip markdown fences, thinking/reasoning tags, and surrounding prose whitespace.

    Args:
        text: Raw model output text.

    Returns:
        Cleaned text with wrappers removed.
    """
    if not text:
        return ""

    stripped = text.strip()

    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    stripped = _MARKDOWN_FENCE_RE.sub("", stripped).strip()

    # Strip XML-style reasoning blocks (case-insensitive, DOTALL)
    # Note: regex cannot perfectly handle nested tags of different types;
    # it will match from the first opening tag to the first matching closing tag.
    stripped = _THINKING_TAG_RE.sub("", stripped).strip()

    return stripped


def _replace_smart_quotes(text: str) -> str:
    """Replace smart quotes with straight quotes."""
    for smart, straight in _SMART_QUOTES.items():
        text = text.replace(smart, straight)
    return text


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ]."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _fix_nan_infinity(text: str) -> str:
    """Replace bare NaN/Infinity/-Infinity with null (outside string literals).

    This is a best-effort replacement that avoids touching string contents by
    using a simple state machine to track whether we're inside a string.
    """
    result = []
    i = 0
    in_string = False
    escape = False

    while i < len(text):
        char = text[i]

        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        # Not in a string - check for NaN/Infinity patterns
        match = _NAN_INF_RE.match(text, i)
        if match:
            # Replace entire match (NaN, Infinity, or -Infinity) with null
            result.append("null")
            i += match.end() - match.start()
        else:
            result.append(char)
            if char == '"':
                in_string = True
            i += 1

    return "".join(result)


def _fix_unescaped_control_chars(text: str) -> str:
    """Fix unescaped literal control characters inside JSON string values.

    Replaces raw control chars (including raw newline/tab) inside strings with
    their escaped forms. This is a best-effort fix.
    """
    result = []
    i = 0
    in_string = False
    escape = False

    while i < len(text):
        char = text[i]

        if in_string:
            if escape:
                # Already escaped - keep as-is
                result.append(char)
                escape = False
            elif char == "\\":
                escape = True
                result.append(char)
            elif char == '"':
                in_string = False
                result.append(char)
            elif ord(char) < 0x20:
                # Raw control character inside string - escape it
                # Map common ones to JSON escapes, others to \uXXXX
                if char == "\b":
                    result.append("\\b")
                elif char == "\f":
                    result.append("\\f")
                elif char == "\n":
                    result.append("\\n")
                elif char == "\r":
                    result.append("\\r")
                elif char == "\t":
                    result.append("\\t")
                else:
                    result.append(f"\\u{ord(char):04x}")
            else:
                result.append(char)
        else:
            result.append(char)
            if char == '"':
                in_string = True

        i += 1

    return "".join(result)


def repair_json_text(text: str) -> str:
    """Best-effort repair of common JSON syntax errors in model output.

    Handles (in order):
    1. Markdown fences and thinking/reasoning tags (via strip_wrappers)
    2. Smart quotes → straight quotes
    3. Trailing commas before } or ]
    4. Bare NaN/Infinity/-Infinity → null
    5. Unescaped control characters inside strings

    Args:
        text: Raw model output text.

    Returns:
        Repaired JSON string (may still be invalid if errors are severe).
        On any unexpected error, returns the input unchanged.
    """
    if not text:
        return text

    try:
        # Step 1: Strip wrappers
        repaired = strip_wrappers(text)

        # Step 2: Smart quotes
        repaired = _replace_smart_quotes(repaired)

        # Step 3: Trailing commas
        repaired = _fix_trailing_commas(repaired)

        # Step 4: NaN/Infinity
        repaired = _fix_nan_infinity(repaired)

        # Step 5: Unescaped control chars in strings
        repaired = _fix_unescaped_control_chars(repaired)

        return repaired
    except Exception:  # noqa: BLE001 - defensive, never raise
        return text


def _balanced_json_block(text: str, prefer_last: bool = False) -> Dict[str, Any]:
    """Return the first (or last) balanced ``{...}`` object parsed from ``text``.

    Applies repair_json_text before each parse attempt to handle trailing commas,
    smart quotes, NaN/Infinity, etc.
    """
    starts = [i for i, ch in enumerate(text) if ch == "{"]
    if not starts:
        return {}
    indices = starts[::-1] if prefer_last else starts
    for start in indices:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:index + 1]
                    # Apply repair before parsing
                    repaired = repair_json_text(candidate)
                    try:
                        data = json.loads(repaired)
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        pass
                    break
    return {}


def extract_json(text: str) -> Dict[str, Any]:
    """Extract and parse a JSON object from noisy model output.

    Orchestrates the full repair pipeline:
    1. Strip wrappers (markdown, thinking tags)
    2. Repair common JSON syntax errors
    3. Try json.loads on repaired text
    4. Find balanced {...} blocks (first, then last), repair each, and parse

    Args:
        text: Raw model output text.

    Returns:
        Parsed dict, or {} if nothing parses to a dict.
    """
    if not text:
        return {}

    # Step 1: Strip wrappers
    stripped = strip_wrappers(text)

    # Step 2: Repair and try parse (do this BEFORE direct parse to catch NaN/Infinity)
    repaired = repair_json_text(stripped)
    try:
        data = json.loads(repaired)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Step 3: Find balanced blocks, repair each, and try to parse
    # Try first block
    data = _balanced_json_block(stripped, prefer_last=False)
    if data:
        return data

    # Try last block (reasoning prose may contain braces before real payload)
    data = _balanced_json_block(stripped, prefer_last=True)
    if data:
        return data

    return {}