"""Shared enumerations: job states, asset status, pipeline stages, severities."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


class JobState(StrEnum):
    # Spec §44 generic lifecycle
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    # Spec §11 generation lifecycle
    INITIALIZING = "INITIALIZING"
    PREPROCESSING = "PREPROCESSING"
    GENERATING = "GENERATING"
    POSTPROCESSING = "POSTPROCESSING"
    VALIDATING = "VALIDATING"
    PROCESSING = "PROCESSING"  # generic non-generation work
    COMPLETED = "COMPLETED"
    # Failure states
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    MODEL_ERROR = "MODEL_ERROR"
    INVALID_INPUT = "INVALID_INPUT"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_JOB_STATES

    @property
    def is_failure(self) -> bool:
        return self in TERMINAL_JOB_STATES and self is not JobState.COMPLETED and self is not JobState.CANCELLED


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.TIMEOUT,
        JobState.RESOURCE_LIMIT,
        JobState.MODEL_ERROR,
        JobState.INVALID_INPUT,
    }
)

# Active states a generation job passes through, in order, with a progress floor (0..1).
GENERATION_STAGE_ORDER = [
    JobState.QUEUED,
    JobState.INITIALIZING,
    JobState.PREPROCESSING,
    JobState.GENERATING,
    JobState.POSTPROCESSING,
    JobState.VALIDATING,
    JobState.COMPLETED,
]


class AssetStatus(StrEnum):
    DRAFT = "DRAFT"
    GENERATING = "GENERATING"
    PROCESSING = "PROCESSING"
    VALIDATING = "VALIDATING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    PRODUCTION_READY = "PRODUCTION_READY"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


class Stage(StrEnum):
    """Storage stages (spec §12). RAW is never modified after it is written."""

    RAW = "raw"
    PROCESSED = "processed"
    OPTIMIZED = "optimized"
    FINAL = "final"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"
    NOT_APPLICABLE = "not_applicable"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"
