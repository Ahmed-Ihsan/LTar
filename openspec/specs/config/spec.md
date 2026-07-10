## Purpose

Configuration loading and validation from `config.yaml` via Pydantic models. The config package provides the single source of runtime parameters for all components: model names, host URLs, filesystem paths, ChromaDB tuning, chunk parameters, TM threshold, and revision limits.

## Requirements

### Requirement: AppConfig top-level model

`AppConfig` SHALL be a Pydantic model that holds all runtime parameters loaded from `config.yaml`. It MUST embed `PathsConfig` and `ChromaConfig` sub-models plus model names, host URLs, chunk parameters, TM threshold, and revision limits.

#### Scenario: Load config from default path
- **GIVEN** a valid config.yaml at the default config path
- **WHEN** load_config is called with no path argument
- **THEN** an AppConfig is returned with all fields populated from the YAML file

#### Scenario: Load config from explicit path
- **GIVEN** a valid config.yaml at a custom path
- **WHEN** load_config is called with that path
- **THEN** an AppConfig is returned with fields from the specified file

### Requirement: PathsConfig sub-model

`PathsConfig` SHALL be a Pydantic model holding filesystem paths: data_dir, corpus_dir, glossary_dir, raw_dir, db_dir, glossary_db, chroma_dir.

#### Scenario: PathsConfig fields are populated
- **GIVEN** a config.yaml with a `paths` section
- **WHEN** load_config parses it
- **THEN** the AppConfig.paths field is a PathsConfig with data_dir, corpus_dir, glossary_dir, raw_dir, db_dir, glossary_db, and chroma_dir set

### Requirement: ChromaConfig sub-model

`ChromaConfig` SHALL be a Pydantic model holding ChromaDB HNSW tuning parameters: space, hnsw_M, construction_ef, search_ef.

#### Scenario: ChromaConfig fields are populated
- **GIVEN** a config.yaml with a `chroma` section
- **WHEN** load_config parses it
- **THEN** the AppConfig.chroma field is a ChromaConfig with space, hnsw_M, construction_ef, and search_ef set

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

### Requirement: Config Typer app

`config.py` SHALL expose a Typer `app` with a `load` command that loads and prints the parsed configuration. `DEFAULT_CONFIG_PATH` MUST define the default config file location.

#### Scenario: Config load command prints parsed config
- **GIVEN** a valid config.yaml
- **WHEN** the Typer `load` command is executed
- **THEN** the parsed AppConfig is printed to stdout
