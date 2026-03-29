# Eval Decision V1

## Executive Summary

Placeholder: write a one-sentence recommendation after reviewing the baseline.

## Baseline Metrics Table

| Metric            | Score | Zone | Notes |
| ----------------- | ----- | ---- | ----- |
| precision_at_k    | TBD   | TBD  |       |
| recall_at_k       | TBD   | TBD  |       |
| mrr               | TBD   | TBD  |       |
| groundedness      | TBD   | TBD  |       |
| citation_accuracy | TBD   | TBD  |       |
| persona_fidelity  | TBD   | TBD  |       |
| refusal_quality   | TBD   | TBD  |       |

## Analysis Per Upgrade Path

### Chunk Enrichment

Trigger:
Low recall and low groundedness, especially when the right concepts appear to
exist in source material but are not retrieved reliably.

Expected impact:
Improve retrieval recall by enriching chunks with additional lexical and
question-like context.

Cost:
Higher ingestion cost and more data to embed and index.

Reference:
See `docs/rag.md` for chunk enrichment guidance.

### Parent-Child Chunking

Trigger:
Relevant fragments are found, but answers still lack enough surrounding context
to stay grounded.

Expected impact:
Increase context completeness for long documents and reduce answer fragmentation.

Cost:
Additional hierarchy handling in ingestion and retrieval.

Reference:
See `docs/rag.md` for parent-child chunking guidance.

### BGE-M3 Fallback

Trigger:
Sparse keyword retrieval underperforms in target languages or multilingual
scenarios.

Expected impact:
Improve keyword-style recall for languages where BM25 stemming and stopword
behavior are not sufficient.

Cost:
Additional model dependency and operational complexity.

Reference:
See `docs/spec.md` multilingual support requirements.

## Worst Performers Analysis

Placeholder: summarize the lowest-scoring cases and the most likely causes.

## Human Review Summary

Placeholder: record agreement or disagreement with judge scores and why.

## Prioritized Recommendations

1. Placeholder.
2. Placeholder.
3. Placeholder.

## Next Steps

1. Placeholder: define the first Phase 9 story.
2. Placeholder: define the second Phase 9 story.
3. Placeholder: define the follow-up verification order.
