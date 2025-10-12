"""Utility script to package the current AutoGPT workspace as a zip archive.

This helper focuses on the Codex-generated project contained in the repository. It
creates a deterministic archive that skips build artefacts and version-control
folders so the resulting download only contains the relevant source files.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterator
import zipfile

EXCLUDE_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
}

EXCLUDE_FILES = {
    ".DS_Store",
}


def iter_files(root: Path) -> Iterator[Path]:
    """Yield all files under *root* that are not excluded."""
    for dirpath, dirnames, filenames in os.walk(root):
        path_obj = Path(dirpath)

        # Prevent os.walk from descending into excluded directories by mutating
        # dirnames in-place.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]

        for filename in filenames:
            if filename in EXCLUDE_FILES:
                continue

            file_path = path_obj / filename
            if any(part in EXCLUDE_DIRS for part in file_path.relative_to(root).parts):
                continue

            yield file_path


def create_archive(root: Path, output: Path) -> None:
    """Create a zip archive containing the repository contents."""
    root = root.resolve()
    output = output.resolve()

    if output.exists():
        output.unlink()

    try:
        output_relative = output.relative_to(root)
    except ValueError:
        output_relative = None

    seen_paths: set[Path] = set()

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in iter_files(root):
            relative_path = file_path.resolve().relative_to(root)
            if output_relative is not None and relative_path == output_relative:
                # Skip the archive itself when it lives inside the repository.
                continue
            if relative_path in seen_paths:
                continue
            seen_paths.add(relative_path)
            archive.write(file_path, arcname=str(relative_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package the Codex-generated AutoGPT project into a zip archive.",
    )
    parser.add_argument(
        "--output",
        default="autogpt_codex_project.zip",
        help="Destination path for the generated zip file (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output

    create_archive(root, output)
    print(f"Archive written to {output}")


if __name__ == "__main__":
    main()
