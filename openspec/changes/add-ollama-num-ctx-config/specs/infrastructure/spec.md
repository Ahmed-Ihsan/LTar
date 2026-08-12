## MODIFIED Requirements

### Requirement: OllamaEngineAdapter num_ctx forwarding

`OllamaEngineAdapter.__init__` SHALL accept a keyword-only `num_ctx: int | None = None` parameter. When `num_ctx` is not None, the adapter SHALL include `"num_ctx": <value>` in the Ollama `options` dict passed to `client.chat` on every `generate` call. When `num_ctx` is None (the constructor default), the adapter SHALL omit `num_ctx` from the options dict so Ollama auto-selects the context size (preserving the pre-change behavior for direct construction). The `LLMEngineAdapter.generate` protocol signature MUST NOT change — `num_ctx` is a construction-time parameter, not a per-call parameter. The `_construct_adapters` composition root in `cli.py` SHALL pass `cfg.ollama_num_ctx` to `OllamaEngineAdapter` on the Ollama/llamacpp path. The Gemini path is unaffected.

#### Scenario: num_ctx is forwarded to the options dict
- **GIVEN** an `OllamaEngineAdapter` constructed with `num_ctx=2048` and a mock client
- **WHEN** `generate` is called
- **THEN** the `options` dict passed to `client.chat` contains `"num_ctx": 2048`

#### Scenario: num_ctx None omits the key (backward compatible)
- **GIVEN** an `OllamaEngineAdapter` constructed with `num_ctx=None` (the default) and a mock client
- **WHEN** `generate` is called
- **THEN** the `options` dict passed to `client.chat` does NOT contain a `"num_ctx"` key

#### Scenario: _construct_adapters wires cfg.ollama_num_ctx
- **GIVEN** an `AppConfig` with `ollama_num_ctx=2048` and `llm_backend="ollama"`
- **WHEN** `_construct_adapters` constructs the `OllamaEngineAdapter`
- **THEN** the adapter's `num_ctx` equals 2048

#### Scenario: generate protocol signature is unchanged
- **GIVEN** the `LLMEngineAdapter` protocol
- **WHEN** its `generate` method signature is inspected
- **THEN** it accepts `(system_prompt, user_prompt, *, model, temperature, max_tokens, timeout)` with no `num_ctx` parameter

#### Scenario: Gemini path is unaffected
- **GIVEN** an `AppConfig` with `llm_backend="gemini"` and a valid `GEMINI_API_KEY`
- **WHEN** `_construct_adapters` constructs the adapters
- **THEN** a `GeminiEngineAdapter` is constructed (not `OllamaEngineAdapter`) and `ollama_num_ctx` is not passed to it
