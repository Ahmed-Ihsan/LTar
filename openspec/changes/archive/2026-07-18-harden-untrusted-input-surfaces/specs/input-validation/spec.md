## Purpose

Cross-cutting input-validation primitives shared by every component. This
capability exists so that `interfaces`, `knowledge_sources`, and `config`
can validate untrusted input without depending on each other (preserving
the acyclic dependency graph documented in `AGENTS.md` §2). It lives in a
new `src/utils/` package that imports only stdlib + `pydantic` and is a
leaf in the dependency graph.

## ADDED Requirements

### Requirement: Path containment validator

`src/utils/paths.py` SHALL expose `validate_path_in_root(path: Path, root: Path) -> Path` that resolves both paths via `Path.resolve()` and returns `path` if and only if `path.is_relative_to(root)` is true. On violation it SHALL raise `PathContainmentError` (a `LegalTranslationError` subclass) with a message naming both paths.

#### Scenario: a path inside the root is accepted
- **GIVEN** `path = Path("/project/data/corpus/civil.txt")` and `root = Path("/project")`
- **WHEN** `validate_path_in_root(path, root)` is called
- **THEN** the resolved `path` is returned without raising

#### Scenario: a path traversal attempt is rejected
- **GIVEN** `path = Path("/project/../etc/passwd")` and `root = Path("/project")`
- **WHEN** `validate_path_in_root(path, root)` is called
- **THEN** `PathContainmentError` is raised whose message contains both the resolved path and the root

#### Scenario: an absolute path outside the root is rejected
- **GIVEN** `path = Path("/etc/passwd")` and `root = Path("/project")`
- **WHEN** `validate_path_in_root(path, root)` is called
- **THEN** `PathContainmentError` is raised

### Requirement: Zip-slip validator

`src/utils/zip_safe.py` SHALL expose `validate_zip_path(name: str) -> str` that rejects any zip entry name that is absolute, contains `..` path segments, or uses backslashes to escape the archive root. On violation it SHALL raise `InputValidationError`.

#### Scenario: a normal relative path is accepted
- **GIVEN** a zip entry name `xl/sharedStrings.xml`
- **WHEN** `validate_zip_path(name)` is called
- **THEN** the name is returned unchanged

#### Scenario: a path traversal entry is rejected
- **GIVEN** a zip entry name `../../evil.txt`
- **WHEN** `validate_zip_path(name)` is called
- **THEN** `InputValidationError` is raised

#### Scenario: an absolute path entry is rejected
- **GIVEN** a zip entry name `/etc/passwd`
- **WHEN** `validate_zip_path(name)` is called
- **THEN** `InputValidationError` is raised

#### Scenario: a backslash escape entry is rejected
- **GIVEN** a zip entry name `..\\evil.txt`
- **WHEN** `validate_zip_path(name)` is called
- **THEN** `InputValidationError` is raised

### Requirement: XML text escape helper

`src/utils/xml_escape.py` SHALL expose `escape_xml_text(text: str) -> str` that escapes `&`, `<`, and `>` (and `"` and `'` for attribute contexts) via `xml.sax.saxutils.escape` / `quoteattr`. It is a pure function with no I/O.

#### Scenario: ampersand and angle brackets are escaped
- **GIVEN** `text = "a < b & c > d"`
- **WHEN** `escape_xml_text(text)` is called
- **THEN** the result is `&amp;a &lt; b &amp; c &gt; d&amp;` (per `xml.sax.saxutils.escape` semantics)

#### Scenario: a translation containing closing tags is neutralized
- **GIVEN** `text = "evil</t><script>alert(1)</script>"`
- **WHEN** `escape_xml_text(text)` is called
- **THEN** the result contains `&lt;/t&gt;` and `&lt;script&gt;` and no raw `<` or `>` characters

### Requirement: JSONL schema models

`src/utils/jsonl_schema.py` SHALL expose two Pydantic models:
- `BatchRecord` with `input: str` (max 10 000 chars) and `direction: Literal["ar-en", "en-ar"]`.
- `ParallelPair` with `source_sentence: str` (max 10 000 chars), `target_sentence: str` (max 10 000 chars), `source_lang: str = "ar"`, `target_lang: str = "en"`.

Both SHALL raise `pydantic.ValidationError` on oversized fields, missing fields, or wrong types.

#### Scenario: a valid batch record parses
- **GIVEN** a JSONL line `{"input": "المادة ١", "direction": "ar-en"}`
- **WHEN** `BatchRecord.model_validate_json(line)` is called
- **THEN** a `BatchRecord` with `input="المادة ١"` and `direction="ar-en"` is returned

#### Scenario: an oversized input is rejected
- **GIVEN** a JSONL line whose `input` field is 10 001 characters
- **WHEN** `BatchRecord.model_validate_json(line)` is called
- **THEN** `pydantic.ValidationError` is raised

#### Scenario: an invalid direction is rejected
- **GIVEN** a JSONL line `{"input": "x", "direction": "fr-en"}`
- **WHEN** `BatchRecord.model_validate_json(line)` is called
- **THEN** `pydantic.ValidationError` is raised

#### Scenario: a valid parallel pair parses with default langs
- **GIVEN** a JSONL line `{"source_sentence": "a", "target_sentence": "b"}`
- **WHEN** `ParallelPair.model_validate_json(line)` is called
- **THEN** a `ParallelPair` with `source_lang="ar"` and `target_lang="en"` is returned

### Requirement: Token-bucket rate limiter

`src/utils/rate_limit.py` SHALL expose `TokenBucket(rate: float, capacity: int)` that is thread-safe (via `threading.Lock`) and exposes `try_acquire() -> bool` which returns `True` if a token was available (and consumes it) or `False` if the bucket is empty.

#### Scenario: a token is available initially
- **GIVEN** a `TokenBucket(rate=1.0, capacity=10)`
- **WHEN** `try_acquire()` is called for the first time
- **THEN** `True` is returned and one token is consumed

#### Scenario: the bucket empties after capacity acquisitions
- **GIVEN** a `TokenBucket(rate=1.0, capacity=10)` and 10 prior `try_acquire()` calls that returned `True`
- **WHEN** `try_acquire()` is called immediately
- **THEN** `False` is returned

#### Scenario: tokens refill over time
- **GIVEN** an empty `TokenBucket(rate=1.0, capacity=10)` and a 1.5-second wait
- **WHEN** `try_acquire()` is called
- **THEN** `True` is returned (at least one token has refilled)
