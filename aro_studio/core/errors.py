"""Studio error hierarchy and translation of low-level failures into actionable explanations.

Every error carries a stable ``code``, a human explanation, and a recommended action so the
UI never has to show a bare ``CUDA ERROR`` (spec §36).
"""

from __future__ import annotations

from dataclasses import dataclass


class StudioError(Exception):
    code = "STUDIO_ERROR"
    http_status = 500
    job_state = "FAILED"

    def __init__(self, message: str, *, recommended_action: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.recommended_action = recommended_action
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "recommended_action": self.recommended_action,
            "details": self.details,
        }


class InvalidInputError(StudioError):
    code = "INVALID_INPUT"
    http_status = 400
    job_state = "INVALID_INPUT"


class NotFoundError(StudioError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(StudioError):
    code = "CONFLICT"
    http_status = 409


class SecurityError(StudioError):
    code = "SECURITY_VIOLATION"
    http_status = 400


class UnauthorizedError(StudioError):
    code = "UNAUTHORIZED"
    http_status = 401


class RateLimitedError(StudioError):
    code = "RATE_LIMITED"
    http_status = 429


class ImmutableVersionError(ConflictError):
    code = "IMMUTABLE_VERSION"


class EngineUnavailableError(StudioError):
    """The selected engine cannot run in this environment (missing weights/torch/GPU)."""

    code = "ENGINE_UNAVAILABLE"
    http_status = 503
    job_state = "MODEL_ERROR"


class ModelError(StudioError):
    code = "MODEL_ERROR"
    http_status = 500
    job_state = "MODEL_ERROR"


class ResourceLimitError(StudioError):
    code = "RESOURCE_LIMIT"
    http_status = 507
    job_state = "RESOURCE_LIMIT"


class JobTimeoutError(StudioError):
    code = "TIMEOUT"
    http_status = 504
    job_state = "TIMEOUT"


class JobCancelledError(StudioError):
    code = "CANCELLED"
    http_status = 409
    job_state = "CANCELLED"


class ValidationFailedError(StudioError):
    code = "VALIDATION_FAILED"
    http_status = 422


@dataclass(frozen=True)
class Explanation:
    code: str
    message: str
    recommended_action: str
    job_state: str


def explain_exception(exc: BaseException) -> Explanation:
    """Translate any exception into a plain-language explanation and terminal job state."""
    if isinstance(exc, StudioError):
        return Explanation(
            exc.code, exc.message, exc.recommended_action or "See the job log for details.", exc.job_state
        )
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "out of memory" in low and ("cuda" in low or "cublas" in low or "hip" in low):
        return Explanation(
            "GPU_OUT_OF_MEMORY",
            "Generation failed because available GPU memory was insufficient for the selected configuration.",
            "Use the LOW_RESOURCE preset (smaller marching-cubes grid and chunk size), or retry when the GPU is free.",
            "RESOURCE_LIMIT",
        )
    if isinstance(exc, MemoryError) or "cannot allocate memory" in low or "std::bad_alloc" in low:
        return Explanation(
            "HOST_OUT_OF_MEMORY",
            "The job needed more system memory (RAM) than is available.",
            "Lower the resolution / polygon budget, or run the job when other work has finished.",
            "RESOURCE_LIMIT",
        )
    if "no space left" in low:
        return Explanation(
            "DISK_FULL",
            "The storage volume is full.",
            "Free space by purging cache and deleting unused temporary files from Settings, then retry.",
            "RESOURCE_LIMIT",
        )
    if "cuda" in low and any(k in low for k in ("no kernel image", "driver", "not available", "invalid device")):
        return Explanation(
            "GPU_UNAVAILABLE",
            "The GPU could not be used by the model (driver/CUDA mismatch or no GPU attached).",
            "Switch the device to 'cpu' (slow) or deploy on hardware whose CUDA version matches the installed PyTorch build.",
            "MODEL_ERROR",
        )
    if isinstance(exc, TimeoutError):
        return Explanation(
            "TIMEOUT",
            "The job exceeded its time limit.",
            "Retry with a lighter preset or increase the job timeout in Settings.",
            "TIMEOUT",
        )
    if isinstance(exc, PermissionError):
        return Explanation(
            "PERMISSION_DENIED",
            "The Studio was not allowed to read or write a required file.",
            "Check ARO_DATA_DIR permissions for the user running the Studio.",
            "FAILED",
        )
    return Explanation(
        "UNEXPECTED_ERROR",
        f"An unexpected error occurred: {type(exc).__name__}.",
        "Open the job log for the full traceback; report it if it persists.",
        "FAILED",
    )
