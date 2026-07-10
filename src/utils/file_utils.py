"""
ExperimentIQ — File System Utility Functions

Purpose:
    Provides consistent, cross-platform path resolution and file management
    helpers used across the pipeline. Centralises all file system operations
    to ensure paths are always relative to the project root.

Design:
    - All path resolution is relative to the project root (from settings).
    - Functions are pure and stateless where possible.
    - Never silently swallows errors; always raises with context.

Dependencies:
    - config.settings (for project root resolution)
    - Standard library: pathlib, shutil, csv, logging

Inputs:
    Relative or absolute path strings.

Outputs:
    Resolved Path objects; created directories; written files.
"""

from __future__ import annotations

import csv
import logging
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Project Root Resolution
# ---------------------------------------------------------------------------


def get_project_root() -> Path:
    """
    Return the absolute path to the project root directory.

    The project root is defined as the directory containing this file's
    grandparent (src/utils → src → experimentiq/).

    Returns:
        Absolute Path to the project root.
    """
    return Path(__file__).parent.parent.parent.resolve()


def resolve_path(relative_path: str | Path) -> Path:
    """
    Resolve a path relative to the project root.

    If the path is already absolute, returns it unchanged.

    Args:
        relative_path: Relative or absolute path string or Path object.

    Returns:
        Resolved absolute Path.
    """
    p = Path(relative_path)
    if p.is_absolute():
        return p
    return get_project_root() / p


# ---------------------------------------------------------------------------
# Directory Management
# ---------------------------------------------------------------------------


def ensure_directory(path: str | Path) -> Path:
    """
    Ensure a directory exists, creating it and all parents if necessary.

    This is idempotent — safe to call even if the directory already exists.

    Args:
        path: Absolute or relative path to the directory.

    Returns:
        Resolved absolute Path to the created/existing directory.

    Raises:
        OSError: If the path exists but is a file, not a directory.
    """
    resolved = resolve_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    logger.debug("Directory ensured: %s", resolved)
    return resolved


def clear_directory(path: str | Path, recreate: bool = True) -> Path:
    """
    Remove all contents of a directory, optionally recreating it.

    Args:
        path: Absolute or relative path to the directory.
        recreate: If True (default), recreate the empty directory after clearing.

    Returns:
        Resolved absolute Path to the cleared directory.

    Raises:
        FileNotFoundError: If the directory does not exist and recreate=False.
    """
    resolved = resolve_path(path)
    if resolved.exists():
        shutil.rmtree(resolved)
        logger.info("Directory cleared: %s", resolved)
    if recreate:
        resolved.mkdir(parents=True, exist_ok=True)
        logger.debug("Directory recreated: %s", resolved)
    return resolved


# ---------------------------------------------------------------------------
# File Operations
# ---------------------------------------------------------------------------


def safe_delete_file(path: str | Path) -> bool:
    """
    Delete a file if it exists. Does not raise if the file is absent.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        True if the file was deleted; False if it did not exist.
    """
    resolved = resolve_path(path)
    if resolved.exists() and resolved.is_file():
        resolved.unlink()
        logger.debug("Deleted file: %s", resolved)
        return True
    return False


def file_size_mb(path: str | Path) -> float:
    """
    Return the size of a file in megabytes.

    Args:
        path: Absolute or relative path to the file.

    Returns:
        File size in MB rounded to 2 decimal places.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    resolved = resolve_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {resolved}")
    size_bytes = resolved.stat().st_size
    return round(size_bytes / (1024 * 1024), 2)


def count_csv_rows(path: str | Path) -> int:
    """
    Count the number of data rows in a CSV file (excluding the header row).

    Args:
        path: Absolute or relative path to the CSV file.

    Returns:
        Number of data rows (header excluded).

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    resolved = resolve_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"CSV file not found: {resolved}")

    with resolved.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        # Skip header
        try:
            next(reader)
        except StopIteration:
            return 0
        count = sum(1 for _ in reader)

    return count


def list_csv_files(directory: str | Path) -> list[Path]:
    """
    Return a sorted list of all CSV files in a directory.

    Args:
        directory: Absolute or relative path to the directory.

    Returns:
        Sorted list of Path objects pointing to CSV files.

    Raises:
        FileNotFoundError: If the directory does not exist.
    """
    resolved = resolve_path(directory)
    if not resolved.exists():
        raise FileNotFoundError(f"Directory not found: {resolved}")
    return sorted(resolved.glob("*.csv"))


def read_sql_file(path: str | Path) -> str:
    """
    Read a SQL file and return its contents as a string.

    Args:
        path: Absolute or relative path to the SQL file.

    Returns:
        SQL file content as a string.

    Raises:
        FileNotFoundError: If the SQL file does not exist.
    """
    resolved = resolve_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"SQL file not found: {resolved}")
    content = resolved.read_text(encoding="utf-8")
    logger.debug("Read SQL file: %s | length=%d chars", resolved.name, len(content))
    return content


def write_text_file(path: str | Path, content: str, overwrite: bool = True) -> Path:
    """
    Write a text string to a file, creating parent directories as needed.

    Args:
        path: Absolute or relative path to the destination file.
        content: Text content to write.
        overwrite: If False and file exists, raises FileExistsError.

    Returns:
        Resolved absolute Path to the written file.

    Raises:
        FileExistsError: If file exists and overwrite=False.
    """
    resolved = resolve_path(path)
    if not overwrite and resolved.exists():
        raise FileExistsError(f"File already exists and overwrite=False: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    logger.debug("Wrote text file: %s | size=%.2fKB", resolved.name, len(content) / 1024)
    return resolved


def get_output_path(
    filename: str,
    subdirectory: Optional[str] = None,
    base_dir: Optional[str | Path] = None,
) -> Path:
    """
    Construct an output file path within the project's data directory.

    Args:
        filename: The output filename (e.g., "users.csv").
        subdirectory: Optional subdirectory within base_dir (e.g., "raw").
        base_dir: Base directory. Defaults to project root / "data".

    Returns:
        Resolved absolute Path for the output file.
    """
    if base_dir is None:
        root = get_project_root() / "data"
    else:
        root = resolve_path(base_dir)

    if subdirectory:
        root = root / subdirectory

    root.mkdir(parents=True, exist_ok=True)
    return root / filename
