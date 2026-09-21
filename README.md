# VelixAgent

**A powerful multimodal AI coding agent.**

> ⚠️ **Phase 1 — CLI Foundation**
>
> VelixAgent is under active, phased development. Phase 1 establishes the
> command-line foundation. **AI execution is intentionally not implemented
> in Phase 1.** The agent cannot yet edit repositories, run commands, reason
> autonomously, or use an LLM.

---

## What is VelixAgent?

VelixAgent is intended to become a powerful multimodal AI coding agent that
can understand software projects, reason about complex development tasks,
work with text, images, documents, audio, and video, use developer tools,
modify code safely, execute commands under controlled permissions, verify
its own work, remember relevant context, and recover from failures.

### Long-term Vision

```
USER → Multimodal Input → Understanding Engine → Memory → Planner
     → Tool System → Executor → Observer → Verifier
     → Success (Response) or Failure (Replan → Executor)
```

### Current Status

Phase 1 provides a complete CLI foundation:

- ✅ One-shot command execution
- ✅ Interactive REPL with history
- ✅ Typed configuration (env vars + defaults)
- ✅ Cross-platform path handling
- ✅ Rich terminal rendering
- ✅ Centralized error hierarchy
- ✅ Debug mode and structured logging
- ✅ Comprehensive test suite

### What Phase 1 Does NOT Implement

- ❌ LLM / AI model integration
- ❌ Multimodal processing (images, audio, video, documents)
- ❌ Code modification or shell execution
- ❌ Git integration
- ❌ Planning, reasoning, or autonomous loops
- ❌ Tool registry or function calling
- ❌ RAG, embeddings, or vector databases
- ❌ Memory or context persistence
- ❌ Sandboxing or permission systems

These capabilities will be added in future phases.

---

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager

---

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd velix-agent

# Install with uv
uv sync
```

---

## CLI Usage

### One-shot Mode

Pass a task as an argument:

```bash
uv run velix "fix the failing tests"
```

Phase 1 acknowledges the task with a placeholder response.

### Interactive REPL

Launch without arguments:

```bash
uv run velix
```

This starts an interactive session with persistent history, command
completion, and slash commands.

### Version

```bash
uv run velix --version
```

### Help

```bash
uv run velix --help
```

### Configuration

```bash
uv run velix config
```

### Debug Mode

```bash
uv run velix --debug "analyze this code"
```

---

## REPL Slash Commands

| Command    | Description                      |
|------------|----------------------------------|
| `/help`    | Show available commands          |
| `/clear`   | Clear the terminal screen        |
| `/config`  | Show current configuration       |
| `/version` | Show VelixAgent version          |
| `/exit`    | Exit VelixAgent                  |
| `/quit`    | Exit VelixAgent                  |

Any other text input is treated as a coding task (placeholder in Phase 1).

---

## Configuration

VelixAgent uses environment variables with the `VELIX_` prefix:

| Variable               | Default     | Description                     |
|------------------------|-------------|---------------------------------|
| `VELIX_DEBUG`          | `false`     | Enable debug mode               |
| `VELIX_LOG_LEVEL`      | `WARNING`   | Logging level                   |
| `VELIX_HISTORY_ENABLED`| `true`      | Enable persistent REPL history  |
| `VELIX_HISTORY_FILE`   | *(auto)*    | Custom path for history file    |

Copy `.env.example` to `.env` to configure locally:

```bash
cp .env.example .env
```

### Configuration Precedence

1. Explicit CLI options (highest)
2. Environment variables
3. `.env` file
4. Application defaults (lowest)

---

## Development

### Run Tests

```bash
uv run pytest
```

### Run Tests with Coverage

```bash
uv run pytest --cov
```

### Lint

```bash
uv run ruff check .
```

### Format Check

```bash
uv run ruff format --check .
```

### Type Check

```bash
uv run mypy src
```

---

## Project Structure

```
velix-agent/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── src/
│   └── velix_agent/
│       ├── __init__.py          # Package + version
│       ├── main.py              # Entry point
│       ├── cli/
│       │   ├── app.py           # Typer CLI application
│       │   ├── repl.py          # Interactive REPL
│       │   ├── commands.py      # Slash command dispatch
│       │   └── console.py       # Rich console helpers
│       ├── core/
│       │   ├── config.py        # Pydantic-settings configuration
│       │   ├── errors.py        # Error hierarchy
│       │   ├── logging.py       # Logging setup
│       │   └── runtime.py       # Application runtime
│       └── utils/
│           └── paths.py         # Cross-platform path utilities
└── tests/
    ├── unit/
    │   ├── test_config.py
    │   ├── test_runtime.py
    │   └── test_paths.py
    └── integration/
        ├── test_cli.py
        └── test_repl.py
```

---

## License

MIT
