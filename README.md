# CodeCoverage CLI

AI-powered test generation and documentation for Python codebases.

CodeCoverage analyses your project, learns your existing test style, and generates tests and documentation using an LLM agent — function by function or across a whole module.

---

## Features

- **`generate`** — Generate a pytest/unittest test for any Python function. The agent reads your existing test style first and replicates it exactly.
- **`diff-test`** — Generate or update tests for functions that changed in a git diff (uncommitted, last commit, since a branch).
- **`document`** — Write `FLOWS.md` (entry points + call chains) and `SUMMARY.md` (per-function docs) from your codebase.
- **`serve`** — Browse your API as a live Swagger UI.

---

## Requirements

- Python 3.10+
- One of:
  - Anthropic API key (`ANTHROPIC_API_KEY`)
  - OpenAI API key (`OPENAI_API_KEY`) + `pip install langchain-openai`
  - Cursor IDE with an API key (`CURSOR_API_KEY`)

---

## Installation

### From PyPI

```bash
pip install codecoverage-cli
```

For OpenAI provider support:

```bash
pip install codecoverage-cli langchain-openai
```

### Local development install

```bash
git clone https://github.com/AbhigyaShridhar/codecoverage-cli
cd codecoverage-cli
pip install -e ".[dev]"
```

---

## Quick Start

### 1. Initialise your project

```bash
cd /path/to/your/project
codecoverage init
```

This creates `.codecoverage.toml` with sensible defaults. **Do not commit API keys** — use environment variables instead (see [Configuration](#configuration)).

### 2. Generate tests

```bash
# Generate tests for every function in the project (bulk mode)
codecoverage generate

# Limit bulk generation to a subdirectory
codecoverage generate --dir payments/interface_layer/

# Generate tests for every function in one file
codecoverage generate --file payments/gateway.py

# Generate a test for a single function
codecoverage generate -f my_function --file src/module.py

# Steer the agent with extra instructions
codecoverage generate --dir payments/ -x "focus on celery tasks and APIs"

# Preview what would be generated without making LLM calls
codecoverage generate --dir payments/ --dry-run
```

The agent parses the codebase once, then makes **one LLM call per function**, keeping context focused. For each function it:
1. Scans existing tests in that module to learn the style (framework, fixtures, mock library)
2. Reads the source function and its dependencies
3. Writes a test file, auto-placing it in your existing test root

### 3. Generate tests from a git diff

```bash
# Test uncommitted changes (default)
codecoverage diff-test

# Test what the last commit changed
codecoverage diff-test --last-commit

# Test everything changed since branching off main
codecoverage diff-test --since main

# Preview without calling the LLM
codecoverage diff-test --dry-run
```

### 4. Generate documentation

```bash
# Render FLOWS.md and SUMMARY.md from already-cached docs
codecoverage document

# Enrich a module with LLM-generated summaries, then render
codecoverage document --enrich payments/gateway/

# Write to a custom directory
codecoverage document --output docs/
```

### 5. Browse your API

```bash
codecoverage serve
# Opens Swagger UI at http://localhost:8080

codecoverage serve --port 9000 --no-browser
```

---

## Configuration

`codecoverage init` creates `.codecoverage.toml` in the project root:

```toml
[project]
name = "my-project"

[parsing]
ignore_patterns = [
    "venv/", "env/", ".venv/",
    "node_modules/", ".git/",
    "__pycache__/", "*.pyc",
    "dist/", "build/", "migrations/",
    "static/",
]

[llm]
provider    = "anthropic"        # anthropic | openai | cursor
model       = "claude-sonnet-4-6"
temperature = 0.0

# API keys — prefer environment variables instead of hardcoding here
# anthropic_api_key = "sk-ant-..."
# openai_api_key    = "sk-proj-..."
# cursor_api_key    = "crsr_..."

[generation]
max_retries = 3
```

### Environment variables

| Variable | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | `--provider anthropic` |
| `OPENAI_API_KEY` | `--provider openai` |
| `CURSOR_API_KEY` | `--provider cursor` |

Environment variables always take priority over values in the config file.

---

## LLM Providers

| Provider | `--provider` flag | Default model | Requires |
|---|---|---|---|
| Anthropic | `anthropic` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `gpt-4o` | `OPENAI_API_KEY` + `pip install langchain-openai` |
| Cursor | `cursor` | `sonnet-4.6` | Cursor IDE installed, `CURSOR_API_KEY` |

Override per-run with `--provider` and `--model`:

```bash
codecoverage generate -f my_fn --file src/foo.py --provider openai --model gpt-4o-mini
codecoverage generate -f my_fn --file src/foo.py --provider cursor --model opus-4.6
```

---

## Command Reference

### `codecoverage init`

Creates `.codecoverage.toml` in the current directory with interactive prompts.

```bash
codecoverage init [--path DIR]
```

---

### `codecoverage generate`

Generate tests for functions. Works in three modes:

| Invocation | What happens |
|---|---|
| `codecoverage generate` | Generate tests for **every function** in the project |
| `codecoverage generate --file src/mod.py` | Generate tests for every function in that file |
| `codecoverage generate -f my_fn --file src/mod.py` | Generate a test for one specific function |

The codebase is parsed **once** at startup. The agent is then called **once per function** so context stays focused and token use stays manageable.

```
Options:
  -f, --function TEXT      Function name. If omitted, all functions are processed.
  --file TEXT              Source file (relative to project root). If omitted, all files are processed.
  --dir DIR                Limit bulk generation to this subdirectory (relative to project root).
                           Ignored when --file is specified.
  --path PATH              Project root  [default: .]
  --provider CHOICE        anthropic | openai | cursor
  --model TEXT             Model name (overrides config default)
  -o, --output PATH        Output file path (single-function mode only; default: auto-detected)
  --dry-run                Show which functions would be processed without making LLM calls
  -x, --extra-context TEXT Extra instructions passed verbatim to the agent for every function.
  --overwrite              Regenerate tests even for files that already have a test file.
  --config PATH            Config file path
```

**Mode summary:**

| Flags | Scope |
|---|---|
| *(none)* | Every function in the entire project |
| `--dir payments/` | Every function under `payments/` |
| `--file payments/gateway.py` | Every function in that file |
| `-f process --file payments/gateway.py` | One specific function |

**Existing test detection (bulk and per-file modes)**

In bulk mode (`codecoverage generate`) and per-file mode (`codecoverage generate --file ...`), the tool checks whether a test file already exists for each source file before making any LLM call. Files with existing tests are skipped and reported as a count at the start of the run:

```
⊘  42 function(s) in files with existing tests skipped — pass --overwrite to regenerate.
```

Pass `--overwrite` to regenerate tests for all files regardless. Single-function mode (`-f --file`) always proceeds and is unaffected by this check.

**Agent skip decisions**

Even for files without existing tests, the agent is allowed to decline generating a test. It will do this when a function is not worth testing — Django/framework entry points (`manage.py`, `wsgi.py`), migration files, trivial one-liner passthroughs, `__str__`/`__repr__` with only attribute assignment, etc. Skipped functions are shown in yellow with a reason:

```
⊘  main: Django entry point with no testable logic
```

Skips are reported separately from failures in the final summary:

```
Done.  12 succeeded  8 skipped  0 failed
```

The agent also respects `--extra-context` when deciding whether to skip. If you say `-x "focus on celery tasks, APIs and models"`, functions clearly outside those areas will be skipped rather than generating empty or unhelpful tests.

**`--extra-context` / `-x`**

Passes additional instructions verbatim to the agent for every function. Use this to steer *how* tests are written, not to scope *which* files are processed (use `--file` for that):

```bash
# Focus on edge cases, skip boilerplate assertions
codecoverage generate --file payments/gateway.py -x "skip boilerplate, focus on edge cases"

# Let the agent decide whether a legacy module is worth testing
codecoverage generate --file legacy/utils.py -x "decide whether this module is worth testing"

# Enforce a specific style
codecoverage generate -f process -x "use hypothesis for property-based tests"
```

Applies equally in single-function, per-file, and bulk modes.

**Output path auto-detection** (when `-o` is not specified):

1. Scans the project for all `test_*.py` and `*_test.py` files (excludes `venv/`, `env/`, etc.)
2. Walks each test file's ancestor directories to find the nearest directory named `tests`, `unit_tests`, `specs`, etc.
3. Picks the most frequently occurring such directory as the **test root**
4. Mirrors the source file's path under that root:
   - `payments/gateway/views.py` → `unit_tests/tests/payments/gateway/test_views.py`
5. Falls back to `<source_dir>/tests/test_<name>.py` if no existing test layout is found

---

### `codecoverage diff-test`

Generate or update tests for functions that changed in git.

```
Options:
  --working              [default] Diff uncommitted changes vs HEAD
  --last-commit          Diff the most recent commit against its parent
  --last-merge           Diff the most recent merge commit
  --since REF            Diff HEAD against a branch, tag, or commit SHA
  --dry-run              Show plan without making LLM calls
  --output-dir DIR       Write generated tests here (mirrors source structure)
  --provider / --model   (same as generate)
  --path PATH            Project root
  --config PATH          Config file path
```

**Actions per changed function:**

| Change type | Action |
|---|---|
| Added | Generate a fresh test; if a test file already exists for that module, update it instead |
| Modified | Always overwrites the existing test with minimal changes |
| Deleted | Report orphaned tests for manual review — no auto-delete |

`diff-test` always overwrites existing tests for modified functions — that is its purpose. A `.py.bak` backup of the original test file is created beside it before overwriting. This is intentionally different from `generate`, which skips files with existing tests by default and requires `--overwrite` to proceed.

---

### `codecoverage document`

Write codebase documentation to markdown files.

```
Options:
  --path PATH          Project root  [default: .]
  --output PATH        Output directory  [default: .codecoverage/docs/]
  --enrich DIR         Run LLM doc generation for all functions under DIR
                       (skips already-cached). DIR is relative to --path.
  --working            Update docs for uncommitted changes vs HEAD
  --last-commit        Update docs for functions changed in the last commit
  --last-merge         Update docs for functions changed in the last merge commit
  --since REF          Update docs for everything changed since a branch/tag/SHA
  --dry-run            Show which functions would be re-documented (no LLM calls)
  --provider / --model (same as generate)
  --config PATH        Config file path
```

**Three enrichment modes:**

| Mode | When to use |
|---|---|
| `--enrich DIR` | First-time documentation of a module |
| `--working` / `--last-commit` / `--since REF` | Incremental update after code changes |
| *(none)* | Just re-render FLOWS.md and SUMMARY.md from the existing cache |

The diff modes mirror `diff-test` exactly: added/modified functions are re-documented, deleted functions are removed from the cache.

**Output files:**

| File | Contents |
|---|---|
| `FLOWS.md` | All HTTP endpoints, Celery tasks, signal handlers and management commands, each with its full call chain and decoupled flows. LLM summaries shown as block quotes. |
| `SUMMARY.md` | All LLM-documented functions grouped by source file, with test coverage links. |

Function summaries are cached in `.codecoverage/doc_cache.json` so re-running `document` is fast — only new or changed functions are re-enriched.

---

### `codecoverage serve`

Start a local Swagger UI server to browse your project's API.

```
Options:
  --path PATH         Project root  [default: .]
  --port INT          Port number  [default: 8080]
  --no-browser        Don't auto-open the browser
```

---

## How the Codebase is Analysed

CodeCoverage parses Python source files using the standard `ast` module (no runtime import required). It extracts:

- Module-level and class-level functions with full decorator details
- Class inheritance chains (for DRF/Django CBV HTTP method inference)
- Decorator arguments (`@app.route("/path", methods=["POST"])`, `@shared_task(bind=True)`, etc.)
- Cross-file call chains (BFS-limited to avoid runaway depth)
- Decoupled flows: functions invoked by the framework via decorators (signals, pre/post transitions, Celery tasks)

The parsed representation is kept in memory — no database required.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run the test suite
pytest

# Run without coverage (faster)
pytest --no-cov

# Lint
ruff check src/

# Type check
mypy src/codecoverage/
```

---

## Limitations

- **Cursor provider** requires Cursor IDE to be installed locally. It uses `cursor agent --print` as a subprocess (no API endpoint). Prompts with very large source files may hit OS argument length limits.
- **Generated tests are not auto-run.** The tool writes test files to disk; you should run `pytest` to validate them. Import paths in generated tests may need adjustment for unusual project layouts.
- **Full codebase parse on every invocation.** There is no incremental parse cache — the entire project is re-parsed on each `generate` / `document` / `diff-test` call.
- **Python 3.10+ required** to run the CLI itself. Generated tests can target older Python versions if your LLM config or project conventions guide the agent accordingly.
- **OpenAI provider** requires `pip install langchain-openai` separately (not bundled to keep the base install lightweight).
