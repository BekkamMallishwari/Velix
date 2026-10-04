# VelixAgent

**A powerful, extensible AI coding assistant and command-line agent.**

VelixAgent is an AI-powered development assistant designed to run directly from your terminal. By deeply integrating large language models (LLMs) with secure, constrained system access, VelixAgent operates as an intelligent pair programmer right in your local environment.

---

## What It Does

VelixAgent solves the friction of context-switching between your code editor and a web-based AI chat. It dynamically interacts with your repository, interpreting development requests and autonomously invoking system tools to gather context or execute changes.

Instead of manually copy-pasting code snippets, you simply ask VelixAgent to investigate or modify the codebase. It formulates a plan, leverages its tools to read, search, or edit files, and iteratively works through the task until it reaches a resolution.

---

## Key Capabilities

- **Autonomous Tool Execution:** Natively uses system tools to read, write, and safely edit files, explore directories, search file contents, and execute shell commands inside your workspace.
- **Iterative Reasoning Loop:** Dynamically adjusts its plan based on command output or file contents, looping through multiple tool calls in a single turn to fully resolve complex tasks.
- **Interactive REPL & One-Shot Mode:** Work conversationally with persistent history using the interactive REPL, or pass a specific task directly via the CLI for instant one-shot execution.
- **Multi-Provider Fallback:** Connects to major LLM providers (including Google Gemini, OpenAI, Anthropic, OpenRouter, and local models like Ollama) with an automatic fallback chain if the primary model encounters errors.
- **Robust Security Constraints:** File operations are strictly sandboxed to prevent arbitrary path traversal, and large outputs are intelligently truncated to optimize the LLM's context window.
