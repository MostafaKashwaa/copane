import json
import os
import difflib

from agents import ToolApprovalItem


def format_diff(path: str, new_content: str) -> str:
    """Build a unified diff, or show full content for a new file."""
    if os.path.exists(path):
        with open(path) as f:
            old_content = f.read()
        diff = difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        return "".join(diff)
    return f"(new file)\n---\n{new_content}\n---"


def format_tool_preview(item: ToolApprovalItem) -> str:
    """Format a tool approval item for preview."""

    raw = item.raw_item
    if not hasattr(raw, 'arguments') or not raw.arguments:
        return f"Tool: {item.tool_name}\n(No arguments provided)"

    try:
        args = json.loads(raw.arguments)
    except (json.JSONDecodeError, TypeError, ValueError):
        return f"Tool: {item.tool_name}\n(Arguments are not valid JSON)\n---\n{raw.arguments}\n---"

    tool_name = item.tool_name or ''

    if 'write_file' in tool_name or tool_name == 'write_file':
        path = args.get('path', '(unknown)')
        content = args.get('content', '')
        diff = format_diff(path, content)
        return f"Tool: {tool_name}\nPath: {path}\n---\n{diff}\n---"
    elif 'delete_file' in tool_name or tool_name == 'delete_file':
        path = args.get('path', '(unknown)')
        return f"Tool: {tool_name}\nPath: {path}\n(Note: This will delete the file if approved)"
    elif 'run_command' in tool_name or tool_name == 'run_command':
        command = args.get('cmd', '(unknown)')
        return f"Tool: {tool_name}\nCommand: {command}\n(Note: This will execute the command if approved)"
    else:
        lines = [f"Tool: {tool_name}"]
        for key, value in args.items():
            display = value if len(str(value)) < 200 else str(value)[:200] + "..." 
            lines.append(f"{key}: {display}")
        return "\n".join(lines)

