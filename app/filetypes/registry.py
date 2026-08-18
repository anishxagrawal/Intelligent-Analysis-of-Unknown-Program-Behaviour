"""Dispatch to the first detector that claims the header.

First match wins, and order is therefore meaningful - see
:data:`app.filetypes.detectors.DEFAULT_DETECTORS`. The alternative, asking every
detector and resolving conflicts by score, would mean inventing a comparison
between "this is definitely a PE" and "this looks like a script", and no honest
comparison exists.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.filetypes.base import Detector, FileType
from app.filetypes.detectors import DEFAULT_DETECTORS
from app.logging import get_logger

logger = get_logger(__name__)


class DetectorRegistry:
    """An ordered set of detectors, asked in turn."""

    def __init__(self, detectors: Iterable[Detector] | None = None) -> None:
        self._detectors: tuple[Detector, ...] = tuple(
            DEFAULT_DETECTORS if detectors is None else detectors
        )

    @property
    def detectors(self) -> tuple[Detector, ...]:
        return self._detectors

    def detect(self, header: bytes) -> FileType:
        """Identify the container format, or report that nothing recognised it.

        A detector that raises is logged and skipped rather than allowed to fail
        the submission. Identification is advisory: getting it wrong costs
        Stage 2 some effort, while refusing the upload loses the sample, and the
        sample is the thing that cannot be recreated.
        """
        for detector in self._detectors:
            try:
                if detector.matches(header):
                    return detector.file_type
            except Exception:
                logger.exception(
                    "detector failed",
                    extra={"detector": type(detector).__name__},
                )

        return FileType.UNKNOWN


#: The registry used by the application. One instance; detectors are stateless.
default_registry = DetectorRegistry()


def detect(header: bytes) -> FileType:
    """Identify a header using the default registry."""
    return default_registry.detect(header)
