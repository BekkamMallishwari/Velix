# VelixAgent

**A powerful, extensible AI coding assistant and command-line agent.**

VelixAgent is an AI-powered development assistant designed to run directly from your terminal. By deeply integrating large language models (LLMs) with secure, constrained system access, VelixAgent can understand complex codebases, execute commands, and autonomously complete development tasks through an iterative reasoning loop.

Whether you need to debug a script, search a large repository, or write new features, VelixAgent operates as an intelligent pair programmer right in your local environment.

---

## Overview

VelixAgent solves the friction of context-switching between your code editor and a web-based AI chat. By running locally via a CLI interface, VelixAgent can directly interact with your repository, meaning you don't have to manually copy-paste code snippets.

It connects to your choice of leading AI providers (including Google Gemini, OpenAI, Anthropic, OpenRouter, and Local models like Ollama) and executes a dynamic agentic loop: it receives a task, plans the required actions, utilizes system tools to read or modify the codebase, and iteratively feeds the results back to the LLM until the task is fully resolved.

---

## Key Capabilities

- **Autonomous Tool Execution:** The agent natively uses tools to read, write, and search files, list directories, and execute shell commands inside your workspace.
- **Iterative Reasoning Loop:** The agent can make up to 5 consecutive tool calls in a single turn, dynamically adjusting its plan based on command output or file contents.
- **Interactive REPL & One-Shot Execution:** Work conversationally with persistent history using the interactive REPL, or pass a specific task directly via the CLI for one-shot execution.
- **Multi-Provider Fallback:** Configure a chain of providers (e.g., Gemini -> OpenAI -> Local). If the primary model encounters a rate limit or error, VelixAgent automatically falls back to the next available provider.
- **Robust Security Constraints:** File and directory tools are safely sandboxed to the current working directory, preventing arbitrary path traversal attacks. Large outputs are intelligently truncated to prevent blowing out the LLM's context window.

---

## How It Works

VelixAgent's architecture is built on a modern, decoupled core:

1. **User Input:** You submit a task via the REPL or CLI arguments.
2. **Input Router & Session:** The input is parsed, and previous conversation history is loaded from the active session.
3. **Agent Loop:** The `Agent` core sends the context to the selected AI `Provider`.
4. **Tool Execution:** If the LLM requests actions, the `ToolRegistry` executes them securely (e.g., reading a file, searching a directory) and returns the output to the LLM.
5. **Resolution:** This loop continues until the LLM arrives at a final answer, which is rendered beautifully in your terminal.

---

## Technology Stack

- **Language:** Python 3.12+
- **CLI & UI:** `Typer` (command line routing), `prompt-toolkit` (interactive REPL), `Rich` (terminal formatting)
- **Configuration:** `pydantic-settings`, `python-dotenv`
- **Providers Supported:** `google-genai` (Gemini), `openai`, `anthropic`, OpenRouter, Local Models
- **Code Quality:** `ruff`, `mypy`, `pytest`

---

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package and project manager

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/BekkamMallishwari/Velix.git
   cd velix-agent
   ```

2. **Install dependencies using uv:**
   ```bash
   uv sync
   ```

---

## Configuration

VelixAgent is configured entirely via environment variables (prefixed with `VELIX_`).

To configure your agent, copy the example environment file and add your desired API keys:

```bash
cp .env.example .env
```

### Essential Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VELIX_DEFAULT_PROVIDER` | `gemini` | The primary AI provider (`gemini`, `openai`, `anthropic`, `openrouter`, `local`) |
| `VELIX_DEFAULT_MODEL` | `gemini-3.6-flash` | The specific model name to use |
| `VELIX_GEMINI_API_KEY` | *(None)* | Your Google Gemini API Key |
| `VELIX_OPENAI_API_KEY` | *(None)* | Your OpenAI API Key |
| `VELIX_ANTHROPIC_API_KEY` | *(None)* | Your Anthropic API Key |
| `VELIX_PROVIDER_CHAIN` | `["gemini", "openai", "openrouter", "local"]` | JSON array of providers for the fallback mechanism |
| `VELIX_DEBUG` | `false` | Enable verbose debug logging |
| `VELIX_HISTORY_ENABLED` | `true` | Enable persistent REPL conversation history |

*(Note: API keys are securely loaded into memory and never logged or exposed.)*

---

## Usage

### Interactive REPL (Recommended)

Launch the interactive chat interface by running VelixAgent without any task arguments:

```bash
uv run velix
```
This mode supports multiline input, persistent history, and slash commands (e.g., `/help`, `/clear`, `/config`, `/exit`).

### One-Shot Mode

Execute a specific task instantly and return to your shell:

```bash
uv run velix "Find all instances of MAX_FILE_SIZE and change them to 10MB"
```

### Other Commands

- **Check Version:** `uv run velix --version`
- **View Help:** `uv run velix --help`
- **View Configuration:** `uv run velix config`
- **Debug Mode:** `uv run velix --debug "analyze this codebase"`

---

## Available Tools

VelixAgent comes with a suite of registered system tools that the LLM can invoke dynamically:

- **`read_file`**: Reads and returns the contents of a specified file. Gracefully handles encoding and skips oversized files.
- **`write_file`**: Creates a new file with the specified content. Safely prevents accidental overwrites unless explicitly requested.
- **`edit_file`**: Modifies an existing file using exact text replacements, ensuring surgical precision without rewriting the entire file.
- **`list_directory`**: Explores the workspace by listing all files and folders in a given path.
- **`search_files`**: Recursively searches file contents for a string or Regex query across the workspace, bypassing ignored directories (like `.git` and `node_modules`).
- **`run_command`**: Executes terminal commands within the workspace (e.g., running test suites, formatters, or linters) and returns standard output and errors.

---

## Testing and Code Quality

VelixAgent maintains high code quality standards. You can verify the integrity of the project using the repository's established commands:

**Run the full unit test suite:**
```bash
uv run pytest
```

**Run tests with coverage:**
```bash
uv run pytest --cov
```

**Run the linter and format checker:**
```bash
uv run ruff check .
uv run ruff format --check .
```

**Run static type checking:**
```bash
uv run mypy src
```

---

## Project Structure

```
velix-agent/
├── pyproject.toml           # Project dependencies and configuration
├── README.md                # Documentation
├── LICENSE                  # MIT License
├── .env.example             # Configuration template
├── src/
│   └── velix_agent/
│       ├── cli/             # Typer CLI application, REPL, and Console UI
│       ├── core/            # Agent reasoning loop, runtime, config, and logging
│       ├── providers/       # LLM integrations (Gemini, OpenAI, Anthropic, etc.)
│       ├── tools/           # System tools (read, write, search, run_command)
│       └── utils/           # Path resolution and safety utilities
└── tests/
    ├── unit/                # Unit tests for core systems, tools, and providers
    └── integration/         # Integration tests for agent logic and REPL
```

---

## License

VelixAgent is released under the [MIT License](LICENSE).
