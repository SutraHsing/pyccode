"""File tools: read, write, edit."""


def handle_read(input: dict) -> str:
    """Read file contents and return them with line numbers.

    Opens the specified file, extracts a range of lines based on the given
    offset and limit, and formats them with line numbers. Handles common
    file system errors gracefully, returning descriptive error messages.

    Args:
        input: A dict containing the following keys:
            file_path (str): Path to the file to read (absolute or relative).
            offset (int, optional): Line number to start reading from (1-based).
                Defaults to 1.
            limit (int, optional): Maximum number of lines to read.
                Defaults to 2000.

    Returns:
        The file contents with line-number formatting as a string,
        or an error message string if the file cannot be read.
    """
    file_path = input["file_path"]
    offset = input.get("offset", 1)
    limit = input.get("limit", 2000)
    print(f"\033[33mRead: {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        output = "".join(
            f"{i:>6}\t{line}" for i, line in enumerate(selected, start=offset)
        )
    except FileNotFoundError:
        output = f"Error: File not found: {file_path}"
    except IsADirectoryError:
        output = f"Error: Is a directory: {file_path}"
    except PermissionError:
        output = f"Error: Permission denied: {file_path}"
    except Exception as e:
        output = f"Error: {e}"
    if not output:
        output = "(empty)"
    print(output)
    return output


def handle_write(input: dict) -> str:
    """Write content to a file and return a status message.

    Creates the file (and any missing parent directories) if it does not exist,
    or overwrites the existing file. Handles common file system errors gracefully,
    returning descriptive error messages.

    Args:
        input: A dict containing the following keys:
            file_path (str): Path to the file to write (absolute or relative).
            content (str): Content to write to the file.

    Returns:
        A status message string indicating success or describing an error.
    """
    import os
    file_path = input["file_path"]
    content = input["content"]
    print(f"\033[33mWrite: {file_path}\033[0m")
    try:
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        output = f"OK: Wrote {len(content)} chars to {file_path}"
    except PermissionError:
        output = f"Error: Permission denied: {file_path}"
    except Exception as e:
        output = f"Error: {e}"
    print(output)
    return output


def handle_edit(input: dict) -> str:
    """Edit a file by replacing an exact text match with new text.

    Reads the specified file, locates occurrences of old_string, and replaces
    them with new_string. Handles zero-match and multiple-match cases, as well
    as common file system errors, returning descriptive status or error messages.

    Args:
        input: A dict containing the following keys:
            file_path (str): Path to the file to edit (absolute or relative).
            old_string (str): Exact text to find in the file.
            new_string (str): Text to replace old_string with.

    Returns:
        A status message string indicating how many occurrences were replaced,
        or describing an error.
    """
    file_path = input["file_path"]
    old_string = input["old_string"]
    new_string = input["new_string"]
    print(f"\033[33mEdit: {file_path}\033[0m")
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            output = f"Error: old_string not found in {file_path}"
        else:
            content = content.replace(old_string, new_string)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            output = f"OK: Replaced {count} occurrence(s) in {file_path}"
    except FileNotFoundError:
        output = f"Error: File not found: {file_path}"
    except PermissionError:
        output = f"Error: Permission denied: {file_path}"
    except Exception as e:
        output = f"Error: {e}"
    print(output)
    return output


SCHEMAS = [
    {
        "name": "read",
        "description": "Read file contents with line numbers. Use for: viewing source code, config files, logs, any text file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read (absolute or relative)"
                },
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-based). Default: 1"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Default: 2000"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "write",
        "description": "Write content to a file. Creates the file if it does not exist, overwrites if it does. Creates parent directories if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write (absolute or relative)"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "required": ["file_path", "content"]
        }
    },
    {
        "name": "edit",
        "description": "Edit a file by replacing exact text matches. Finds old_string in the file and replaces it with new_string. The old_string must match exactly (including whitespace and indentation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to edit (absolute or relative)"
                },
                "old_string": {
                    "type": "string",
                    "description": "Exact text to find in the file"
                },
                "new_string": {
                    "type": "string",
                    "description": "Text to replace old_string with"
                }
            },
            "required": ["file_path", "old_string", "new_string"]
        }
    },
]
