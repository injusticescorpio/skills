#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
# SPDX-License-Identifier: MIT
"""
Log Combiner Script
Discovers log files in a given directory and combines them into a single deterministic output file
without loading all contents into memory at once.
"""

import argparse
import glob
import os
import re
import sys
from typing import List, Tuple, Optional

# Supported log extensions & common log filenames
LOG_EXTENSIONS = ('.log', '.txt', '.out', '.err')
COMMON_LOG_NAMES = {'stdout', 'stderr', 'application', 'error', 'system', 'server', 'access'}

# Standard timestamp pattern matching at beginning of lines for chronological sorting
# Examples: 2023-11-01 10:00:00, 2023/11/01T10:00:00Z, [2023-11-01 10:00:00]
TIMESTAMP_REGEX = re.compile(
    r'^\[?(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?'
)


def discover_log_files(log_dir: str, recursive: bool = True) -> List[str]:
    """Finds all relevant log files in the specified directory."""
    if not os.path.isdir(log_dir):
        raise ValueError(f"Log directory not found or not a directory: {log_dir}")

    found_files = set()
    pattern = "**/*" if recursive else "*"
    search_path = os.path.join(log_dir, pattern)

    for path in glob.glob(search_path, recursive=recursive):
        if not os.path.isfile(path):
            continue
        # Skip hidden files
        basename = os.path.basename(path)
        if basename.startswith('.'):
            continue

        ext = os.path.splitext(basename)[1].lower()
        name_no_ext = os.path.splitext(basename)[0].lower()

        if ext in LOG_EXTENSIONS or name_no_ext in COMMON_LOG_NAMES or 'log' in name_no_ext:
            found_files.add(os.path.abspath(path))

    # Return sorted list for determinism
    return sorted(list(found_files))


def parse_timestamp(line: str) -> Optional[str]:
    """Extracts timestamp from line if present, normalized as string for sorting."""
    match = TIMESTAMP_REGEX.match(line)
    if match:
        return match.group(1).replace('/', '-')
    return None


def combine_logs(log_dir: str, output_path: str, recursive: bool = True, sort_by_timestamp: bool = False) -> Tuple[int, int]:
    """
    Combines log files from log_dir into output_path.
    Prefixes each line with source filename tag for provenance: `[source:filename] ...`
    Returns (file_count, total_lines).
    """
    files = discover_log_files(log_dir, recursive=recursive)
    if not files:
        print(f"Warning: No log files found in directory: {log_dir}", file=sys.stderr)
        # Create empty file
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            pass
        return 0, 0

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    total_lines = 0

    if sort_by_timestamp:
        # If timestamp sorting requested, read streaming lines with key and sort
        entries = []
        for file_path in files:
            rel_name = os.path.relpath(file_path, log_dir)
            with open(file_path, 'r', encoding='utf-8', errors='replace') as infile:
                for line in infile:
                    ts = parse_timestamp(line) or "9999-99-99 99:99:99"
                    clean_line = line.rstrip('\r\n')
                    entries.append((ts, rel_name, clean_line))
        
        # Sort stably by timestamp then source file
        entries.sort(key=lambda x: (x[0], x[1]))
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for _, source_file, line_content in entries:
                outfile.write(f"[source:{source_file}] {line_content}\n")
                total_lines += 1
    else:
        # Streaming combination preserving file boundaries
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for file_path in files:
                rel_name = os.path.relpath(file_path, log_dir)
                with open(file_path, 'r', encoding='utf-8', errors='replace') as infile:
                    for line in infile:
                        clean_line = line.rstrip('\r\n')
                        outfile.write(f"[source:{rel_name}] {clean_line}\n")
                        total_lines += 1

    return len(files), total_lines


def main():
    parser = argparse.ArgumentParser(
        description="Combine multiple log files into a single structured log stream preserving source provenance."
    )
    parser.add_argument(
        "--log-dir",
        "-d",
        required=True,
        help="Path to the directory containing log files to analyze."
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path for the combined output log file."
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not search subdirectories recursively."
    )
    parser.add_argument(
        "--sort-timestamps",
        action="store_true",
        help="Attempt to sort log lines across files by timestamp."
    )

    args = parser.parse_args()

    try:
        file_count, line_count = combine_logs(
            log_dir=args.log_dir,
            output_path=args.output,
            recursive=not args.no_recursive,
            sort_by_timestamp=args.sort_timestamps
        )
        print(f"Successfully combined {file_count} log file(s) into {args.output} ({line_count} total lines).")
    except Exception as e:
        print(f"Error combining logs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
