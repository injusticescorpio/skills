#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "drain3>=0.9.11",
# ]
# ///
# SPDX-License-Identifier: MIT
"""
Drain3 Log Analyzer Script
Incrementally processes combined/single log files using Drain3 template mining,
extracts log levels, metadata, timestamps, and aggregates clusters into structured JSON
suitable for downstream LLM reasoning and reporting without overloading context.
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, Any, List, Optional, Tuple

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig
from drain3.masking import MaskingInstruction


SOURCE_REGEX = re.compile(r'^\[source:([^\]]+)\]\s*(.*)$')
TIMESTAMP_REGEX = re.compile(
    r'(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)'
)
LOG_LEVEL_REGEX = re.compile(
    r'\b(FATAL|CRITICAL|ERROR|ERR|WARN|WARNING|INFO|DEBUG|TRACE)\b',
    re.IGNORECASE
)

# Standard regex masking rules
DEFAULT_MASKING_RULES = [
    {"regex_pattern": r"((?<=[^A-Za-z0-9])|^)(([0-9a-f]{2,}:){3,}([0-9a-f]{2,}))((?=[^A-Za-z0-9])|$)", "mask_with": "MAC"},
    {"regex_pattern": r"((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?)((?=[^A-Za-z0-9])|$)", "mask_with": "IP"},
    {"regex_pattern": r"((?<=[^A-Za-z0-9])|^)([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})((?=[^A-Za-z0-9])|$)", "mask_with": "UUID"},
    {"regex_pattern": r"((?<=[^A-Za-z0-9])|^)(0x[a-f0-9A-F]+)((?=[^A-Za-z0-9])|$)", "mask_with": "HEX"},
    {"regex_pattern": r"((?<=[^A-Za-z0-9])|^)([\-\+]?\d+)((?=[^A-Za-z0-9])|$)", "mask_with": "NUM"},
    {"regex_pattern": r'(?<=executed cmd )(".*?")', "mask_with": "CMD"}
]


def extract_metadata(raw_line: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """
    Parses source file, timestamp, log level, and the free-text log payload.
    Returns: (source_file, timestamp, log_level, payload)
    """
    source_file = None
    line = raw_line.strip()

    # 1. Source prefix check
    source_match = SOURCE_REGEX.match(line)
    if source_match:
        source_file = source_match.group(1)
        line = source_match.group(2).strip()

    # 2. Timestamp check
    timestamp = None
    ts_match = TIMESTAMP_REGEX.search(line)
    if ts_match:
        timestamp = ts_match.group(1)

    # 3. Log level check
    log_level = "INFO"
    lvl_match = LOG_LEVEL_REGEX.search(line)
    if lvl_match:
        level_raw = lvl_match.group(1).upper()
        if level_raw in ("FATAL", "CRITICAL"):
            log_level = "CRITICAL"
        elif level_raw in ("ERROR", "ERR"):
            log_level = "ERROR"
        elif level_raw in ("WARNING", "WARN"):
            log_level = "WARNING"
        elif level_raw in ("DEBUG", "TRACE"):
            log_level = "DEBUG"
        else:
            log_level = "INFO"

    # 4. Clean payload for Drain3: strip timestamps / obvious log prefix brackets
    # Remove leading timestamps or structured prefixes like [2023-11-01 10:00:00] [ERROR]
    cleaned = line
    if timestamp:
        cleaned = cleaned.replace(timestamp, "", 1).strip(" []():,-")
    
    # Remove level word if at beginning
    cleaned = re.sub(r'^(?:\[\s*)?' + log_level + r'(?:\s*\])?[:\s-]*', '', cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        cleaned = line

    return source_file, timestamp, log_level, cleaned


def inspect_log_characteristics(file_path: str, sample_size: int = 500) -> Dict[str, Any]:
    """
    Quickly reads sample lines and file statistics to recommend Drain3 settings.
    """
    size_bytes = os.path.getsize(file_path)
    total_lines = 0
    level_counts = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
    token_lengths = []
    sources = set()

    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            total_lines += 1
            if idx < sample_size:
                src, ts, lvl, payload = extract_metadata(line)
                if src:
                    sources.add(src)
                level_counts[lvl] = level_counts.get(lvl, 0) + 1
                token_lengths.append(len(payload.split()))

    avg_tokens = sum(token_lengths) / len(token_lengths) if token_lengths else 10

    # Auto-recommend configuration based on characteristics
    recommended_sim_th = 0.4
    recommended_depth = 4
    if avg_tokens > 20:
        recommended_depth = 5
    if len(sources) > 5:
        recommended_sim_th = 0.5

    return {
        "file_size_bytes": size_bytes,
        "total_lines_approx": total_lines,
        "sample_analyzed": min(total_lines, sample_size),
        "level_distribution_sample": level_counts,
        "avg_tokens_per_line": round(avg_tokens, 2),
        "distinct_sources_sample": list(sources),
        "recommended_sim_th": recommended_sim_th,
        "recommended_depth": recommended_depth,
    }


def analyze_logs(
    input_path: str,
    output_path: str,
    sim_th: float = 0.4,
    depth: int = 4,
    max_children: int = 100,
    max_clusters: Optional[int] = None,
    max_examples_per_cluster: int = 3,
    config_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Executes Drain3 clustering on input_path and writes aggregated results to output_path.
    """
    start_time = time.time()
    
    # Setup Drain3 config
    config = TemplateMinerConfig()
    if config_file and os.path.isfile(config_file):
        config.load(config_file)
    else:
        config.drain_sim_th = sim_th
        config.drain_depth = depth
        config.drain_max_children = max_children
        config.drain_max_clusters = max_clusters
        config.mask_prefix = "<:"
        config.mask_suffix = ":>"
        config.masking_instructions = [
            MaskingInstruction(m["regex_pattern"], m["mask_with"])
            for m in DEFAULT_MASKING_RULES
        ]

    # Explicit override if CLI args provided
    if sim_th != 0.4:
        config.drain_sim_th = sim_th
    if depth != 4:
        config.drain_depth = depth

    template_miner = TemplateMiner(config=config)

    cluster_metadata: Dict[int, Dict[str, Any]] = {}
    level_totals = {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "INFO": 0, "DEBUG": 0}
    source_distribution: Dict[str, int] = {}
    total_processed_lines = 0

    with open(input_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_str = line.rstrip("\r\n")
            if not line_str:
                continue

            total_processed_lines += 1
            source_file, timestamp, log_level, payload = extract_metadata(line_str)
            
            level_totals[log_level] = level_totals.get(log_level, 0) + 1
            if source_file:
                source_distribution[source_file] = source_distribution.get(source_file, 0) + 1

            result = template_miner.add_log_message(payload)
            cluster_id = result["cluster_id"]
            template_mined = result["template_mined"]

            if cluster_id not in cluster_metadata:
                cluster_metadata[cluster_id] = {
                    "cluster_id": cluster_id,
                    "template": template_mined,
                    "count": 0,
                    "log_levels": {},
                    "sources": set(),
                    "first_seen": timestamp,
                    "last_seen": timestamp,
                    "examples": []
                }

            meta = cluster_metadata[cluster_id]
            meta["count"] += 1
            meta["template"] = template_mined
            meta["log_levels"][log_level] = meta["log_levels"].get(log_level, 0) + 1
            if source_file:
                meta["sources"].add(source_file)
            if timestamp:
                if not meta["first_seen"]:
                    meta["first_seen"] = timestamp
                meta["last_seen"] = timestamp

            # Keep a few distinct representative examples
            if len(meta["examples"]) < max_examples_per_cluster:
                if line_str not in meta["examples"]:
                    meta["examples"].append(line_str)

    # Format clusters for output
    clusters_list = []
    for c_id, meta in cluster_metadata.items():
        # Determine dominant level for cluster
        dom_level = max(meta["log_levels"].items(), key=lambda x: x[1])[0] if meta["log_levels"] else "INFO"
        clusters_list.append({
            "cluster_id": c_id,
            "template": meta["template"],
            "count": meta["count"],
            "dominant_level": dom_level,
            "level_counts": meta["log_levels"],
            "sources": sorted(list(meta["sources"])),
            "first_seen": meta["first_seen"],
            "last_seen": meta["last_seen"],
            "examples": meta["examples"]
        })

    # Sort clusters descending by frequency
    clusters_list.sort(key=lambda x: x["count"], reverse=True)

    elapsed_sec = time.time() - start_time
    rate = total_processed_lines / elapsed_sec if elapsed_sec > 0 else 0

    # Categorize patterns into Errors/Warnings vs Normal for quick LLM ingestion
    error_clusters = [c for c in clusters_list if c["dominant_level"] in ("CRITICAL", "ERROR")]
    warning_clusters = [c for c in clusters_list if c["dominant_level"] == "WARNING"]

    output_data = {
        "summary": {
            "total_lines_processed": total_processed_lines,
            "total_clusters": len(clusters_list),
            "processing_time_seconds": round(elapsed_sec, 3),
            "lines_per_second": round(rate, 1),
            "total_by_level": level_totals,
            "sources": source_distribution,
            "drain_config": {
                "sim_th": config.drain_sim_th,
                "depth": config.drain_depth,
                "max_children": config.drain_max_children,
                "max_clusters": config.drain_max_clusters
            }
        },
        "error_patterns": error_clusters,
        "warning_patterns": warning_clusters,
        "top_patterns": clusters_list[:20],
        "all_clusters": clusters_list
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out_f:
        json.dump(output_data, out_f, indent=2)

    return output_data


def main():
    parser = argparse.ArgumentParser(
        description="Mine log templates and aggregate clusters using Drain3."
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to the combined log file or single log file to analyze."
    )
    parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path for output JSON containing structured clusters and insights."
    )
    parser.add_argument(
        "--sim-th",
        type=float,
        default=0.4,
        help="Drain similarity threshold (0.0 - 1.0, default: 0.4)."
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=4,
        help="Drain parse tree depth (min: 3, default: 4)."
    )
    parser.add_argument(
        "--max-children",
        type=int,
        default=100,
        help="Max children per parse tree node (default: 100)."
    )
    parser.add_argument(
        "--max-clusters",
        type=int,
        default=None,
        help="Max clusters in LRU cache (default: unlimited)."
    )
    parser.add_argument(
        "--config-file",
        type=str,
        default=None,
        help="Optional path to a custom drain3.ini file."
    )
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="Inspect file characteristics and recommend configuration without running full mining."
    )

    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"Error: Input file does not exist: {args.input}", file=sys.stderr)
        sys.exit(1)

    if args.inspect_only:
        stats = inspect_log_characteristics(args.input)
        print(json.dumps(stats, indent=2))
        sys.exit(0)

    try:
        results = analyze_logs(
            input_path=args.input,
            output_path=args.output,
            sim_th=args.sim_th,
            depth=args.depth,
            max_children=args.max_children,
            max_clusters=args.max_clusters,
            config_file=args.config_file
        )
        summary = results["summary"]
        print(f"Analysis complete: {summary['total_lines_processed']} lines processed in "
              f"{summary['processing_time_seconds']}s -> {summary['total_clusters']} clusters extracted.")
        print(f"Results saved to: {args.output}")
    except Exception as e:
        print(f"Error during Drain3 analysis: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
