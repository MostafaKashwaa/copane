import os
import re
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from copane.term_styles import Colors, print_success, print_error, print_warning


class FileCompleter(Completer):
    """Enhanced file completer with colors and sub-directory support."""

    def get_completions(self, document: Document, complete_event):
        text_before_cursor = document.text_before_cursor
        pattern = r"@(\S*)$"
        match = re.search(pattern, text_before_cursor)
        
        if not match:
            return
        
        full_prefix = match.group(1)
        
        # Handle both forward and backward slashes
        if '/' in full_prefix or '\\' in full_prefix:
            # Normalize path separators
            normalized = full_prefix.replace('\\', '/')
            
            # Split into directory and filename parts
            if '/' in normalized:
                # Get the last directory separator
                last_slash = normalized.rfind('/')
                dir_part = normalized[:last_slash]
                file_prefix = normalized[last_slash + 1:]
                
                # Handle empty directory part
                if dir_part == '':
                    dir_part = '.'
                
                # Check if directory exists
                if not os.path.isdir(dir_part):
                    return
                
                base_dir = dir_part
                search_prefix = file_prefix
            else:
                # Should not happen with normalized path, but just in case
                base_dir = '.'
                search_prefix = full_prefix
        else:
            # No directory specified
            base_dir = '.'
            search_prefix = full_prefix
        
        try:
            # List files in the target directory
            for entry in os.listdir(base_dir):
                # Skip hidden files unless explicitly typed
                if entry.startswith('.') and not search_prefix.startswith('.'):
                    continue
                
                if entry.startswith(search_prefix):
                    full_path = os.path.join(base_dir, entry)
                    
                    # Determine display text with colors
                    if os.path.isfile(full_path):
                        display_text = ANSI(f"{Colors.PRIMARY}{entry}{Colors.RESET}")
                    elif os.path.isdir(full_path):
                        display_text = ANSI(f"{Colors.ACCENT}{entry}/{Colors.RESET}")
                    else:
                        display_text = entry
                    
                    # Determine completion text
                    if '/' in full_prefix or '\\' in full_prefix:
                        # We need to reconstruct the path
                        if dir_part == '.':
                            completion_text = entry
                        else:
                            completion_text = os.path.join(dir_part, entry).replace('\\', '/')
                    else:
                        completion_text = entry
                    
                    yield Completion(
                        completion_text,
                        start_position=-len(full_prefix),
                        display=display_text,
                        style="bg:default"
                    )
        except (PermissionError, FileNotFoundError, OSError):
            # Directory doesn't exist or no permission
            return


def expand_files(text):
    """Find all occurrences of @filename and replace with file content."""
    pattern = r"@(\S+)"
    matches = re.findall(pattern, text)

    for filename in matches:
        if os.path.isfile(filename):
            try:
                with open(filename, "r") as f:
                    content = f.read()
                # Replace @filename with the file content
                text = text.replace(f"@{filename}", content)
                print_success(f"Included file: {filename}")
            except Exception as e:
                print_error(f"Error reading {filename}: {e}")
                text = text.replace(
                    f"@{filename}", f"[error reading file: {filename}]")
        else:
            print_warning(f"File not found: {filename}")
            text = text.replace(
                f"@{filename}", f"[error: file not found: {filename}]")
    return text
