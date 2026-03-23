from enum import StrEnum

from sqlalchemy import Enum


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


def pg_enum(enum_class: type[StrEnum], *, name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=_enum_values,
    )


class CatalogItemType(StrEnum):
    BOOK = "book"
    COURSE = "course"
    EVENT = "event"
    MERCH = "merch"
    OTHER = "other"


class SourceType(StrEnum):
    MARKDOWN = "markdown"
    TXT = "txt"
    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class SourceStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentVersionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ProcessingPath(StrEnum):
    PATH_A = "path_a"
    PATH_B = "path_b"


class ChunkStatus(StrEnum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class SnapshotStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ACTIVE = "active"
    ARCHIVED = "archived"


class TaskType(StrEnum):
    RETRIEVAL = "retrieval"
    QUERY = "query"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class SessionChannel(StrEnum):
    WEB = "web"
    API = "api"
    TELEGRAM = "telegram"
    FACEBOOK = "facebook"
    VK = "vk"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(StrEnum):
    RECEIVED = "received"
    STREAMING = "streaming"
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class BatchOperationType(StrEnum):
    EMBEDDING = "embedding"
    TEXT_EXTRACTION = "text_extraction"
    REINDEX = "reindex"
    EVAL = "eval"


class BatchStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BackgroundTaskType(StrEnum):
    INGESTION = "INGESTION"
    BATCH_EMBEDDING = "BATCH_EMBEDDING"


class BackgroundTaskStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
