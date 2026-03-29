## ADDED Requirements

### Requirement: Long-form hierarchy qualification

For story S9-02, the system SHALL qualify Path B and Path C documents for hierarchical indexing using explicit long-form thresholds instead of requiring heading-rich structure. Qualification SHALL consider at minimum total parsed token count and flat chunk count. Available structure signals MAY improve the decision but SHALL NOT be a mandatory prerequisite. Weakly structured long-form documents that meet the thresholds SHALL enter the bounded fallback grouping path rather than being forced onto flat chunking.

#### Scenario: Structured long-form document qualifies
- **WHEN** a Path B or Path C document exceeds the configured long-form token and chunk thresholds
- **AND** the parsed chunks contain chapter or section anchors
- **THEN** the document SHALL qualify for hierarchical indexing
- **AND** the qualification reason SHALL indicate structure-first processing

#### Scenario: Weakly structured long-form document qualifies for fallback grouping
- **WHEN** a Path B or Path C document exceeds the configured long-form token and chunk thresholds
- **AND** the parsed chunks do not contain reliable chapter or section anchors
- **THEN** the document SHALL still qualify for hierarchical indexing
- **AND** the qualification reason SHALL indicate bounded fallback grouping

#### Scenario: Short document remains flat
- **WHEN** a Path B or Path C document does not meet the configured long-form token or chunk thresholds
- **THEN** the document SHALL remain on the existing flat chunking path
- **AND** no parent sections SHALL be created

---

### Requirement: Parent section persistence

For every qualifying long-form Path B or Path C document, the system SHALL persist parent sections as first-class records in PostgreSQL and link each qualifying child chunk to exactly one parent section. Parent records SHALL be stored in a dedicated `chunk_parents` relation with the same ownership and snapshot scope as the child chunks. Parent-child links SHALL NOT cross document versions or snapshots.

#### Scenario: Parent rows are created for a qualifying document
- **WHEN** a qualifying long-form Path B or Path C document is ingested
- **THEN** one or more parent section records SHALL be created in PostgreSQL
- **AND** each parent record SHALL reference the same `source_id`, `document_version_id`, and `snapshot_id` scope as its children

#### Scenario: Every qualifying child links to exactly one parent
- **WHEN** child chunks are persisted for a qualifying long-form document
- **THEN** every child chunk SHALL have a non-null `parent_id`
- **AND** every `parent_id` SHALL reference an existing parent section record in the same document version and snapshot

#### Scenario: Non-qualifying document stores no parent links
- **WHEN** a document remains on the flat chunking path
- **THEN** no parent section records SHALL be created for that document
- **AND** all persisted child chunks for that document SHALL keep `parent_id` as null

---

### Requirement: Structure-first parent construction with deterministic fallback

The system SHALL construct parent sections from normalized document structure first. When structure is missing, shallow, or produces oversized groups, it SHALL use deterministic bounded fallback grouping over adjacent child chunks. Fallback grouping SHALL respect configured parent target/max token bounds and preserve child order.

#### Scenario: Structure-first grouping preserves section boundaries
- **WHEN** qualifying child chunks share the same chapter and section anchors
- **THEN** the system SHALL group them under the same parent section while they remain within configured bounds

#### Scenario: Oversized structural group is split deterministically
- **WHEN** a structure-derived parent candidate exceeds the configured maximum parent token bound
- **THEN** the system SHALL split the candidate into bounded parent sections using deterministic child-order grouping

#### Scenario: Fallback grouping preserves child order
- **WHEN** weakly structured long-form chunks are grouped by the fallback algorithm
- **THEN** parent construction SHALL preserve the original child chunk order
- **AND** repeated ingestion of the same source version SHALL produce the same child-to-parent mapping

---

### Requirement: Hierarchy decision observability

Every Path B and Path C ingestion run SHALL emit a structured log event describing the hierarchy decision. The event SHALL include whether the document qualified, the qualification reason, whether structure was detected, total tokens, chunk count, parent count, and whether bounded fallback grouping was used.

#### Scenario: Structured qualification emits observable decision
- **WHEN** a long-form document qualifies through structure-first processing
- **THEN** the ingestion logs SHALL include an event describing the hierarchy decision
- **AND** the event SHALL include `qualifies=true`, a structure-first reason, and `fallback_used=false`

#### Scenario: Fallback qualification emits observable decision
- **WHEN** a long-form document qualifies through bounded fallback grouping
- **THEN** the ingestion logs SHALL include an event describing the hierarchy decision
- **AND** the event SHALL include `qualifies=true`, a fallback reason, and `fallback_used=true`

#### Scenario: Flat fallback emits observable decision
- **WHEN** a document does not qualify for hierarchical indexing
- **THEN** the ingestion logs SHALL include an event describing the hierarchy decision
- **AND** the event SHALL include `qualifies=false` and `parent_count=0`
