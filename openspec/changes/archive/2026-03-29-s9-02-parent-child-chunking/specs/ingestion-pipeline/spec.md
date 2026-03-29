## ADDED Requirements

### Requirement: Hierarchical ingestion for qualifying Path B and Path C documents

For story S9-02, the ingestion pipeline SHALL derive and persist parent sections for qualifying Path B and Path C documents after child chunking and before embedding/indexing. The hierarchy stage SHALL operate on the normalized child chunks and SHALL leave Path A unchanged.

#### Scenario: Path B persists hierarchy before embedding
- **WHEN** a qualifying long-form source is routed to Path B
- **THEN** the handler SHALL construct parent sections after child chunking and before embedding begins
- **AND** parent rows and child `parent_id` links SHALL be persisted before any Qdrant upsert occurs

#### Scenario: Path C persists hierarchy before embedding
- **WHEN** a qualifying long-form source is routed to Path C
- **THEN** the handler SHALL construct parent sections after normalized Document AI chunking and before embedding begins
- **AND** parent rows and child `parent_id` links SHALL be persisted before any Qdrant upsert occurs

#### Scenario: Path A remains unchanged
- **WHEN** a source is routed to Path A
- **THEN** the ingestion pipeline SHALL NOT attempt parent-child hierarchy construction
- **AND** Path A SHALL keep the existing single-chunk behavior

---

### Requirement: Flat fallback remains a real working path

If a Path B or Path C document does not qualify for hierarchical indexing, ingestion SHALL continue through the existing flat chunking pipeline without creating parent sections, without changing child ordering, and without changing retrieval eligibility.

#### Scenario: Non-qualifying Path B source stays on the flat pipeline
- **WHEN** a Path B source does not meet long-form thresholds
- **THEN** ingestion SHALL persist the child chunks exactly as the flat pipeline would
- **AND** no parent rows or child parent links SHALL be created

#### Scenario: Non-qualifying Path C source stays on the flat pipeline
- **WHEN** a Path C source does not meet long-form thresholds
- **THEN** ingestion SHALL persist the child chunks exactly as the flat pipeline would
- **AND** no parent rows or child parent links SHALL be created

---

### Requirement: Qualifying hierarchy failures fail closed

Once a Path B or Path C document has qualified for hierarchical indexing, hierarchy construction and parent persistence become part of the required ingestion contract for that document version. If hierarchy construction fails after qualification, or if parent persistence/linking cannot be completed consistently, the ingestion run SHALL fail closed rather than silently degrading the qualifying document back to flat chunking.

#### Scenario: Hierarchy construction failure after qualification fails the ingestion run
- **WHEN** a Path B or Path C document qualifies for hierarchical indexing
- **AND** parent construction fails before persistence completes
- **THEN** the ingestion run SHALL fail
- **AND** the document SHALL NOT be silently re-routed to the flat path for that run

#### Scenario: Parent persistence failure after qualification fails the ingestion run
- **WHEN** a Path B or Path C document qualifies for hierarchical indexing
- **AND** parent rows or child-to-parent links cannot be persisted consistently
- **THEN** the ingestion run SHALL fail
- **AND** the failure SHALL be visible through the existing ingestion task failure path and logs
