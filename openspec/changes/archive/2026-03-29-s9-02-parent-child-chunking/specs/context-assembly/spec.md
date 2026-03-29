## ADDED Requirements

### Requirement: Child plus parent prompt units

For story S9-02, the `ContextAssembler` SHALL treat each qualifying retrieved result as a hierarchical prompt unit consisting of child evidence plus optional parent context. The matched child SHALL remain the exact grounding unit while the parent text SHALL provide broader section context.

#### Scenario: Prompt includes child and parent for a hierarchical result
- **WHEN** the assembler receives a retrieved child chunk with parent metadata
- **THEN** the generated knowledge context SHALL include the matched child text
- **AND** it SHALL include the associated parent text in the same prompt unit

#### Scenario: Prompt includes child only for a flat result
- **WHEN** the assembler receives a retrieved chunk without parent metadata
- **THEN** the generated knowledge context SHALL include only the child text and existing child anchors

---

### Requirement: Shared-parent deduplication

If multiple selected child chunks share the same parent section, the `ContextAssembler` SHALL include the shared parent text once while preserving each selected child as a separate grounding unit. Parent deduplication SHALL apply before retrieval context budget trimming is finalized.

#### Scenario: Two child hits from the same parent share one parent block
- **WHEN** two selected child chunks reference the same parent section
- **THEN** the assembled knowledge context SHALL include the parent text once
- **AND** both child excerpts SHALL remain present as separate evidence units

#### Scenario: Retrieval budget preserves child evidence first
- **WHEN** adding parent context would exceed the retrieval context budget
- **THEN** the assembler SHALL prefer keeping the matched child evidence
- **AND** it MAY truncate or omit additional parent context according to the hierarchy-aware budget policy
