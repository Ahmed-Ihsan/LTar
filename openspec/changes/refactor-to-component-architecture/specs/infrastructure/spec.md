## ADDED Requirements

### Requirement: Infrastructure component folder

The infrastructure adapters SHALL reside in `src/components/infrastructure/` as a bounded-context component. The folder SHALL contain: `__init__.py` (re-exports), `models.py`, `llm.py`, `embeddings.py`, `memory.py`, and `run_logging.py`.

#### Scenario: Component folder structure
- **GIVEN** the refactored project structure
- **WHEN** the `src/components/infrastructure/` directory is inspected
- **THEN** it contains `__init__.py`, `models.py`, `llm.py`, `embeddings.py`, `memory.py`, and `run_logging.py`

### Requirement: Infrastructure models module

Infrastructure-specific data models SHALL reside in `src/components/infrastructure/models.py`. This includes `MemoryInfo` (total_bytes, available_bytes) and `RunLogEntry` if applicable. Protocol definitions (`LLMEngineAdapter`, `EmbeddingAdapter`) MAY reside in their respective implementation modules or in models.py.

#### Scenario: Import MemoryInfo from component models
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.models import MemoryInfo` is executed
- **THEN** MemoryInfo is imported successfully

### Requirement: Infrastructure LLM module

`LLMEngineAdapter` (Protocol), `OllamaEngineAdapter`, and `_translate_engine_error` SHALL reside in `src/components/infrastructure/llm.py`.

#### Scenario: Import LLM adapter from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.llm import LLMEngineAdapter, OllamaEngineAdapter` is executed
- **THEN** both the Protocol and concrete adapter are imported successfully

### Requirement: Infrastructure embeddings module

`EmbeddingAdapter` (Protocol), `Embedder`, `embed_batch`, `EMBED_DIM`, and `DEFAULT_BATCH_SIZE` SHALL reside in `src/components/infrastructure/embeddings.py`.

#### Scenario: Import embedding adapter from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.embeddings import Embedder, EmbeddingAdapter, EMBED_DIM` is executed
- **THEN** all symbols are imported successfully

### Requirement: Infrastructure memory module

`read_memory_info`, `available_ram_gb`, `check_ram_guard`, `RAM_GUARD_MIN_GB`, and `MemoryInfo` SHALL reside in `src/components/infrastructure/memory.py`.

#### Scenario: Import memory API from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.memory import read_memory_info, check_ram_guard, RAM_GUARD_MIN_GB` is executed
- **THEN** all symbols are imported successfully

### Requirement: Infrastructure run logging module

`RunLogger` SHALL reside in `src/components/infrastructure/run_logging.py`.

#### Scenario: Import RunLogger from component
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure.run_logging import RunLogger` is executed
- **THEN** RunLogger is imported successfully

### Requirement: Infrastructure public API re-export

`src/components/infrastructure/__init__.py` SHALL re-export the component's public API so that `from src.components.infrastructure import LLMEngineAdapter, Embedder, RunLogger` works without specifying the submodule.

#### Scenario: Re-exported public API
- **GIVEN** the refactored structure
- **WHEN** `from src.components.infrastructure import LLMEngineAdapter, Embedder, RunLogger, check_ram_guard` is executed
- **THEN** all symbols are imported successfully via the package __init__

### Requirement: Infrastructure intra-component imports

Modules within `infrastructure/` SHALL import from sibling modules within the same component using component paths (e.g., `from src.components.infrastructure.memory import check_ram_guard`), not from the old flat `src.memory` paths.

#### Scenario: llm.py imports from component memory
- **GIVEN** the refactored llm.py
- **WHEN** its imports are inspected
- **THEN** it imports check_ram_guard from `src.components.infrastructure.memory`, not from `src.memory`
