## MODIFIED Requirements

### Requirement: AppConfig top-level model

`AppConfig` SHALL be a Pydantic model that holds all runtime parameters loaded from `config.yaml`. It MUST embed `PathsConfig` and `ChromaConfig` sub-models plus model names, host URLs, chunk parameters, TM threshold, and revision limits. The `config.py` module SHALL NOT contain CLI command definitions — CLI logic SHALL live in a separate `cli.py` module within the config package. `load_config()` SHALL remain the single entry point for configuration loading and MUST NOT be called from within adapter constructors. The `llm_backend` field SHALL be typed as `Literal["ollama", "llamacpp", "gemini"]` with default `"ollama"` (offline-first). `AppConfig` SHALL additionally expose Gemini backend fields: `gemini_model: str = "gemini-2.0-flash"`, `gemini_embed_model: str = "text-embedding-004"`, `gemini_timeout: float = 120.0`, `gemini_rpm: int = 15`, and `gemini_api_key: str | None = None` (populated from the `GEMINI_API_KEY` environment variable by `load_config`, never from `config.yaml`). `gemini_timeout` SHALL be validated as a non-negative float. `gemini_rpm` SHALL be validated as a positive integer. An unknown `llm_backend` value SHALL fail Pydantic validation (raising `ConfigError` via `load_config`) with a message listing the three valid values.

#### Scenario: Load config from default path
- **GIVEN** a valid config.yaml at the default config path
- **WHEN** load_config is called with no path argument
- **THEN** an AppConfig is returned with all fields populated from the YAML file

#### Scenario: Load config from explicit path
- **GIVEN** a valid config.yaml at a custom path
- **WHEN** load_config is called with that path
- **THEN** an AppConfig is returned with fields from the specified file

#### Scenario: Config module does not contain CLI commands
- **GIVEN** the config package is inspected
- **WHEN** the modules are listed
- **THEN** `config.py` contains `load_config`, `AppConfig`, `ConfigError`, and `DEFAULT_CONFIG_PATH` only; CLI commands are in a separate module

#### Scenario: Adapters do not call load_config internally
- **GIVEN** an OllamaEngineAdapter, Embedder, or GeminiEngineAdapter is constructed
- **WHEN** the constructor is called
- **THEN** it receives model, host/timeout, and (for Gemini) api_key as keyword-only args and does NOT call `load_config()` internally

#### Scenario: llm_backend defaults to ollama
- **GIVEN** a config.yaml with no `llm_backend` key
- **WHEN** load_config parses it
- **THEN** `cfg.llm_backend == "ollama"` (offline-first default preserved)

#### Scenario: llm_backend accepts the three valid values
- **GIVEN** a config.yaml with `llm_backend: gemini`
- **WHEN** load_config parses it
- **THEN** `cfg.llm_backend == "gemini"` and the Gemini fields use their defaults when unset

#### Scenario: an unknown llm_backend is rejected
- **GIVEN** a config.yaml with `llm_backend: openai`
- **WHEN** load_config parses it
- **THEN** a `ConfigError` is raised with a message listing `ollama`, `llamacpp`, and `gemini` as the valid values

#### Scenario: Gemini fields default when the section is absent
- **GIVEN** a config.yaml with `llm_backend: gemini` and no `gemini_*` keys
- **WHEN** load_config parses it
- **THEN** `cfg.gemini_model == "gemini-2.0-flash"`, `cfg.gemini_embed_model == "text-embedding-004"`, `cfg.gemini_timeout == 120.0`, and `cfg.gemini_rpm == 15`

## ADDED Requirements

### Requirement: Gemini API key loaded from environment variable

`load_config` SHALL populate `AppConfig.gemini_api_key` by reading the `GEMINI_API_KEY` environment variable via `os.environ.get("GEMINI_API_KEY")`. The key SHALL NOT be read from `config.yaml` — if a `gemini_api_key` key appears in `config.yaml`, `load_config` SHALL raise `ConfigError` with a message stating that the Gemini API key must be provided via the `GEMINI_API_KEY` environment variable for security. When `llm_backend == "gemini"` and `GEMINI_API_KEY` is unset or empty, `load_config` SHALL raise `ConfigError` with a message instructing the user to export `GEMINI_API_KEY`. When `llm_backend != "gemini"`, an unset `GEMINI_API_KEY` SHALL NOT raise (the key is irrelevant on the Ollama path). The loaded `gemini_api_key` SHALL NEVER be written to logs, to the run log, or to any `__repr__` output (security — AGENTS.md §12).

#### Scenario: gemini backend with a valid env var succeeds
- **GIVEN** `llm_backend: gemini` in config.yaml and `GEMINI_API_KEY=AIza...` exported in the environment
- **WHEN** load_config parses it
- **THEN** `cfg.gemini_api_key == "AIza..."` and no error is raised

#### Scenario: gemini backend without the env var fails
- **GIVEN** `llm_backend: gemini` in config.yaml and `GEMINI_API_KEY` unset
- **WHEN** load_config parses it
- **THEN** a `ConfigError` is raised instructing the user to export `GEMINI_API_KEY`

#### Scenario: ollama backend with no env var succeeds
- **GIVEN** `llm_backend: ollama` in config.yaml and `GEMINI_API_KEY` unset
- **WHEN** load_config parses it
- **THEN** no error is raised and `cfg.gemini_api_key` is `None`

#### Scenario: a key placed in config.yaml is rejected
- **GIVEN** a config.yaml containing a `gemini_api_key: AIza...` entry
- **WHEN** load_config parses it
- **THEN** a `ConfigError` is raised stating the key must come from the `GEMINI_API_KEY` environment variable

#### Scenario: the API key is not logged
- **GIVEN** a loaded `AppConfig` with `gemini_api_key="AIza..."`
- **WHEN** the config is printed or logged (e.g. by the `config load` Typer command)
- **THEN** the `gemini_api_key` value is masked or omitted (never printed in cleartext)
