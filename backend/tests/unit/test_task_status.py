from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType


def test_background_task_type_enum_values() -> None:
    assert [member.value for member in BackgroundTaskType] == [
        "INGESTION",
        "BATCH_EMBEDDING",
    ]


def test_background_task_status_enum_values() -> None:
    assert [member.value for member in BackgroundTaskStatus] == [
        "PENDING",
        "PROCESSING",
        "COMPLETE",
        "FAILED",
        "CANCELLED",
    ]
