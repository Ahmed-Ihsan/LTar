# Contributing to the Iraqi Legal Translation Agent

Thank you for your interest in contributing! This document outlines the process for submitting changes.

## Getting Started

1. **Fork** the repository and clone your fork.
2. Create a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   pip install -e ".[dev]"
   ```
3. Install Ollama and pull the required models (see [README.md](README.md) §5.2).

## Development Workflow

1. Create a branch from `main`:
   ```powershell
   git checkout -b feature/your-feature-name
   ```
2. Make your changes. Keep commits focused and write clear commit messages.
3. Run the test suite:
   ```powershell
   python -m pytest tests/ -q
   ```
4. Lint changed files:
   ```powershell
   python -m ruff check <changed files>
   ```
5. Push to your fork and open a Pull Request.

## Code Style

- **Ruff** is the lint gate (line-length 100, target py311).
- Follow existing patterns — see [ARCHITECTURE.md](ARCHITECTURE.md) for design conventions.
- Adapter boundary: engine exceptions are caught in adapters and re-raised as domain exceptions (see [AGENTS.md](AGENTS.md)).
- Node functions in `src/nodes.py` are closed for modification (OCP). New cross-cutting concerns go in `src/graph.py` or `src/cli.py`.

## Testing

- All tests must pass without a running Ollama daemon (mocks are used in CI).
- `@pytest.mark.slow` tests require a real Ollama daemon and are excluded from the default run.
- Add tests for any new functionality.

## Pull Request Process

1. Ensure all tests pass and lint is clean.
2. Update documentation (README, ARCHITECTURE, etc.) if your change affects the public API or architecture.
3. Follow the PR template when submitting.
4. Request review from a maintainer.

## Reporting Issues

Use the GitHub issue templates for bug reports and feature requests. Include as much detail as possible (environment, steps to reproduce, expected vs actual behavior).
