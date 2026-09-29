# Drain3 Log Analyzer Skill

A high-performance log analysis skill for AI agents using Drain3 log template mining. It discovers, combines, and clusters large multi-file application logs into structured template representations without exhausting LLM context windows, and renders a deterministic HTML report from `assets/report_template.html`.

All scripts are **self-contained** adhering to **PEP 723** (`# /// script ... ///`) and executed seamlessly using [`uv run`](https://docs.astral.sh/uv/).

## Structure

```
log-analyzer-with-drain3/
├── SKILL.md                          # Agent instructions and workflow definition
├── README.md                         # Skill overview & CLI usage instructions
├── references/
│   └── drain3-reference.md           # Lightweight Drain3 configuration & tuning guide
├── scripts/
│   ├── combine_logs.py               # Discovers and merges log files with provenance (PEP 723)
│   └── drain3_analyzer.py            # Mines templates and aggregates statistics using Drain3 (PEP 723)
└── assets/
    └── report_template.html          # Standardized responsive HTML report template
```

## Quick Start (with `uv run`)

```bash
# 1. Combine logs from a directory
uv run skills/log-analyzer-with-drain3/scripts/combine_logs.py \
  --log-dir /path/to/logs \
  --output /tmp/combined.log

# 2. Inspect characteristics & mine clusters
uv run skills/log-analyzer-with-drain3/scripts/drain3_analyzer.py \
  --input /tmp/combined.log \
  --output /tmp/analysis.json \
  --sim-th 0.4 \
  --depth 4

# 3. Formulate insights and render log-analysis-report/report.html using assets/report_template.html
```
