#!/usr/bin/env bash

# Convenience script to run VelixAgent without manually activating the virtual environment.

# Robustly find the directory where this script is located
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT" || exit 1

if [ ! -d ".venv" ]; then
    echo "Error: Virtual environment '.venv' not found in $PROJECT_ROOT."
    echo "Please set up the project dependencies first (e.g., using 'uv sync' or 'python -m venv .venv')."
    exit 1
fi

# Use the virtual environment's Python to run the velix executable
exec .venv/bin/velix "$@"
