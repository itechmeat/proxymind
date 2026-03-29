# ProxyMind FAQ

## What does ProxyMind store in PostgreSQL?

PostgreSQL stores relational metadata such as sources, documents, chunks,
snapshots, sessions, and audit logs.

## What does Qdrant store?

Qdrant stores dense and BM25 sparse vectors for retrieval over chunked content.

## Why are citations important?

Citations connect generated claims back to concrete sources so that users can
inspect the evidence behind a response.

## When should the system refuse to answer?

The system should refuse when the available retrieved context does not support a
reliable answer or when the question falls outside the known material.

## How are upgrade decisions made?

Upgrade decisions are made from baseline eval reports that compare retrieval and
answer quality metrics before and after a change.

## What is the purpose of snapshots?

Snapshots freeze a specific published knowledge state so chats and evals can be
reproduced against a stable corpus.
