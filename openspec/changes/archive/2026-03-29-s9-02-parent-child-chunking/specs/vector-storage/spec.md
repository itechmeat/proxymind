## ADDED Requirements

### Requirement: Parent metadata on child Qdrant payloads

For story S9-02, Qdrant SHALL continue indexing child chunks only, but each child point payload SHALL use one fixed parent-aware payload shape. That shape SHALL always include `parent_id`, `parent_text_content`, `parent_token_count`, `parent_anchor_page`, `parent_anchor_chapter`, `parent_anchor_section`, and `parent_anchor_timecode`. For qualifying hierarchical children these fields SHALL contain parent metadata. For flat children these same fields SHALL still be present and SHALL be null.

#### Scenario: Qualifying child point includes parent metadata
- **WHEN** a qualifying long-form child chunk is upserted to Qdrant
- **THEN** the child point payload SHALL include its parent identifier and parent text/anchor metadata

#### Scenario: Flat child point uses null parent fields in the same payload shape
- **WHEN** a non-qualifying flat chunk is upserted to Qdrant
- **THEN** the child point payload SHALL include the full parent-aware field set
- **AND** all parent metadata fields SHALL be null

---

### Requirement: Retrieved child results expose parent metadata

Child-ranked retrieval results SHALL expose the parent metadata stored on the child point payload without changing ranking semantics. `RetrievedChunk` SHALL still represent the matched child fragment, with parent data attached as supporting context.

#### Scenario: Hybrid retrieval returns child plus parent metadata
- **WHEN** hybrid retrieval returns a child chunk from a qualifying long-form document
- **THEN** the retrieval result SHALL contain the matched child text and child anchors
- **AND** it SHALL also contain the parent identifier and parent metadata needed for prompt assembly

#### Scenario: Retrieval ranking remains child-only
- **WHEN** hybrid or dense retrieval is executed for a qualifying long-form document
- **THEN** ranking SHALL continue to be based on child chunk vectors only
- **AND** parent sections SHALL NOT be ranked as independent retrieval points in this story
