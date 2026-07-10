# refactor-to-component-architecture

Restructure the 21 flat src/ modules into 4 bounded-context components (translation_pipeline, knowledge_sources, infrastructure, interfaces) plus a config package, each with a models.py for its domain types, and an app.py DI entry point.
