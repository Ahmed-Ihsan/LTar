# Gemma 3 4B + Legal TM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Qwen 2.5 7B with Gemma 3 4B as the LLM for both Translator and Auditor nodes, and add a Legal Translation Memory (TM) layer that intercepts repetitive legal sentences before they reach the LLM.

**Architecture:** Two independent changes on the existing LangGraph pipeline. (1) Config-only model swap: `llm_model: qwen2.5:7b-instruct-q5_K_M` → `llm_model: gemma3:4b` — no code changes, the `OllamaEngineAdapter` works with any Ollama model tag. (2) A new `tm_lookup` pre-processing node inserted between `preprocess` and `translate` that checks a sentence-level TM built from the existing bilingual corpus; sentences with ≥98% similarity to a stored pair bypass the LLM entirely. The TM is a new SQLite store (`db/tm.sqlite`) built by aligning ar/en article pairs from `data/corpus/`. All new components respect the adapter boundary, OCP (nodes are closed for modification), and DI at the CLI seam.

**Tech Stack:** Python 3.10+ (`.venv310`), LangGraph 0.2.x, SQLite (TM store), Pydantic (config), pytest + ruff. No new dependencies — `sqlite3` and `difflib` are stdlib.

## Global Constraints

- **Python:** use `.\.venv310\Scripts\python.exe` for all commands (per `AGENTS.md`).
- **Shell:** PowerShell — use `;` not `&&` to chain commands.
- **Tests:** `.\.venv310\Scripts\python.exe -m pytest tests/ -q` — expected ~192 passed, 3 deselected. New tests must not require an Ollama daemon or network.
- **Lint:** `.\.venv310\Scripts\python.exe -m ruff check <changed files>` — only lint changed files.
- **Adapter boundary:** no engine exception type escapes an adapter. New code only sees domain exceptions from `src/exceptions.py`.
- **OCP:** node functions in `src/nodes.py` are closed for modification. New logic goes in new modules or new nodes.
- **DI:** the CLI (`src/cli.py`) is the only place concrete adapters are constructed. `run_translation` / `run_translation_streamed` are the orchestration seams.
- **TM safety:** acceptance threshold ≥ 0.98 similarity. TM outputs bypass the Auditor (pre-approved). The threshold is non-negotiable.
- **Config validation:** all new config keys must have Pydantic validators in `AppConfig` (`src/config.py`).
- **LangGraph gotcha:** node callables wrapped for logging must use annotation-free inner functions (see `_wrap_with_logging` in `src/graph.py`).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config.yaml` | Modify | Change `llm_model` to `gemma3:4b`; add TM config keys |
| `src/config.py` | Modify | Add `tm_enabled`, `tm_similarity_threshold`, `tm_db` fields to `AppConfig` with validators |
| `src/tm.py` | Create | `TranslationMemory` class: build/load SQLite TM, sentence alignment from corpus, similarity search, threshold-gated lookup |
| `src/decision.py` | Create | `route_tm`: pure function that decides TM-hit vs LLM per sentence based on similarity score and threshold |
| `src/state.py` | Modify | Add `tm_hits` field to `TranslationState` (list of TM matches that bypass the LLM) |
| `src/nodes.py` | Create function | `tm_lookup_node`: new node that queries the TM and populates `tm_hits` |
| `src/graph.py` | Modify | Insert `tm_lookup` node between `preprocess` and `translate`; wire the TM adapter via DI |
| `src/cli.py` | Modify | Construct `TranslationMemory` and pass it to `build_graph` via DI |
| `tests/test_config.py` | Create | Tests for new TM config keys + validation |
| `tests/test_tm.py` | Create | Tests for `TranslationMemory` (build, lookup, threshold gating, miss → fallback) |
| `tests/test_decision.py` | Create | Tests for `route_tm` (deterministic routing, edge cases at threshold) |
| `tests/test_tm_node.py` | Create | Tests for `tm_lookup_node` using in-memory TM |
| `tests/test_graph.py` | Modify | Add test that `tm_lookup` node is in the graph topology when `tm_enabled=True` |

---

## Task 1: Config — Add TM keys and switch model

**Files:**
- Modify: `config.yaml`
- Modify: `src/config.py:44-87` (the `AppConfig` class)
- Test: `tests/test_config.py` (create)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `AppConfig.tm_enabled: bool`, `AppConfig.tm_similarity_threshold: float`, `AppConfig.tm_db: str`, `AppConfig.llm_model` now defaults to `gemma3:4b`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Tests for TM config keys and the Gemma 3 4B model default (task 1)."""
from __future__ import annotations

import pytest

from src.config import AppConfig

pytestmark = pytest.mark.unit


def test_llm_model_default_is_gemma3_4b():
    """The default model is now gemma3:4b, not qwen2.5:7b."""
    cfg = AppConfig()
    assert cfg.llm_model == "gemma3:4b"


def test_tm_config_defaults():
    """TM config keys have sensible defaults."""
    cfg = AppConfig()
    assert cfg.tm_enabled is True
    assert cfg.tm_similarity_threshold == 0.98
    assert cfg.tm_db == "db/tm.sqlite"


def test_tm_threshold_validation_rejects_out_of_range():
    """tm_similarity_threshold must be in [0.0, 1.0]."""
    with pytest.raises(Exception):
        AppConfig(tm_similarity_threshold=-0.1)
    with pytest.raises(Exception):
        AppConfig(tm_similarity_threshold=1.5)


def test_tm_threshold_accepts_boundaries():
    """0.0 and 1.0 are valid threshold values."""
    AppConfig(tm_similarity_threshold=0.0)
    AppConfig(tm_similarity_threshold=1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `AppConfig` has no `tm_enabled` / `tm_similarity_threshold` / `tm_db` attributes, and `llm_model` default is still `qwen2.5:7b-instruct-q5_K_M`.

- [ ] **Step 3: Update `src/config.py`**

In the `AppConfig` class, change the `llm_model` default and add the three TM fields. Add a validator for the threshold.

Change line 51 from:
```python
    llm_model: str = "qwen2.5:7b-instruct-q5_K_M"
```
to:
```python
    llm_model: str = "gemma3:4b"
```

After line 70 (`chroma: ChromaConfig = Field(default_factory=ChromaConfig)`), add:
```python
    # --- Translation Memory (TM) ---
    tm_enabled: bool = True
    tm_similarity_threshold: float = 0.98
    tm_db: str = "db/tm.sqlite"
```

Add `"tm_similarity_threshold"` to the `_non_negative_float` validator's field list, and add a new validator for the upper bound:

```python
    @field_validator("tm_similarity_threshold")
    @classmethod
    def _threshold_upper_bound(cls, v: float) -> float:
        if v > 1.0:
            raise ValueError(f"tm_similarity_threshold must be <= 1.0, got {v}")
        return v
```

- [ ] **Step 4: Update `config.yaml`**

Change `llm_model` and add TM keys at the end:

```yaml
llm_model: gemma3:4b
```

At the end of the file, add:
```yaml
# --- Translation Memory (TM) ---
tm_enabled: true
tm_similarity_threshold: 0.98
tm_db: db/tm.sqlite
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run full suite to check no regressions**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
Expected: ~196 passed, 3 deselected (192 original + 4 new)

- [ ] **Step 7: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/config.py tests/test_config.py`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add config.yaml src/config.py tests/test_config.py
git commit -m "feat: switch llm_model to gemma3:4b and add TM config keys"
```

---

## Task 2: State — Add `tm_hits` field to `TranslationState`

**Files:**
- Modify: `src/state.py:71-95` (the `TranslationState` TypedDict)
- Test: `tests/conftest.py` (modify `_empty_state` fixture)

**Interfaces:**
- Consumes: nothing
- Produces: `TranslationState.tm_hits: list[TmHit]` where `TmHit` is a new TypedDict

- [ ] **Step 1: Add the `TmHit` TypedDict and `tm_hits` field to `src/state.py`**

After the `AuditVerdict` class (line 68) and before `TranslationState`, add:

```python
class TmHit(TypedDict):
    """A Translation Memory match found in the source text.

    Produced by the ``tm_lookup`` node. When a sentence has ≥ 98% similarity
    to a stored bilingual pair, the stored target translation is used directly
    (bypassing the LLM). ``char_start`` / ``char_end`` delimit the matched
    span in the original input; ``source_sentence`` / ``target_sentence`` are
    the stored pair; ``similarity`` is the ratio in [0.0, 1.0].
    """

    source_sentence: str
    target_sentence: str
    similarity: float
    char_start: int
    char_end: int
```

In `TranslationState`, after `context_chunks: list[ContextChunk]` (line 90), add:

```python
    tm_hits: list[TmHit]
```

Update the docstring field-ownership comment to include:
```
    - ``tm_lookup`` reads ``input_text`` / ``direction``; writes ``tm_hits``.
```

- [ ] **Step 2: Update `_empty_state` in `tests/conftest.py`**

Add `"tm_hits": []` to the dict returned by `_empty_state` (after `"context_chunks": []`):

```python
def _empty_state(
    input_text: str = "", direction: str = "ar-en"
) -> TranslationState:
    return {
        "input_text": input_text,
        "direction": direction,  # type: ignore[arg-type]
        "glossary_hits": [],
        "context_chunks": [],
        "tm_hits": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }
```

- [ ] **Step 3: Run full suite to check no regressions**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
Expected: ~196 passed, 3 deselected (all existing tests that build a state must still pass — the `_empty_state` fixture covers most; any test that builds a state inline may need `"tm_hits": []` added)

If any test fails with a missing `tm_hits` key, add `"tm_hits": []` to that test's inline state dict.

- [ ] **Step 4: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/state.py tests/conftest.py`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add src/state.py tests/conftest.py
git commit -m "feat: add tm_hits field to TranslationState"
```

---

## Task 3: TM core — `TranslationMemory` class

**Files:**
- Create: `src/tm.py`
- Test: `tests/test_tm.py` (create)

**Interfaces:**
- Consumes: `AppConfig.tm_db` (path), `AppConfig.tm_similarity_threshold`
- Produces: `TranslationMemory` class with methods:
  - `build_from_corpus(corpus_dir: Path) -> None` — aligns ar/en article pairs and populates SQLite
  - `lookup(sentence: str, direction: str) -> TmHit | None` — returns a match if similarity ≥ threshold, else `None`
  - `close() -> None` — closes the SQLite connection

- [ ] **Step 1: Write the failing test**

Create `tests/test_tm.py`:

```python
"""Tests for the TranslationMemory class (task 3).

Tests use a temp SQLite DB and a small fake corpus — no real files, no
network, no Ollama daemon (testing-verification §3.4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tm import TranslationMemory

pytestmark = pytest.mark.unit


def _write_corpus(corpus_dir: Path) -> None:
    """Write a minimal bilingual corpus for TM build tests."""
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون المدني العراقي\nLANG: ar\n---\n\n"
        "ARTICLE 1\nعقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.\n\n"
        "ARTICLE 2\nالأهلية هي صلاحية الشخص لاكتساب الحقوق.\n",
        encoding="utf-8",
    )
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Iraqi Civil Code\nLANG: en\n---\n\n"
        "ARTICLE 1\nA contract of sale is an agreement to transfer ownership "
        "of a thing in exchange for a price.\n\n"
        "ARTICLE 2\nLegal capacity is the fitness of a person to acquire rights.\n",
        encoding="utf-8",
    )


def test_build_from_corpus_aligns_articles(tmp_path: Path):
    """Building from a bilingual corpus stores aligned sentence pairs."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)
    hits = tm.list_all()
    assert len(hits) == 2
    # Each hit has source + target + law_slug + article
    assert all("source_sentence" in h and "target_sentence" in h for h in hits)
    tm.close()


def test_lookup_exact_match_returns_hit(tmp_path: Path):
    """An exact source sentence match returns a TmHit with similarity 1.0."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    hit = tm.lookup("عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.", "ar-en")
    assert hit is not None
    assert hit["source_sentence"] == "عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن."
    assert "contract of sale" in hit["target_sentence"].lower()
    assert hit["similarity"] == pytest.approx(1.0)
    tm.close()


def test_lookup_below_threshold_returns_none(tmp_path: Path):
    """A sentence with low similarity to all stored pairs returns None."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    hit = tm.lookup("هذا نص قانوني مختلف تماماً عن أي شيء مخزن.", "ar-en")
    assert hit is None
    tm.close()


def test_lookup_empty_tm_returns_none(tmp_path: Path):
    """Lookup on an empty TM returns None."""
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    hit = tm.lookup("أي نص", "ar-en")
    assert hit is None
    tm.close()


def test_lookup_en_ar_direction(tmp_path: Path):
    """Lookup in en-ar direction matches English source to Arabic target."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    hit = tm.lookup(
        "A contract of sale is an agreement to transfer ownership "
        "of a thing in exchange for a price.",
        "en-ar",
    )
    assert hit is not None
    assert "عقد البيع" in hit["target_sentence"]
    tm.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_tm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tm'`

- [ ] **Step 3: Implement `src/tm.py`**

```python
"""Legal Translation Memory (TM) — sentence-level bilingual lookup.

Single responsibility: build a SQLite TM from aligned ar/en corpus article
pairs, and look up source sentences with a similarity threshold. Sentences
at or above the threshold return a stored target translation directly,
bypassing the LLM (spec §5). Below the threshold, lookup returns None and
the sentence goes to the LLM.

The TM is built once from ``data/corpus`` by aligning articles by their
``ARTICLE N`` marker across ar/en file pairs with the same law slug. The
similarity metric is ``difflib.SequenceMatcher.ratio`` (stdlib, no
dependencies). The threshold (default 0.98) is non-negotiable per the spec
safety rules: a near-match with a critical legal difference is worse than
a slow LLM call.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from src.state import TmHit

# ARTICLE marker — same pattern as src/ingestion.py (DATA_SPEC §1.2).
_ARTICLE_MARKER_RE: re.Pattern[str] = re.compile(r"^ARTICLE\s+(.+?)\s*$")

# Header separator in corpus files.
_HEADER_SEPARATOR: str = "---"


@dataclass(slots=True, frozen=True)
class TmEntry:
    """A stored bilingual sentence pair with provenance."""

    source_sentence: str
    target_sentence: str
    source_lang: str
    target_lang: str
    law_slug: str
    article: str


def _parse_articles(file_path: Path) -> dict[str, str]:
    """Parse a corpus file into ``{article_number: article_body}`` pairs.

    Skips the header (everything before the first ``---`` line). Each
    ``ARTICLE N`` line starts a new article; the body is the text until the
    next ``ARTICLE`` line or EOF.
    """
    text: str = file_path.read_text(encoding="utf-8")
    lines: list[str] = text.splitlines()
    articles: dict[str, str] = {}
    current_article: str | None = None
    body_lines: list[str] = []
    past_header: bool = False

    for line in lines:
        if not past_header:
            if line.strip() == _HEADER_SEPARATOR:
                past_header = True
            continue
        marker_match: re.Match[str] | None = _ARTICLE_MARKER_RE.match(
            line.strip()
        )
        if marker_match is not None:
            if current_article is not None:
                articles[current_article] = "\n".join(body_lines).strip()
            current_article = marker_match.group(1).strip()
            body_lines = []
        elif current_article is not None:
            body_lines.append(line)

    if current_article is not None:
        articles[current_article] = "\n".join(body_lines).strip()

    return articles


def _law_slug_from_filename(filename: str) -> str:
    """Extract the law slug from a corpus filename.

    ``civil_code_ar.txt`` -> ``civil_code``. Strips the ``_ar`` / ``_en``
    suffix and the ``.txt`` extension.
    """
    stem: str = Path(filename).stem
    for suffix in ("_ar", "_en"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def _lang_from_filename(filename: str) -> str:
    """Extract the language code from a corpus filename (``_ar`` / ``_en``)."""
    stem: str = Path(filename).stem
    if stem.endswith("_ar"):
        return "ar"
    if stem.endswith("_en"):
        return "en"
    return ""


def _align_corpus(corpus_dir: Path) -> list[TmEntry]:
    """Align ar/en article pairs from the corpus directory.

    Pairs files by law slug (e.g. ``civil_code_ar.txt`` + ``civil_code_en.txt``).
    Within each pair, aligns articles by article number. Each aligned article
    body becomes one TM entry (source = ar body, target = en body, or vice
    versa — both directions are stored for bidirectional lookup).
    """
    files: list[Path] = sorted(corpus_dir.glob("*.txt"))
    by_slug: dict[str, dict[str, dict[str, str]]] = {}

    for f in files:
        lang: str = _lang_from_filename(f.name)
        if lang not in ("ar", "en"):
            continue
        slug: str = _law_slug_from_filename(f.name)
        if slug not in by_slug:
            by_slug[slug] = {}
        by_slug[slug][lang] = _parse_articles(f)

    entries: list[TmEntry] = []
    for slug, langs in by_slug.items():
        ar_articles: dict[str, str] = langs.get("ar", {})
        en_articles: dict[str, str] = langs.get("en", {})
        for article_num, ar_body in ar_articles.items():
            en_body: str | None = en_articles.get(article_num)
            if en_body is None or not ar_body or not en_body:
                continue
            entries.append(TmEntry(
                source_sentence=ar_body,
                target_sentence=en_body,
                source_lang="ar",
                target_lang="en",
                law_slug=slug,
                article=article_num,
            ))
            entries.append(TmEntry(
                source_sentence=en_body,
                target_sentence=ar_body,
                source_lang="en",
                target_lang="ar",
                law_slug=slug,
                article=article_num,
            ))
    return entries


class TranslationMemory:
    """SQLite-backed legal Translation Memory with threshold-gated lookup.

    The TM stores aligned bilingual sentence pairs from the corpus. Lookup
    returns a :class:`TmHit` only when the best similarity ratio is at or
    above ``similarity_threshold``; otherwise returns ``None`` so the caller
    routes the sentence to the LLM.
    """

    __slots__ = ("_db_path", "_threshold", "_conn")

    def __init__(
        self, *, db_path: str, similarity_threshold: float = 0.98
    ) -> None:
        self._db_path: str = db_path
        self._threshold: float = similarity_threshold
        self._conn: sqlite3.Connection = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tm_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_sentence TEXT NOT NULL,
                target_sentence TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                law_slug TEXT NOT NULL,
                article TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def build_from_corpus(self, corpus_dir: Path) -> None:
        """Build the TM by aligning ar/en article pairs from ``corpus_dir``.

        Clears existing entries, then inserts aligned pairs. Safe to call
        repeatedly (idempotent rebuild).
        """
        self._conn.execute("DELETE FROM tm_entries")
        entries: list[TmEntry] = _align_corpus(corpus_dir)
        self._conn.executemany(
            """
            INSERT INTO tm_entries
                (source_sentence, target_sentence, source_lang,
                 target_lang, law_slug, article)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (e.source_sentence, e.target_sentence, e.source_lang,
                 e.target_lang, e.law_slug, e.article)
                for e in entries
            ],
        )
        self._conn.commit()

    def lookup(self, sentence: str, direction: str) -> TmHit | None:
        """Look up a source sentence; return a TmHit if above threshold.

        ``direction`` is ``"ar-en"`` or ``"en-ar"`` — determines which
        source language to match against. Returns ``None`` if no entry
        reaches the similarity threshold.
        """
        source_lang: str = direction.split("-")[0]
        rows: list[tuple[str, str, int, int]] = self._conn.execute(
            "SELECT source_sentence, target_sentence, ROWID, 0 "
            "FROM tm_entries WHERE source_lang = ?",
            (source_lang,),
        ).fetchall()

        best_ratio: float = 0.0
        best_source: str = ""
        best_target: str = ""
        for source_sentence, target_sentence, _rowid, _ in rows:
            ratio: float = SequenceMatcher(
                None, sentence, source_sentence
            ).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_source = source_sentence
                best_target = target_sentence

        if best_ratio < self._threshold:
            return None

        return TmHit(
            source_sentence=best_source,
            target_sentence=best_target,
            similarity=best_ratio,
            char_start=0,
            char_end=len(sentence),
        )

    def list_all(self) -> list[dict[str, str]]:
        """Return all entries as dicts (for testing / inspection)."""
        rows: list[tuple[str, str, str, str, str, str]] = self._conn.execute(
            "SELECT source_sentence, target_sentence, source_lang, "
            "target_lang, law_slug, article FROM tm_entries"
        ).fetchall()
        return [
            {
                "source_sentence": r[0],
                "target_sentence": r[1],
                "source_lang": r[2],
                "target_lang": r[3],
                "law_slug": r[4],
                "article": r[5],
            }
            for r in rows
        ]

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_tm.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/tm.py tests/test_tm.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/tm.py tests/test_tm.py
git commit -m "feat: add TranslationMemory with corpus alignment and threshold-gated lookup"
```

---

## Task 4: Decision — `route_tm` pure function

**Files:**
- Create: `src/decision.py`
- Test: `tests/test_decision.py` (create)

**Interfaces:**
- Consumes: `TmHit | None` (from `TranslationMemory.lookup`)
- Produces: `route_tm(hit: TmHit | None, threshold: float) -> bool` — returns `True` if the sentence should use the TM (bypass LLM), `False` if it should go to the LLM

- [ ] **Step 1: Write the failing test**

Create `tests/test_decision.py`:

```python
"""Tests for the TM routing decision function (task 4)."""
from __future__ import annotations

import pytest

from src.decision import route_tm
from src.state import TmHit

pytestmark = pytest.mark.unit


def test_route_tm_none_hit_returns_false():
    """No TM hit → go to LLM."""
    assert route_tm(None, threshold=0.98) is False


def test_route_tm_above_threshold_returns_true():
    """TM hit with similarity above threshold → use TM."""
    hit: TmHit = {
        "source_sentence": "test",
        "target_sentence": "اختبار",
        "similarity": 0.99,
        "char_start": 0,
        "char_end": 4,
    }
    assert route_tm(hit, threshold=0.98) is True


def test_route_tm_at_threshold_returns_true():
    """Similarity exactly at threshold → use TM (>= is the rule)."""
    hit: TmHit = {
        "source_sentence": "test",
        "target_sentence": "اختبار",
        "similarity": 0.98,
        "char_start": 0,
        "char_end": 4,
    }
    assert route_tm(hit, threshold=0.98) is True


def test_route_tm_below_threshold_returns_false():
    """TM hit with similarity below threshold → go to LLM."""
    hit: TmHit = {
        "source_sentence": "test",
        "target_sentence": "اختبار",
        "similarity": 0.97,
        "char_start": 0,
        "char_end": 4,
    }
    assert route_tm(hit, threshold=0.98) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_decision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.decision'`

- [ ] **Step 3: Implement `src/decision.py`**

```python
"""TM routing decision — pure function, no LLM, no side effects.

Single responsibility: decide whether a sentence should use a TM hit
(bypass the LLM) or go to the LLM. The decision is threshold-gated:
a hit with similarity >= threshold uses the TM; anything below goes to
the LLM. This is the conservative gate that prevents silent legal errors
from near-matches (spec §5.4 / §7.2).
"""
from __future__ import annotations

from src.state import TmHit


def route_tm(hit: TmHit | None, *, threshold: float) -> bool:
    """Return True if the sentence should use the TM (bypass the LLM).

    A ``None`` hit (no TM match at all) always returns False. A hit with
    ``similarity >= threshold`` returns True; below the threshold returns
    False. The comparison is ``>=`` so a hit exactly at the threshold is
    accepted (spec §7.2: "≥ 98% similarity").
    """
    if hit is None:
        return False
    return hit["similarity"] >= threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_decision.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/decision.py tests/test_decision.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/decision.py tests/test_decision.py
git commit -m "feat: add route_tm decision function with threshold gating"
```

---

## Task 5: Node — `tm_lookup_node`

**Files:**
- Create: `tm_lookup_node` function in `src/nodes.py` (add, do not modify existing nodes — OCP)
- Test: `tests/test_tm_node.py` (create)

**Interfaces:**
- Consumes: `TranslationMemory` (from `src/tm.py`), `AppConfig` (for threshold), `TranslationState` (reads `input_text`, `direction`)
- Produces: writes `tm_hits: list[TmHit]` to state

- [ ] **Step 1: Write the failing test**

Create `tests/test_tm_node.py`:

```python
"""Tests for the tm_lookup node (task 5).

Uses an in-memory TranslationMemory built from a temp corpus — no real
SQLite file, no Ollama daemon (testing-verification §3.4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config import AppConfig
from src.nodes import tm_lookup_node
from src.state import TranslationState
from src.tm import TranslationMemory

pytestmark = pytest.mark.unit


def _write_corpus(corpus_dir: Path) -> None:
    """Write a minimal bilingual corpus for TM tests."""
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون المدني العراقي\nLANG: ar\n---\n\n"
        "ARTICLE 1\nعقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.\n",
        encoding="utf-8",
    )
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Iraqi Civil Code\nLANG: en\n---\n\n"
        "ARTICLE 1\nA contract of sale is an agreement to transfer ownership "
        "of a thing in exchange for a price.\n",
        encoding="utf-8",
    )


def _state(input_text: str, direction: str = "ar-en") -> TranslationState:
    return {
        "input_text": input_text,
        "direction": direction,  # type: ignore[arg-type]
        "glossary_hits": [],
        "context_chunks": [],
        "tm_hits": [],
        "draft": "",
        "audit": None,
        "revision_count": 0,
        "final_output": None,
        "warnings": [],
    }


def test_tm_lookup_exact_match_populates_tm_hits(tmp_path: Path):
    """An exact match populates tm_hits with the stored translation."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    cfg = AppConfig()
    state = _state("عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.")
    result = tm_lookup_node(state, tm=tm, cfg=cfg)

    assert len(result["tm_hits"]) == 1
    assert "contract of sale" in result["tm_hits"][0]["target_sentence"].lower()
    tm.close()


def test_tm_lookup_no_match_leaves_empty_tm_hits(tmp_path: Path):
    """A non-matching input leaves tm_hits empty."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    cfg = AppConfig()
    state = _state("نص قانوني مختلف تماماً لا يطابق أي شيء.")
    result = tm_lookup_node(state, tm=tm, cfg=cfg)

    assert result["tm_hits"] == []
    tm.close()


def test_tm_lookup_none_tm_leaves_empty(tmp_path: Path):
    """When tm is None, tm_hits stays empty (TM disabled)."""
    cfg = AppConfig()
    state = _state("أي نص")
    result = tm_lookup_node(state, tm=None, cfg=cfg)
    assert result["tm_hits"] == []


def test_tm_lookup_preserves_other_state_fields(tmp_path: Path):
    """The node only writes tm_hits; other fields are preserved."""
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_corpus(corpus_dir)

    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    cfg = AppConfig()
    state = _state("عقد البيع هو اتفاق يقتضي نقل ملكية شيء مقابل ثمن.")
    state["glossary_hits"] = [{"source_term": "x", "target_term": "y",
        "law_ref": "", "article_ref": "", "note": "",
        "char_start": 0, "char_end": 1}]
    result = tm_lookup_node(state, tm=tm, cfg=cfg)

    assert result["glossary_hits"] == state["glossary_hits"]
    assert result["input_text"] == state["input_text"]
    tm.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_tm_node.py -v`
Expected: FAIL — `ImportError: cannot import name 'tm_lookup_node' from 'src.nodes'`

- [ ] **Step 3: Implement `tm_lookup_node` in `src/nodes.py`**

First, add `TmHit` to the existing `src.state` imports at the top of `src/nodes.py`. The current imports (lines 43-52) are:

```python
from src.state import (
    ContextChunk as StateContextChunk,
)
from src.state import (
    GlossaryHit as StateGlossaryHit,
)
from src.state import (
    TranslationState,
    Verdict,
)
```

Add a new import block after them:

```python
from src.state import (
    TmHit as StateTmHit,
)
```

Then add at the end of `src/nodes.py` (after `finalize_node`, do not modify existing functions):

```python
# ---------------------------------------------------------------------------
# tm_lookup_node (TM layer — spec §5)
# ---------------------------------------------------------------------------


def tm_lookup_node(
    state: TranslationState,
    *,
    tm: object | None = None,
    cfg: AppConfig,
) -> TranslationState:
    """Look up the input text in the Translation Memory; populate ``tm_hits``.

    Reads: ``input_text``, ``direction``.
    Writes: ``tm_hits``.

    When ``tm`` is ``None`` (TM disabled), ``tm_hits`` is set to an empty
    list and the node is a no-op pass-through. When the TM is enabled, the
    full input text is looked up; a hit at or above the configured
    threshold populates ``tm_hits`` with the stored target translation.
    The translate node checks ``tm_hits`` and, if non-empty, uses the TM
    output directly instead of calling the LLM (spec §5.4).
    """
    _require_fields(state, ("input_text", "direction"))
    if tm is None:
        return {**state, "tm_hits": []}

    input_text: str = state["input_text"].strip()
    hit: StateTmHit | None = tm.lookup(  # type: ignore[attr-defined]
        input_text, state["direction"]
    )
    if hit is None:
        return {**state, "tm_hits": []}

    return {**state, "tm_hits": [hit]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_tm_node.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/nodes.py tests/test_tm_node.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/nodes.py tests/test_tm_node.py
git commit -m "feat: add tm_lookup_node for TM-based sentence lookup"
```

---

## Task 6: Graph — Insert `tm_lookup` node into the pipeline

**Files:**
- Modify: `src/graph.py` (add `TM_LOOKUP_NODE`, wire it between preprocess and translate)
- Modify: `tests/test_graph.py` (add topology test)

**Interfaces:**
- Consumes: `tm_lookup_node` (from Task 5), `TranslationMemory` (from Task 3), `AppConfig.tm_enabled`
- Produces: the compiled graph now runs `preprocess → tm_lookup → translate → audit → ...`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_graph.py` (after the existing topology tests):

```python
def test_graph_includes_tm_lookup_node_when_enabled(
    config, mock_llm, mock_embedder, glossary_index, tmp_path
):
    """When tm_enabled=True, the graph topology includes tm_lookup."""
    from src.graph import build_graph, TM_LOOKUP_NODE

    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(_fixture_chunks(), persist_dir=persist_dir)

    # Build a TM from a temp corpus
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون\nLANG: ar\n---\n\nARTICLE 1\nعقد البيع\n",
        encoding="utf-8",
    )
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Code\nLANG: en\n---\n\nARTICLE 1\nContract of sale\n",
        encoding="utf-8",
    )
    from src.tm import TranslationMemory
    tm = TranslationMemory(
        db_path=str(tmp_path / "tm.sqlite"),
        similarity_threshold=0.98,
    )
    tm.build_from_corpus(corpus_dir)

    graph = build_graph(
        llm=mock_llm, cfg=config, glossary_index=glossary_index,
        embedder=mock_embedder, persist_dir=persist_dir, tm=tm,
    )
    state = _initial_state("عقد البيع")
    result = graph.invoke(state)
    assert "tm_hits" in result
    tm.close()


def test_graph_skips_tm_lookup_when_tm_is_none(
    config, mock_llm, mock_embedder, glossary_index, tmp_path
):
    """When tm=None, the graph still runs; tm_hits is empty."""
    persist_dir = str(tmp_path / "chroma")
    build_chroma_collection(_fixture_chunks(), persist_dir=persist_dir)

    graph = build_graph(
        llm=mock_llm, cfg=config, glossary_index=glossary_index,
        embedder=mock_embedder, persist_dir=persist_dir, tm=None,
    )
    state = _initial_state("المادة 148: عقد البيع")
    result = graph.invoke(state)
    assert result["tm_hits"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_graph.py -k tm_lookup -v`
Expected: FAIL — `ImportError: cannot import name 'TM_LOOKUP_NODE' from 'src.graph'`

- [ ] **Step 3: Modify `src/graph.py`**

Add `TM_LOOKUP_NODE` constant after `PREPROCESS_NODE` (line 40):

```python
TM_LOOKUP_NODE: str = "tm_lookup"
```

Add import of `tm_lookup_node` to the existing `from src.nodes import ...` line:

```python
from src.nodes import audit_node, finalize_node, preprocess_node, tm_lookup_node, translate_node
```

Add `tm: object | None = None` parameter to `build_graph` (after `run_logger`):

```python
def build_graph(
    *,
    llm: LLMEngineAdapter,
    cfg: AppConfig,
    glossary_index: GlossaryIndex | None = None,
    embedder: object | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
) -> Any:
```

Add the `tm_lookup` node after the `preprocess` node registration (after line 162):

```python
    graph.add_node(
        TM_LOOKUP_NODE,
        _bind(TM_LOOKUP_NODE, partial(tm_lookup_node, tm=tm, cfg=cfg)),
    )
```

Change the edge from `PREPROCESS_NODE -> TRANSLATE_NODE` to go through `tm_lookup`:

Replace:
```python
    graph.add_edge(PREPROCESS_NODE, TRANSLATE_NODE)
```
With:
```python
    graph.add_edge(PREPROCESS_NODE, TM_LOOKUP_NODE)
    graph.add_edge(TM_LOOKUP_NODE, TRANSLATE_NODE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_graph.py -k tm_lookup -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full suite to check no regressions**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
Expected: all pass (existing graph tests must still pass — the `tm_lookup` node is a no-op pass-through when `tm=None`)

- [ ] **Step 6: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/graph.py tests/test_graph.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/graph.py tests/test_graph.py
git commit -m "feat: insert tm_lookup node between preprocess and translate"
```

---

## Task 7: CLI — Wire `TranslationMemory` via DI

**Files:**
- Modify: `src/cli.py` (construct `TranslationMemory` and pass to `build_graph` / `run_translation`)

**Interfaces:**
- Consumes: `TranslationMemory` (from Task 3), `AppConfig.tm_enabled` / `tm_db` / `tm_similarity_threshold`
- Produces: `run_translation` and `run_translation_streamed` accept a `tm` parameter; the CLI constructs a real `TranslationMemory` when `tm_enabled=True`

- [ ] **Step 1: Add `tm` parameter to `run_translation`**

In `src/cli.py`, add `tm: object | None = None` to `run_translation`'s signature (after `run_logger`):

```python
def run_translation(
    input_text: str,
    direction: str,
    cfg: AppConfig,
    *,
    llm: LLMEngineAdapter,
    embedder: object,
    glossary_index: GlossaryIndex | None = None,
    persist_dir: str | None = None,
    run_logger: RunLogger | None = None,
    tm: object | None = None,
) -> TranslationState:
```

Pass `tm=tm` to `build_graph`:

```python
    graph = build_graph(
        llm=llm,
        cfg=cfg,
        glossary_index=glossary_index,
        embedder=embedder,
        persist_dir=persist_dir,
        run_logger=run_logger,
        tm=tm,
    )
```

- [ ] **Step 2: Add `tm` parameter to `run_translation_streamed`**

Apply the same change to `run_translation_streamed` — add `tm: object | None = None` to its signature and pass `tm=tm` to `build_graph`.

- [ ] **Step 3: Construct `TranslationMemory` in the CLI translate/batch commands**

In the CLI command functions that call `run_translation` (the `translate` and `batch` commands), construct a `TranslationMemory` when `cfg.tm_enabled` is `True`:

```python
from src.tm import TranslationMemory

# Inside the translate command, before calling run_translation:
tm: TranslationMemory | None = None
if cfg.tm_enabled:
    tm = TranslationMemory(
        db_path=cfg.tm_db,
        similarity_threshold=cfg.tm_similarity_threshold,
    )
```

Pass `tm=tm` to `run_translation`. After the call, close it:

```python
    if tm is not None:
        tm.close()
```

Apply the same pattern to the `batch` command and the UI command (`_run_one_translation` or equivalent).

- [ ] **Step 4: Run full suite to check no regressions**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
Expected: all pass (existing CLI tests inject `tm=None` by default since the new parameter defaults to `None`)

- [ ] **Step 5: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/cli.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/cli.py
git commit -m "feat: wire TranslationMemory into CLI via dependency injection"
```

---

## Task 8: TM build command — CLI command to build the TM from corpus

**Files:**
- Modify: `src/cli.py` (add a `tm-build` subcommand)
- Test: `tests/test_cli.py` (add test)

**Interfaces:**
- Consumes: `TranslationMemory.build_from_corpus` (from Task 3), `AppConfig.paths.corpus_dir`
- Produces: a CLI command `python -m src.cli tm-build` that builds `db/tm.sqlite` from the corpus

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_tm_build_command_creates_db(tmp_path):
    """The tm-build command creates a TM SQLite DB from the corpus."""
    import sqlite3
    from typer.testing import CliRunner
    from src.cli import app

    runner = CliRunner()
    # Use a temp corpus dir and tm_db path
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "civil_code_ar.txt").write_text(
        "LAW: قانون\nLANG: ar\n---\n\nARTICLE 1\nعقد البيع\n",
        encoding="utf-8",
    )
    (corpus_dir / "civil_code_en.txt").write_text(
        "LAW: Code\nLANG: en\n---\n\nARTICLE 1\nContract of sale\n",
        encoding="utf-8",
    )
    tm_db = str(tmp_path / "tm.sqlite")

    result = runner.invoke(app, [
        "tm-build",
        "--corpus-dir", str(corpus_dir),
        "--tm-db", tm_db,
    ])
    assert result.exit_code == 0
    conn = sqlite3.connect(tm_db)
    count = conn.execute("SELECT COUNT(*) FROM tm_entries").fetchone()[0]
    conn.close()
    assert count > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_cli.py::test_tm_build_command_creates_db -v`
Expected: FAIL — no `tm-build` command exists

- [ ] **Step 3: Add the `tm-build` command to `src/cli.py`**

```python
@app.command("tm-build")
def tm_build(
    corpus_dir: Annotated[
        Path,
        typer.Option("--corpus-dir", "-c", help="Path to the corpus directory."),
    ] = None,
    tm_db: Annotated[
        str,
        typer.Option("--tm-db", help="Path to the TM SQLite DB to create."),
    ] = None,
) -> None:
    """Build the Translation Memory SQLite DB from the bilingual corpus."""
    cfg = load_config()
    cdir: Path = corpus_dir if corpus_dir is not None else Path(cfg.paths.corpus_dir)
    dbpath: str = tm_db if tm_db is not None else cfg.tm_db

    from src.tm import TranslationMemory
    tm = TranslationMemory(
        db_path=dbpath,
        similarity_threshold=cfg.tm_similarity_threshold,
    )
    tm.build_from_corpus(cdir)
    entries = tm.list_all()
    tm.close()
    typer.echo(f"TM built: {len(entries)} entries in {dbpath}")
```

The `app` Typer instance already exists in `src/cli.py` (line 118 area, shared with `src/config.py`). The existing commands use `@app.command()` with `Annotated[Path, typer.Option(...)]` parameters. Follow the same pattern as the `ingest` command (line 949). Place the new command after the `ingest` command.

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/test_cli.py::test_tm_build_command_creates_db -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 6: Lint changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/cli.py tests/test_cli.py`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/cli.py tests/test_cli.py
git commit -m "feat: add tm-build CLI command to build TM from corpus"
```

---

## Task 9: Final verification and documentation

**Files:**
- Modify: `AGENTS.md` (add TM build command to verification section)
- No new tests — this is a verification + docs task

- [ ] **Step 1: Run the full test suite**

Run: `.\.venv310\Scripts\python.exe -m pytest tests/ -q`
Expected: all pass, ~210+ tests (192 original + new tests from tasks 1-8)

- [ ] **Step 2: Lint all changed files**

Run: `.\.venv310\Scripts\python.exe -m ruff check src/config.py src/state.py src/tm.py src/decision.py src/nodes.py src/graph.py src/cli.py tests/test_config.py tests/test_tm.py tests/test_decision.py tests/test_tm_node.py tests/test_graph.py tests/test_cli.py`
Expected: no errors

- [ ] **Step 3: Build the TM from the real corpus**

Run: `.\.venv310\Scripts\python.exe -m src.cli tm-build`
Expected: "TM built: N entries in db/tm.sqlite" (N depends on how many ar/en pairs are in `data/corpus/`)

- [ ] **Step 4: Verify the TM was created**

Run: `.\.venv310\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('db/tm.sqlite'); print(c.execute('SELECT COUNT(*) FROM tm_entries').fetchone()[0], 'entries'); c.close()"`
Expected: a positive number

- [ ] **Step 5: Update `AGENTS.md`**

Add to the verification commands section:

```markdown
- TM build: `.\.venv310\Scripts\python.exe -m src.cli tm-build`
  - Builds `db/tm.sqlite` from `data/corpus` aligned ar/en article pairs.
```

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md
git commit -m "docs: add TM build command to AGENTS.md verification section"
```
