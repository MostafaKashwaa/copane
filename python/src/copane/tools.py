import os
import subprocess
from agents import function_tool
from langsmith import traceable


@function_tool
@traceable(run_type="tool", name="Read File")
def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Read a file or a line range from it. Use absolute or relative paths."""
    with open(path) as f:
        lines = f.readlines()
    if end_line <= 0:
        end_line = len(lines)
    return "".join(lines[start_line - 1:end_line])

@function_tool
@traceable(run_type="tool", name="Run Command")
def run_command(cmd: str) -> str:
    """Run a shell command and return stdout+stderr. Use for tests, builds, git, etc."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=30
    )
    output = result.stdout + result.stderr
    return f"[exit code: {result.returncode}]\n{output[:8000]}"

@function_tool
@traceable(run_type="tool", name="Grep Files")
def grep_files(pattern: str, path: str = ".", file_glob: str = "*") -> str:
    """Search for a regex pattern across files. Returns matches with line numbers."""
    result = subprocess.run(
        f"grep -rn --include='{file_glob}' -E '{pattern}' '{path}'",
        shell=True, capture_output=True, text=True, timeout=10
    )
    return result.stdout[:5000] or "No matches found."

@function_tool
@traceable(run_type="tool", name="List Files")
def list_files(path: str = ".", depth: int = 2) -> str:
    """List directory structure up to a certain depth."""
    result = subprocess.run(
        f"find '{path}' -maxdepth {depth} -not -path '*/node_modules/*' "
        f"-not -path '*/.git/*' -not -path '*/vendor/*' | head -200",
        shell=True, capture_output=True, text=True
    )
    return result.stdout

@function_tool
@traceable(run_type="tool", name="Write File")
def write_file(path: str, content: str) -> str:
    """Write content to a file. Use when the user asks you to create or modify files."""
    print(f"\n[write_file] {path} ({len(content)} chars)")
    print("---\n" + content[:500] + "\n---")
    confirm = input("Confirm write? (y/n): ").strip().lower()
    if confirm != "y":
        return "Write cancelled."
    with open(path, "w") as f:
        f.write(content)
    return f"Wrote {len(content)} chars to {path}"

@function_tool
@traceable(run_type="tool", name="Get Current Directory")
def get_current_dir() -> str:
    """Return the current working directory."""
    return os.getcwd()


