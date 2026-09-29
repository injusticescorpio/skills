# Drain3 Reference & Configuration Guide

Drain3 is an online, streaming log template miner based on the Drain algorithm (He et al., ICWS 2017). It extracts structured log templates (clusters) from raw unstructured log messages in real time using a fixed-depth parse tree.

---

## 1. How Drain3 Works

Raw log messages often contain static boilerplate text mixed with dynamic variables (IP addresses, timestamps, process IDs, user IDs, error codes). Drain3 replaces dynamic values with mask tokens (e.g., `<:IP:>`, `<:NUM:>`) or generic wildcards (`<*>`) and clusters similar log messages into templates.

### High-Level Workflow:
1. **Preprocessing / Masking**: Configured regular expressions mask dynamic patterns (IPs, numbers, hex, UUIDs) before parsing.
2. **Tokenization & Tree Search**: The log message is split into tokens. Drain3 traverses a fixed-depth search tree:
   - **Level 1**: Root node.
   - **Level 2**: Log message length (number of tokens).
   - **Level 3 to (depth - 1)**: First $(d - 2)$ tokens of the log message (tokens containing digits or wildcards are treated specially).
   - **Leaf Node**: Contains a list of candidate log clusters with the same prefix.
3. **Similarity Calculation**: Drain3 computes token-level similarity between the incoming message and candidate templates in the leaf node:
   $$\text{sim}(T_1, T_2) = \frac{\sum_{i=1}^n \mathbf{1}(T_{1,i} == T_{2,i})}{n}$$
   If $\text{sim} \ge \text{sim\_th}$, the message joins the matching cluster and the cluster template is updated with `<*>` for differing token positions.
4. **Cluster Creation**: If no candidate meets the similarity threshold, a new cluster is created.

---

## 2. Core Configuration Parameters

Drain3 is configured via an `.ini` file or programmatically with `TemplateMinerConfig`.

### `[DRAIN]` Section

| Parameter | Type | Default | Description | Tuning Guidance |
| :--- | :--- | :--- | :--- | :--- |
| `sim_th` | float | `0.4` | **Similarity Threshold** ($0.0 - 1.0$). Minimum ratio of matching tokens required to assign a log message to an existing cluster. | • **Lower (0.3 - 0.4)**: Fewer, more generic clusters. Good for noisy logs or when broad grouping is desired.<br>• **Higher (0.5 - 0.7)**: Stricter matching, more distinct clusters. Prevents unrelated logs from merging. |
| `depth` | int | `4` | **Max parse tree depth** (min `3`). Determines how many leading tokens are used as routing keys in the tree. | • **Default (4)**: Inspects token count + 1st token.<br>• **Higher (5-6)**: Use when logs share identical first words but diverge in subsequent words. |
| `max_children` | int | `100` | Max branches / child nodes per tree node. | Increase if logs have high token vocabulary at early positions. |
| `max_clusters` | int/None | `None` | Max active clusters kept in LRU cache. | Set to e.g. `1024` or `2048` for memory-constrained environments or endless streams. |
| `extra_delimiters` | list | `[]` | Additional characters used to split words (e.g. `["_", "="]`). | Add symbols like `_`, `=`, `:`, `/` if variable names are joined without spaces. |
| `parametrize_numeric_tokens` | bool | `True` | Treat any token containing at least one digit as a parameter token (`<*>`). | Keep `True` unless numeric tokens convey specific log types (e.g., HTTP status codes where 404 vs 200 matters). |
| `engine` | str | `Drain` | Clustering engine (`Drain` or `JaccardDrain`). | `Drain` is standard token-order matching. `JaccardDrain` uses Jaccard set similarity. |

### `[MASKING]` Section

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `masking` | JSON array | `[]` | List of regex patterns: `[{"regex_pattern": "...", "mask_with": "TAG"}]` |
| `mask_prefix` | str | `"<"` | Prefix delimiter for masked values (e.g., `<:IP:>`). |
| `mask_suffix` | str | `">"` | Suffix delimiter for masked values. |

#### Standard Recommended Masking Patterns:
- **IP Address**: `((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})((?=[^A-Za-z0-9])|$)` -> `IP`
- **Hex/UUID**: `((?<=[^A-Za-z0-9])|^)(0x[a-f0-9A-F]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})((?=[^A-Za-z0-9])|$)` -> `HEX_ID`
- **Numbers**: `((?<=[^A-Za-z0-9])|^)([\-\+]?\d+)((?=[^A-Za-z0-9])|$)` -> `NUM`
- **Quoted Strings**: `(?<=executed cmd )(".+?")` -> `CMD`

---

## 3. Best Practices for Preprocessing Logs

1. **Strip Timestamps and Prefixes for Clustering**:
   Drain3 groups by token position and length. Raw timestamps (e.g., `2025-02-17 14:02:11,123`) vary on every line, making message length and positions identical only if masked or stripped.
   - *Best approach*: Extract timestamp, log level, and source file into structured fields, and feed only the log payload/message body to Drain3.
2. **Preserve Metadata**:
   Retain line references, log levels (`ERROR`, `WARN`, `INFO`), timestamp bounds (first/last seen), and sample occurrences to enable downstream root cause analysis.
3. **Handling Stack Traces**:
   Multi-line stack traces should either be joined with their parent log line or clustered with a dedicated exception mask to avoid exploding cluster count.
