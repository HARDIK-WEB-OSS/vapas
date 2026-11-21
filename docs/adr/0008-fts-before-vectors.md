# ADR 0008: Postgres full-text search over clauses before any vector search

Status: accepted (M0.5, 19 Nov 2026)

## Context
VAPAS must cite exact clauses from a small set of verified instruments: the TAT circular and its amendments, RB-IOS 2026, and RB-IOS 2021 for history. The corpus is hundreds of clauses, not millions. Citations must be exact; "close enough" retrieval counts as a failure.

## Options
1. pgvector embeddings (semantic search) from the start.
2. An external search engine (Elasticsearch, OpenSearch).
3. Postgres full-text search (`tsvector` with a GIN index) over a clause table, measured with a 30-question eval; add pgvector hybrid search only if recall@5 < 0.9.

## Decision
Option 3. `circular_clauses` holds one row per clause with instrument id, clause number, text and URL. Every answer path returns a citation or "not found".

## Result (M6, 21 Nov 2026)
On the 30-question evaluation over the 26 verified clause quotes, plain `ts_rank_cd` reached recall@5 0.933 and recall@1 0.533. Adding an inverse-document-frequency score (rare exact terms such as APBS or NACH outweigh common words) and a small domain thesaurus for everyday words raised this to recall@5 1.000 and recall@1 0.767 (`docs/knowledge_eval.md`). pgvector is therefore not built. The evaluation is re-run after the full PDFs are ingested.

## Consequences
- No embedding model and no extra extension or service in v1.
- Exact terms (TAT, T+5, NACH, clause numbers) are matched exactly, which suits legal text.
- Paraphrased or Hindi queries may be missed. The M6 eval measures this and triggers the vector upgrade if needed, with before/after numbers.
