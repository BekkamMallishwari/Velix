# VelixAgent

**A powerful, extensible AI coding assistant and command-line agent.**

VelixAgent is an AI-powered development assistant designed to run directly from your terminal. By deeply integrating large language models (LLMs) with secure, constrained system access, VelixAgent operates as an intelligent pair programmer right in your local environment.

---

## Installation

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/) (recommended) or pip.

```bash
# Clone the repository
git clone <repository-url>
cd velix-agent

# Set up the virtual environment and install dependencies
uv sync --all-extras

# Activate the virtual environment
source .venv/bin/activate

# Verify the installation
velix --version
```

Alternatively, install in editable mode with pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Quick Start

```bash
# One-shot mode — execute a single task
velix "add error handling to the parser module"

# Interactive REPL — persistent conversational session
velix

# Show resolved configuration
velix config

# Enable debug tracebacks
velix --debug "explain the auth flow"
```

A convenience script (`run.sh`) is also provided. It locates the virtual environment automatically:

```bash
./run.sh "fix the failing tests"
```

---

## CLI Reference

```
velix [OPTIONS] [TASK]
```

| Option          | Description                                      |
|-----------------|--------------------------------------------------|
| `TASK`          | A coding task to execute (one-shot mode), or `config` to show configuration. |
| `--version, -V` | Show the application version and exit.           |
| `--debug, -d`   | Enable debug mode (full tracebacks on error).    |
| `--one-shot`     | Explicit one-shot flag (optional when providing a TASK). |

If `TASK` is omitted, VelixAgent starts the interactive REPL with persistent history.

---

## Configuration

VelixAgent uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) with a `VELIX_` environment-variable prefix. Values are resolved in this order (highest precedence first):

1. CLI options (e.g. `--debug`)
2. `.env` file in the project root
3. OS environment variables
4. Application defaults

Copy the provided template to create your environment file:

```bash
cp .env.example .env
```

### General Settings

| Variable                  | Default      | Description                                  |
|---------------------------|-------------|----------------------------------------------|
| `VELIX_DEBUG`             | `false`     | Enable debug mode.                           |
| `VELIX_LOG_LEVEL`         | `WARNING`   | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `VELIX_MAX_INPUT_FILE_SIZE` | `15728640` (15 MB) | Maximum file size for multimodal inputs. |
| `VELIX_MAX_TOOL_OUTPUT_SIZE` | `8000`   | Maximum tool-output string length sent to the provider. |
| `VELIX_ENABLE_MEMORY`    | `true`      | Enable SQLite-based memory system.           |
| `VELIX_HISTORY_ENABLED`  | `true`      | Enable persistent REPL command history.      |

---

## Shadow Workspace Mode

Shadow mode runs all agent file operations and shell commands inside a temporary, isolated copy of your project. The host workspace is never modified.

> **Status:** Experimental. Shadow mode provides directory-level isolation via a full file copy. It is not a security sandbox — it does not restrict network access, process spawning, or system calls beyond confining file paths to the shadow directory.

### Enabling Shadow Mode

```bash
# Via environment variable
export VELIX_USE_SHADOW_WORKSPACE=true
velix "refactor the database module"

# Or in .env
VELIX_USE_SHADOW_WORKSPACE=true
```

### How It Works

1. On task start, the agent's host workspace is recursively copied into a temporary directory (the *shadow root*).
2. `.git` directories are excluded. Symlinks that escape the workspace boundary are skipped.
3. The agent's working directory (`cwd`) and all filesystem tools (read, write, edit, search, list) are rebound to the shadow root.
4. Shell commands (`RunCommandTool`) execute with the shadow root as their working directory.
5. On completion — whether success, failure, exception, or `KeyboardInterrupt` — the shadow directory is removed.

### Shadow Workspace Environment Variables

| Variable                     | Default       | Description                                   |
|------------------------------|---------------|-----------------------------------------------|
| `VELIX_USE_SHADOW_WORKSPACE` | `false`       | Enable shadow workspace isolation.            |
| `VELIX_SHADOW_MAX_FILES`     | `100000`      | Maximum file/directory entries allowed during seeding. |
| `VELIX_SHADOW_MAX_BYTES`     | `2147483648` (2 GB) | Maximum total bytes allowed during seeding. |

### Limitations

- **No automatic write-back.** Changes made inside the shadow workspace are discarded on cleanup. There is currently no `apply_plan()` or synchronization mechanism.
- **Not a security sandbox.** Shadow mode isolates file paths but does not restrict network, IPC, or process-level access. For process-level sandboxing, see the Sandbox Architecture section below.
- **Large projects.** Seeding copies every file (excluding `.git`). Projects exceeding `VELIX_SHADOW_MAX_FILES` or `VELIX_SHADOW_MAX_BYTES` will fail with a `SeedingFailedError`.
- **Platform behavior.** File-descriptor-based directory traversal (`O_DIRECTORY | O_NOFOLLOW`) is used on platforms that support it. Cleanup uses `shutil.rmtree` with permission-repair fallbacks.

---

## Sandbox Architecture

VelixAgent uses a platform-specific sandbox architecture to isolate tool execution, with **macOS and Windows as the only supported platforms**:

*   **macOS (Supported):** Uses Apple Seatbelt (`sandbox-exec`) profile generation.
    *   *Enforced:* Workspace filesystem isolation, network denial (outbound & localhost), `RLIMIT_CPU` limits, execution timeouts, output truncation, and secret redaction.
    *   *Security Limitation:* Double-forked processes that reparent to PID 1 (`launchd`) escape user-space process-tree walks because Darwin lacks kernel PID namespaces. Session-leader termination and workspace confinement remain strictly enforced.
*   **Windows (Supported):** Uses native Win32 Job Objects via ctypes (`SetInformationJobObject`).
    *   *Enforced:* Process tree containment, execution timeouts, active process limits, memory limits, output truncation, and secret redaction. **Does not require Administrator privileges.**
    *   *Security Limitation:* Native filesystem and network isolation are currently **unsupported** (no AppContainer or Windows Filtering Platform rules). Tests requiring filesystem/network isolation skip on Windows; skips are never treated as proof of isolation.
*   **Linux (Unsupported):** Linux is explicitly unsupported for sandbox execution. The sandbox fails closed immediately with a `SandboxError` (`"Sandbox backend unavailable for platform: Linux"`). It **never** silently falls back to unrestricted subprocess execution.

---

## What It Does

VelixAgent solves the friction of context-switching between your code editor and a web-based AI chat. It dynamically interacts with your repository, interpreting development requests and autonomously invoking system tools to gather context or execute changes.

Instead of manually copy-pasting code snippets, you simply ask VelixAgent to investigate or modify the codebase. It formulates a plan, leverages its tools to read, search, or edit files, and iteratively works through the task until it reaches a resolution.

## Key Capabilities

- **Autonomous Tool Execution:** Natively uses system tools to read, write, and safely edit files, explore directories, search file contents, and execute shell commands inside your workspace.
- **Iterative Reasoning Loop:** Dynamically adjusts its plan based on command output or file contents, looping through multiple tool calls in a single turn to fully resolve complex tasks.
- **Interactive REPL & One-Shot Mode:** Work conversationally with persistent history using the interactive REPL, or pass a specific task directly via the CLI for instant one-shot execution.
- **Multi-Provider Fallback:** Connects to major LLM providers (including Google Gemini, OpenAI, Anthropic, OpenRouter, and local models like Ollama) with an automatic fallback chain if the primary model encounters errors.
- **Robust Security Constraints:** File operations are strictly sandboxed to prevent arbitrary path traversal, and large outputs are intelligently truncated to optimize the LLM's context window.
- **Shadow Workspace Isolation:** Optionally execute tasks in a disposable copy of your project, keeping the original workspace untouched.

---

## Development

```bash
# Run the full test suite
.venv/bin/pytest -v --tb=short

# Run with coverage
.venv/bin/pytest --cov=velix_agent --cov-report=term-missing

# Lint and format
.venv/bin/ruff check src tests
.venv/bin/ruff format src tests

# Type checking
.venv/bin/mypy
```

---

## License

MIT — see [LICENSE](LICENSE) for details.
