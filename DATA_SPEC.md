# Data Specification

> Defines the ingestion formats for Iraqi legal corpus, the schema for the Exact-Match Glossary, and the chunking strategy optimized for legal clauses under the 8 GB RAM constraint.

---

## 1. Corpus Ingestion Format

### 1.1 Source Files

Raw Iraqi legal texts are stored as plain UTF-8 text files under `data/corpus/`. Each law has up to two files — one per language — named with a strict convention:

```
data/corpus/<law_slug>_<lang>.txt
```

Examples:
```
data/corpus/civil_code_ar.txt
data/corpus/civil_code_en.txt
data/corpus/penal_code_ar.txt
data/corpus/penal_code_en.txt
data/corpus/civil_procedure_code_ar.txt
data/corpus/civil_procedure_code_en.txt
data/corpus/commercial_code_ar.txt
data/corpus/penal_procedure_code_ar.txt
```

`<law_slug>` is lowercase snake_case. `<lang>` is `ar` or `en`. Bilingual pairs are preferred but not mandatory; missing pairs are recorded as warnings during ingestion.

### 1.2 File Structure

Each corpus file must follow this structure:

```
LAW: <Official Law Name in the file's language>
SOURCE: <Official Gazette reference, e.g. "Al-Waqa'i al-Iraqiya No. 40, 1951">
LANG: <ar|en>
---

ARTICLE 1
<text of article 1>

ARTICLE 2
<text of article 2>

ARTICLE 3
<text of article 3, may span multiple paragraphs>

...
```

Rules:
- The header block (lines before the first `---`) is mandatory and parsed as metadata.
- `ARTICLE N` markers are mandatory and must be on their own line. `N` may be numeric (`1`, `2`) or numeric with a suffix (`148 bis`, `148 ter`).
- Article text continues until the next `ARTICLE` marker or EOF.
- Blank lines within an article are preserved as paragraph breaks.
- No HTML, no Markdown formatting inside the body. Plain text only.

### 1.3 Supported Laws (Initial Corpus)

| Slug | Official Name (EN) | Official Name (AR) |
|---|---|---|
| `civil_code` | Iraqi Civil Code | قانون المدني العراقي |
| `penal_code` | Iraqi Penal Code | قانون العقوبات العراقي |
| `civil_procedure_code` | Civil Procedure Code | قانون أصول المحاكمات المدنية |
| `commercial_code` | Commercial Code | قانون التجارة |
| `penal_procedure_code` | Penal Procedure Code | قانون أصول المحاكمات الجزائية |

Additional laws are added by dropping a correctly-formatted file into `data/corpus/` and re-running ingestion. No code change required.

### 1.4 Ingestion Parsing Rules

1. Read file as UTF-8. Fail hard on encoding errors — do not silently substitute.
2. Parse header metadata. Reject file if `LAW`, `SOURCE`, or `LANG` is missing.
3. Split on `^ARTICLE\s+` regex. Each match begins a new article record.
4. Normalize article numbers: strip whitespace, lowercase suffixes (`Bis` → `bis`).
5. Record `char_start` and `char_end` offsets relative to the original file for provenance.
6. Pass each article to the chunker (see §3).

---

## 2. Exact-Match Glossary Schema

### 2.1 JSON File Format

Glossary files live in `data/glossary/<domain>.json`. Each file is a JSON object with this top-level shape:

```json
{
  "domain": "civil_code",
  "version": "1.0.0",
  "last_updated": "2026-07-01",
  "terms": [
    {
      "source_term": "عقد البيع",
      "source_lang": "ar",
      "target_term": "contract of sale",
      "target_lang": "en",
      "law_ref": "Civil Code",
      "article_ref": "148",
      "note": "Core nominate contract; do not render as 'sale agreement'.",
      "priority": 10
    },
    {
      "source_term": "الالتزام ببذل العناية",
      "source_lang": "ar",
      "target_term": "obligation of means",
      "target_lang": "en",
      "law_ref": "Civil Code",
      "article_ref": "175",
      "note": "Distinguished from 'obligation of result' (الالتزام بتحقيق نتيجة).",
      "priority": 9
    }
  ]
}
```

### 2.2 Field Specification

| Field | Type | Required | Description |
|---|---|---|---|
| `domain` | string | yes | Matches the corpus slug this glossary applies to. |
| `version` | string | yes | Semver. Bumped on any term change. |
| `last_updated` | string | yes | ISO 8601 date. |
| `terms[]` | array | yes | At least one entry per file. |
| `terms[].source_term` | string | yes | The term as it appears in source text. Not normalized — stored verbatim. |
| `terms[].source_lang` | string | yes | `ar` or `en`. |
| `terms[].target_term` | string | yes | The canonical translation. |
| `terms[].target_lang` | string | yes | `ar` or `en`. |
| `terms[].law_ref` | string | yes | Law name in English, matching corpus `LAW` header. |
| `terms[].article_ref` | string | no | Article number where the term is defined or first used. |
| `terms[].note` | string | no | Usage guidance for the translator. Not shown to the LLM unless explicitly enabled. |
| `terms[].priority` | int | no | Default 0. Higher wins on conflict. Used when two terms match the same span. |

### 2.3 Normalization for Indexing

When loading into SQLite, `source_term` is normalized for matching but the original is preserved:

- **Arabic**: strip diacritics (tashkeel), strip tatweel (`ـ`), normalize Alef variants (`أإآ` → `ا`), normalize Ya/Alef Maqsura (`ى` → `ي`), lowercase has no effect (Arabic has no case).
- **English**: lowercase, collapse whitespace, strip trailing punctuation.

The normalized form is stored in an additional column `source_term_norm` used for lookup. The verbatim `source_term` is used for prompt display and offset matching.

### 2.4 Conflict Resolution

When two glossary entries match the same character span in the input:

1. Higher `priority` wins.
2. If equal priority, longer `source_term` wins.
3. If equal length, the entry from the more specific `law_ref` wins (e.g., `Civil Code` beats a generic entry with `law_ref = null`).
4. If still tied, the entry that appears first in JSON file order wins. This is deterministic.

### 2.5 Validation at Ingestion

The ingestion command validates every glossary file and refuses to load on any of:

- Missing required field.
- `source_lang == target_lang` (no-op entry).
- `source_term` or `target_term` is empty or whitespace-only.
- Duplicate `(source_term_norm, source_lang, target_lang)` tuple within the same file.
- `domain` does not match any file in `data/corpus/` (warning, not error — allows pre-loading glossary before corpus).

---

## 3. Text Chunking Strategy

### 3.1 Primary Unit: The Article

Iraqi laws are article-structured. The **article is the primary semantic unit** and the default chunk boundary. Chunking operates per-article, not across the whole file.

### 3.2 Chunking Rules

For each article:

1. **If `len(article_text) <= 512 tokens`**: the entire article is one chunk. This is the common case for Iraqi statutory articles.

2. **If `len(article_text) > 512 tokens`**: split into overlapping chunks:
   - Target chunk size: **512 tokens** (measured with the `nomic-embed-text` tokenizer approximation — see §3.4).
   - Overlap: **64 tokens** between consecutive chunks.
   - Split at paragraph boundaries first (`\n\n`). If a single paragraph exceeds 512 tokens, split at sentence boundaries. If a single sentence exceeds 512 tokens (rare in legal text), split at 512-token hard boundary.

3. **Never split mid-sentence** unless the sentence itself exceeds the chunk size.

4. Each chunk inherits the article's metadata (`law`, `article`, `lang`) and gets a sequential `chunk_idx` starting at 0.

### 3.3 Token Budget Rationale

- **512 tokens per chunk**: balances embedding quality (enough context) against retrieval precision (not too dilute). Legal articles are typically 100–300 tokens, so most fit in one chunk.
- **64 token overlap**: ~12.5% of chunk size. Sufficient to preserve cross-chunk semantic continuity for multi-paragraph articles without excessive duplication in the vector store.
- **Top-k = 8 retrieval**: at 512 tokens/chunk, 8 chunks = 4096 tokens of context, leaving ~4000 tokens for the source + glossary + prompt overhead within the 8192-token LLM context window.

### 3.4 Tokenizer

`nomic-embed-text` does not ship a public Python tokenizer. The system uses a conservative approximation:

```python
def approx_token_count(text: str) -> int:
    # Heuristic: 1 token ~= 4 chars for English, 1 token ~= 2 chars for Arabic.
    # Use a blended estimate based on script ratio.
    arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
    other_chars = len(text) - arabic_chars
    return max(1, (arabic_chars // 2) + (other_chars // 4))
```

This is intentionally conservative (overestimates slightly), which biases toward smaller chunks — safe for the RAM budget.

### 3.5 Chunk ID Scheme

```
{law_slug}_{article_normalized}_{chunk_idx}
```

Example: `civil_code_148_0`, `civil_code_148_1`, `penal_code_40_bis_0`.

IDs are deterministic. Re-ingestion of the same corpus produces identical IDs, enabling idempotent rebuilds.

---

## 4. Ingestion Command Interface

```powershell
python -m src.ingestion [--rebuild] [--glossary-only] [--corpus-only] [--limit N]
```

| Flag | Effect |
|---|---|
| `--rebuild` | Drop existing ChromaDB collection and SQLite glossary, then re-ingest from scratch. |
| `--glossary-only` | Skip corpus chunking; only load `data/glossary/*.json` into SQLite. |
| `--corpus-only` | Skip glossary; only chunk and embed `data/corpus/*.txt` into ChromaDB. |
| `--limit N` | Process only the first N articles per file. Used for smoke tests. |

### Ingestion Output

The command prints a structured summary:

```
[ingestion] Glossary: 3 files, 412 terms loaded, 0 conflicts, 0 validation errors.
[ingestion] Corpus: 5 laws, 1,847 articles, 1,910 chunks, 0 parse errors.
[ingestion] ChromaDB: collection 'iraqi_laws' rebuilt, 1,910 embeddings written.
[ingestion] Duration: 142s. Peak RSS: 2.1 GB.
```

Any non-zero error count exits with code 1 and does not write partial state (glossary load and corpus embed are atomic per file; `--rebuild` only swaps in the new DB after successful completion).

---

## 5. Data Provenance & Integrity

- Every chunk in ChromaDB carries `char_start` and `char_end` so the application can cite the exact source span.
- Every glossary term carries `law_ref` and `article_ref` so the auditor can verify the binding against the corpus.
- The `ingestion` command writes a `data/ingestion_manifest.json` recording: file hashes of all inputs, term count, chunk count, model versions, timestamp. This manifest is checked on startup; a mismatch triggers a warning suggesting `--rebuild`.
