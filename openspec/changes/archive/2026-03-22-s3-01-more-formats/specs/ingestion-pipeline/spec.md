## ADDED Requirements

### Requirement: Corrupt file contract between parser and worker

When `DoclingParser.parse_and_chunk()` raises an exception due to a corrupt or malformed input file, the ingestion worker SHALL catch the exception and mark the `BackgroundTask` as FAILED with `error_message` containing the exception details. The `Source` record SHALL be marked FAILED. No Document, DocumentVersion, or Chunk records SHALL be created for corrupt files (failure occurs before Tx 1). The worker SHALL NOT retry parsing failures — corrupt input is a deterministic failure.

> **ADDED by S3-01:** This contract was implicit when only MD/TXT were supported (text formats rarely corrupt). With binary formats (PDF, DOCX), corrupt file handling becomes a required explicit contract.

#### Scenario: Corrupt PDF triggers task failure

- **WHEN** the ingestion worker processes a source with a corrupt PDF file
- **AND** `DoclingParser.parse_and_chunk()` raises an exception
- **THEN** the `BackgroundTask` status SHALL be FAILED
- **AND** `BackgroundTask.error_message` SHALL contain a description of the parsing failure
- **AND** the `Source` status SHALL be FAILED
- **AND** no Document, DocumentVersion, or Chunk records SHALL exist for this source

#### Scenario: Corrupt DOCX triggers task failure

- **WHEN** the ingestion worker processes a source with a corrupt DOCX file
- **AND** `DoclingParser.parse_and_chunk()` raises an exception
- **THEN** the `BackgroundTask` status SHALL be FAILED
- **AND** `BackgroundTask.error_message` SHALL contain a description of the parsing failure
- **AND** the `Source` status SHALL be FAILED
- **AND** no Document, DocumentVersion, or Chunk records SHALL exist for this source

#### Scenario: Parsing failure is not retried by the worker

- **WHEN** `DoclingParser.parse_and_chunk()` raises an exception for a corrupt file
- **THEN** the worker SHALL NOT re-enqueue or retry the ingestion task
- **AND** the task SHALL remain in FAILED status as a permanent terminal state

#### Scenario: Worker error message includes exception details

- **WHEN** `DoclingParser` raises an exception with message "Invalid PDF header"
- **THEN** `BackgroundTask.error_message` SHALL contain "Invalid PDF header" or a message that includes the original exception text
