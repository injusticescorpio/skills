---
name: log-analyzer-with-drain3
description: Analyze application logs and extract insights about errors, warnings, recurring failures, abnormal patterns, and root causes using Drain3 log template mining while keeping raw logs out of context. Make sure to use this skill whenever the user asks to analyze logs, inspect log files, debug application crashes, monitor system errors, or investigate issues across stdout/stderr/application logs.
compatibility: Requires uv (for PEP 723 self-contained script execution)
---

# Log Analyzer with Drain3

Analyze application logs (single files or directories containing multiple log files) using Drain3 template mining. This skill executes self-contained scripts via `uv run` to discover, merge, and cluster large raw logs into structured JSON summaries, and then directly generates a deterministic HTML report from the template in `assets/report_template.html`.

## Available Scripts

- **`scripts/combine_logs.py`** — Discovers and merges log files from a directory into a single stream with source provenance.
- **`scripts/drain3_analyzer.py`** — Incrementally clusters logs and aggregates statistics using Drain3 (declares `drain3` in PEP 723 metadata).

---

## 1. Mandatory Input Requirement

- **Log Directory or File**: The skill requires a path to a log directory (or log file).
- **If missing**: Ask the user to provide the log directory path before proceeding. Do not assume or guess a default path.

---

## 2. Expected Flow

```
User provides log directory
          ↓
[1] Discover & combine log files (uv run scripts/combine_logs.py)
          ↓
[2] Inspect characteristics (uv run scripts/drain3_analyzer.py --inspect-only)
          ↓
[3] Run Drain3 clustering (uv run scripts/drain3_analyzer.py)
          ↓
[4] Analyze processed output (Read structured JSON, extract insights)
          ↓
[5] Generate deterministic HTML report under log-analysis-report/<report>.html
    (Read assets/report_template.html and fill in the structured sections)
```

The raw logs should **never** be passed directly into the LLM context. Heavy processing is handled by the local scripts, providing the LLM with aggregated templates, counts, errors, warnings, examples, timestamps, and distributions.

---

## 3. Step-by-Step Execution Guide

### Step 1: Discover & Combine Logs

When a directory containing logs (`*.log`, `stdout.log`, `stderr.log`, `application.log`, `error.log`, etc.) is provided, combine them into a single file while preserving source provenance:

```bash
uv run skills/log-analyzer-with-drain3/scripts/combine_logs.py \
  --log-dir /path/to/logs \
  --output /tmp/combined_logs.log
```

*(If the user provides a single log file directly, you can skip to Step 2).*

### Step 2: Inspect Log Characteristics & Select Drain3 Config

**2a. Discover available flags** by running the script with `--help`:

```bash
uv run skills/log-analyzer-with-drain3/scripts/drain3_analyzer.py --help
```

**2b. Inspect log characteristics** (file size, lines, log levels, avg token length, unique-line ratio):

```bash
uv run skills/log-analyzer-with-drain3/scripts/drain3_analyzer.py \
  --input /tmp/combined_logs.log \
  --output /tmp/drain3_analysis.json \
  --inspect-only
```

**2c. Spawn a subagent to determine the best configuration.**
Pass it:
- The full `--help` output (all available flags and their descriptions)
- The full `--inspect-only` output (observed log characteristics)
- The contents of [`references/drain3-reference.md`](references/drain3-reference.md)

Ask the subagent to reason holistically across the logs, their observed characteristics, the available flags, and the reference documentation, then return the exact flags and values to use in Step 3. Apply that recommendation directly — do not fall back to hardcoded values.

### Step 3: Run Drain3 Clustering

Execute Drain3 mining to generate the structured output JSON:

```bash
uv run skills/log-analyzer-with-drain3/scripts/drain3_analyzer.py \
  --input /tmp/combined_logs.log \
  --output /tmp/drain3_analysis.json \
  <flags and values recommended by the subagent in Step 2c>
```

### Step 4: Analyze Processed Output & Formulate Insights

Read `/tmp/drain3_analysis.json`. This lightweight structured output contains:
- `summary`: Total lines, clusters, error/warning counts, source breakdown, engine config.
- `error_patterns`: Clusters where dominant level is ERROR or CRITICAL.
- `warning_patterns`: Clusters where dominant level is WARNING.
- `top_patterns`: Top clusters sorted by frequency.
- `all_clusters`: Full cluster list with templates, occurrence counts, time bounds, and representative samples.

Identify actionable insights:
- **Frequent errors & exceptions**: Repeated stack traces, unhandled errors, assertion failures.
- **Timeouts & connection failures**: Network latency, database drops, downstream service timeouts.
- **HTTP / API errors**: 4xx / 5xx error spikes and failing endpoints.
- **Authentication / authorization**: Repeated 401/403 or token expiries.
- **Abnormal patterns**: Sudden bursts, crash/restart loops, polling runaway.

*Distinguish clearly between direct observed log evidence and potential hypotheses.*

### Step 5: Generate Deterministic HTML Report

1. Create directory `log-analysis-report/` under the current working directory if it does not already exist.
2. Read the HTML template from `skills/log-analyzer-with-drain3/assets/report_template.html`.
3. Populate the template with the concrete analysis data and insights:
   - `{{REPORT_TITLE}}`: Descriptive title (e.g., "Production Service Log Analysis")
   - `{{GENERATION_TIME}}`: Current UTC timestamp
   - `{{LOG_SOURCES}}`: List of analyzed log files/sources
   - `{{DRAIN_DEPTH}}`, `{{DRAIN_SIM_TH}}`: Used Drain3 settings
   - `{{TOTAL_LINES}}`, `{{TOTAL_CLUSTERS}}`, `{{ERROR_COUNT}}`, `{{WARNING_COUNT}}`: Key metrics
   - `{{EXECUTIVE_SUMMARY}}`: High-level summary of health, primary failure modes, and impact
   - `{{POTENTIAL_ISSUES_HTML}}`: Structured issue cards (title, description, and observed log evidence)
   - `{{ERROR_PATTERNS_ROWS}}`: Table rows of error templates with samples, counts, timestamps, and sources
   - `{{WARNING_PATTERNS_ROWS}}`: Table rows of warning templates
   - `{{TOP_PATTERNS_ROWS}}`: Table rows of top volume templates
   - `{{RECOMMENDATIONS_HTML}}`: Targeted investigation steps and actionable recommendations
4. Write the finalized HTML report to `log-analysis-report/report.html` (or `log-analysis-report/<service>-analysis.html`).
5. Provide a clear, concise overview in your response with the path to the report.

---

## 4. Key Rules

1. **Context Management**: Never read raw log files into LLM context. Always run the local processing scripts via `uv run` to keep the context clean and efficient.
2. **Deterministic Output**: Always use the provided template in `assets/report_template.html` so the report layout and styling remain consistent across every execution.
3. **Evidence-Based Insights**: Every issue or claim must be backed by concrete Drain3 cluster IDs, templates, sample lines, or frequency metrics.
