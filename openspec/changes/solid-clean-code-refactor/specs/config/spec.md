## MODIFIED Requirements

### Requirement: AppConfig single responsibility

`AppConfig` SHALL be a Pydantic model that holds all runtime parameters loaded from `config.yaml`. It MUST embed `PathsConfig` and `ChromaConfig` sub-models plus model names, host URLs, chunk parameters, TM threshold, and revision limits. The `config.py` module SHALL NOT contain CLI command definitions — CLI logic SHALL live in a separate `cli.py` module within the config package. `load_config()` SHALL remain the single entry point for configuration loading and MUST NOT be called from within adapter constructors.

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
- **GIVEN** an OllamaEngineAdapter or Embedder is constructed
- **WHEN** the constructor is called
- **THEN** it receives model, host, and timeout as keyword-only args and does NOT call `load_config()` internally

### Requirement: PathsConfig sub-model with validation

`PathsConfig` SHALL be a Pydantic model holding filesystem paths: data_dir, corpus_dir, glossary_dir, raw_dir, db_dir, glossary_db, chroma_dir. Each path field SHALL have a Pydantic validator that ensures the path string is non-empty and normalized to the platform's path separator.

#### Scenario: PathsConfig fields are populated
- **GIVEN** a config.yaml with a `paths` section
- **WHEN** load_config parses it
- **THEN** the AppConfig.paths field is a PathsConfig with data_dir, corpus_dir, glossary_dir, raw_dir, db_dir, glossary_db, and chroma_dir set

#### Scenario: Empty path is rejected
- **GIVEN** a config.yaml with a `paths` section where `data_dir` is an empty string
- **WHEN** load_config parses it
- **THEN** a ConfigError is raised with a message indicating the field is empty

### Requirement: ChromaConfig sub-model with validation

`ChromaConfig` SHALL be a Pydantic model holding ChromaDB HNSW tuning parameters: space, hnsw_M, construction_ef, search_ef. Each numeric field SHALL have a Pydantic validator that ensures the value is within an acceptable range (hnsw_M ≥ 2, construction_ef ≥ 1, search_ef ≥ 1).

#### Scenario: ChromaConfig fields are populated
- **GIVEN** a config.yaml with a `chroma` section
- **WHEN** load_config parses it
- **THEN** the AppConfig.chroma field is a ChromaConfig with space, hnsw_M, construction_ef, and search_ef set

#### Scenario: Invalid hnsw_M is rejected
- **GIVEN** a config.yaml with `chroma.hnsw_M` set to 0
- **WHEN** load_config parses it
- **THEN** a ConfigError is raised with a message indicating hnsw_M must be ≥ 2

### Requirement: ConfigError on invalid config

`ConfigError` SHALL be raised when config.yaml is missing, unreadable, or contains invalid values. `load_config` MUST validate the YAML structure and raise ConfigError with a descriptive message on failure.

#### Scenario: Missing config file
- **GIVEN** no config.yaml at the expected path
- **WHEN** load_config is called
- **THEN** a ConfigError is raised with a message indicating the file was not found

#### Scenario: Invalid YAML structure
- **GIVEN** a config.yaml with missing required fields
- **WHEN** load_config is called
- **THEN** a ConfigError is raised with a message indicating which field is invalid

### Requirement: Config Typer app separation

The config package SHALL expose a Typer `app` with a `load` command that loads and prints the parsed configuration. `DEFAULT_CONFIG_PATH` MUST define the default config file location. The Typer `app` and `load` command SHALL reside in a dedicated `cli.py` module within the config package, separate from `config.py` which contains loading logic only.

#### Scenario: Config load command prints parsed config
- **GIVEN** a valid config.yaml
- **WHEN** the Typer `load` command is executed
- **THEN** the parsed AppConfig is printed to stdout

#### Scenario: CLI module is separate from loading module
- **GIVEN** the config package is inspected
- **WHEN** `config.py` is read
- **THEN** it does not contain Typer app definitions or command decorators; those are in `cli.py`
