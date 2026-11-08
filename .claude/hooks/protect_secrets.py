#!/usr/bin/env python3
"""PreToolUse hook: block edits to .env files and writes that embed API keys.

Exit code 2 blocks the tool call; stderr is shown to Claude as the reason.
"""
import json
import os
import re
import sys

KEY_ASSIGN = re.compile(
    r"""(?ix)
    (api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token)  # key-like name
    ["']?\s*[:=]\s*["']?
    ([A-Za-z0-9_\-]{20,})                                           # long literal value
    """
)
PLACEHOLDER = re.compile(r"(?i)your|example|placeholder|xxx|changeme|here|never_in_chat")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    name = os.path.basename(path)

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        print(f"Blocked: {path} holds secrets. Edit it yourself, outside Claude.", file=sys.stderr)
        return 2

    text = "\n".join(
        str(tool_input.get(k, "")) for k in ("content", "new_string", "new_source")
    )
    for edit in tool_input.get("edits") or []:
        text += "\n" + str(edit.get("new_string", ""))
    for m in KEY_ASSIGN.finditer(text):
        if not PLACEHOLDER.search(m.group(2)):
            print(
                f"Blocked: {path} would contain a literal {m.group(1)}. "
                "Read keys from environment variables instead.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
