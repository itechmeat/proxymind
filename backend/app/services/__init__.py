from importlib import import_module

_EXPORTS = {
    "ChatService": ("app.services.chat", "ChatService"),
    "ChunkData": ("app.services.document_processing", "ChunkData"),
    "DocumentAIParser": ("app.services.document_ai_parser", "DocumentAIParser"),
    "DocumentProcessor": ("app.services.document_processing", "DocumentProcessor"),
    "CollectionSchemaMismatchError": (
        "app.services.qdrant",
        "CollectionSchemaMismatchError",
    ),
    "EmbeddingService": ("app.services.embedding", "EmbeddingService"),
    "FileMetadata": ("app.services.path_router", "FileMetadata"),
    "GeminiContentService": ("app.services.gemini_content", "GeminiContentService"),
    "InvalidRetrievedChunkError": ("app.services.qdrant", "InvalidRetrievedChunkError"),
    "LLMError": ("app.services.llm_types", "LLMError"),
    "LLMResponse": ("app.services.llm_types", "LLMResponse"),
    "LLMService": ("app.services.llm", "LLMService"),
    "NoActiveSnapshotError": ("app.services.chat", "NoActiveSnapshotError"),
    "NO_CONTEXT_REFUSAL": ("app.services.prompt", "NO_CONTEXT_REFUSAL"),
    "PathDecision": ("app.services.path_router", "PathDecision"),
    "QdrantChunkPoint": ("app.services.qdrant", "QdrantChunkPoint"),
    "QdrantService": ("app.services.qdrant", "QdrantService"),
    "RetrievedChunk": ("app.services.qdrant", "RetrievedChunk"),
    "RetrievalError": ("app.services.retrieval", "RetrievalError"),
    "RetrievalService": ("app.services.retrieval", "RetrievalService"),
    "SessionNotFoundError": ("app.services.chat", "SessionNotFoundError"),
    "SnapshotConflictError": ("app.services.snapshot", "SnapshotConflictError"),
    "SnapshotNotFoundError": ("app.services.snapshot", "SnapshotNotFoundError"),
    "SnapshotService": ("app.services.snapshot", "SnapshotService"),
    "SnapshotValidationError": ("app.services.snapshot", "SnapshotValidationError"),
    "SourcePersistenceError": ("app.services.source", "SourcePersistenceError"),
    "SourceService": ("app.services.source", "SourceService"),
    "StorageService": ("app.services.storage", "StorageService"),
    "TaskEnqueueError": ("app.services.source", "TaskEnqueueError"),
    "LightweightParser": ("app.services.lightweight_parser", "LightweightParser"),
    "determine_mime_type": ("app.services.storage", "determine_mime_type"),
    "determine_source_type": ("app.services.storage", "determine_source_type"),
    "validate_file_extension": ("app.services.storage", "validate_file_extension"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attribute_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_EXPORTS))

__all__ = [
    "ChunkData",
    "ChatService",
    "CollectionSchemaMismatchError",
    "EmbeddingService",
    "FileMetadata",
    "GeminiContentService",
    "InvalidRetrievedChunkError",
    "LightweightParser",
    "DocumentAIParser",
    "DocumentProcessor",
    "LLMError",
    "LLMResponse",
    "LLMService",
    "NoActiveSnapshotError",
    "NO_CONTEXT_REFUSAL",
    "PathDecision",
    "QdrantChunkPoint",
    "QdrantService",
    "RetrievedChunk",
    "RetrievalError",
    "RetrievalService",
    "SessionNotFoundError",
    "SnapshotConflictError",
    "SnapshotNotFoundError",
    "SnapshotService",
    "SnapshotValidationError",
    "SourcePersistenceError",
    "SourceService",
    "StorageService",
    "TaskEnqueueError",
    "determine_mime_type",
    "determine_source_type",
    "validate_file_extension",
]
