"""File type detection.

Every sample here is synthesised from a signature rather than taken from a real
binary. That is deliberate: the tests describe what the detectors claim to look
for, and a real executable in the repository would be both larger and harder to
reason about - and, for a malware project, a bad habit to start.
"""

from __future__ import annotations

import pytest

from app.filetypes.base import HEADER_SIZE, FileType
from app.filetypes.detectors import DEFAULT_DETECTORS, PEDetector, ScriptDetector
from app.filetypes.registry import DetectorRegistry, detect

pytestmark = pytest.mark.unit


def pe_bytes(body: bytes = b"") -> bytes:
    """A minimal but structurally honest PE: DOS stub, e_lfanew, PE signature."""
    header = bytearray(b"MZ" + b"\x90" * 62)
    pe_offset = 64
    header[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    return bytes(header) + b"PE\x00\x00" + body


def zip_bytes(first_entry: bytes) -> bytes:
    """A ZIP local file header naming its first entry."""
    return b"PK\x03\x04" + b"\x14\x00\x00\x00\x08\x00" + b"\x00" * 16 + first_entry


# -- Individual formats ----------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (pe_bytes(), FileType.PE),
        (b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 40, FileType.ELF),
        (b"\xcf\xfa\xed\xfe" + b"\x00" * 40, FileType.MACH_O),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 40, FileType.OLE),
        (b"%PDF-1.7\n1 0 obj\n", FileType.PDF),
        (zip_bytes(b"[Content_Types].xml"), FileType.OOXML),
        (zip_bytes(b"payload.txt"), FileType.ARCHIVE),
        (b"Rar!\x1a\x07\x00" + b"\x00" * 20, FileType.ARCHIVE),
        (b"7z\xbc\xaf\x27\x1c" + b"\x00" * 20, FileType.ARCHIVE),
        (b"\x1f\x8b\x08\x00" + b"\x00" * 20, FileType.ARCHIVE),
        (b"#!/bin/sh\necho hello\n", FileType.SCRIPT),
        (b"#!/usr/bin/env python3\nprint(1)\n", FileType.SCRIPT),
        (b"<?php system($_GET['c']); ?>", FileType.SCRIPT),
        (b"@echo off\r\ndel /q C:\\\r\n", FileType.SCRIPT),
    ],
)
def test_known_signatures_are_recognised(payload: bytes, expected: FileType) -> None:
    assert detect(payload) is expected


def test_ooxml_wins_over_archive() -> None:
    """Every OOXML document is a ZIP; the more specific answer is more useful."""
    assert detect(zip_bytes(b"[Content_Types].xml")) is FileType.OOXML


def test_mz_without_a_pe_signature_is_still_pe() -> None:
    """MZ is a deliberate marker, not a coincidence, even when truncated."""
    assert detect(b"MZ") is FileType.PE


def test_mz_pointing_at_something_else_is_not_claimed_blindly() -> None:
    """A full header whose signature is wrong is not a PE, and is not guessed at."""
    header = bytearray(b"MZ" + b"\x90" * 62)
    header[0x3C:0x40] = (64).to_bytes(4, "little")
    payload = bytes(header) + b"NOPE"

    assert detect(payload) is FileType.UNKNOWN


# -- Refusing to guess -----------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\x00" * 64,
        b"just some prose with no signature at all",
        b"\xde\xad\xbe\xef" * 16,
    ],
)
def test_unrecognised_content_is_unknown(payload: bytes) -> None:
    """AC-07. Not the closest guess: "we do not know" is the honest answer."""
    assert detect(payload) is FileType.UNKNOWN


def test_unknown_is_a_value_not_a_null() -> None:
    """So "nothing recognised this" stays distinct from "detection never ran"."""
    assert FileType.UNKNOWN.value == "unknown"


def test_binary_content_is_never_called_a_script() -> None:
    """A NUL byte rules out the text encodings scripts are written in."""
    assert detect(b"import os\x00\x00\x00" + b"\xff" * 32) is not FileType.SCRIPT


def test_a_truncated_utf8_character_does_not_disqualify_text() -> None:
    """The header is a fixed window and can end mid-character."""
    payload = ("#!/bin/sh\n# " + "\u00e9" * HEADER_SIZE).encode("utf-8")[:HEADER_SIZE]

    assert detect(payload) is FileType.SCRIPT


# -- The registry ----------------------------------------------------------


def test_detectors_are_asked_in_registration_order() -> None:
    """First match wins, so order is meaning, not style."""
    registry = DetectorRegistry()

    types = [detector.file_type for detector in registry.detectors]

    assert types.index(FileType.OOXML) < types.index(FileType.ARCHIVE)
    assert types.index(FileType.SCRIPT) == len(types) - 1


def test_every_default_detector_declares_a_type() -> None:
    for detector in DEFAULT_DETECTORS:
        assert isinstance(detector.file_type, FileType)
        assert detector.file_type is not FileType.UNKNOWN


def test_a_failing_detector_does_not_lose_the_submission() -> None:
    """Identification is advisory. The sample is the thing that cannot be recreated."""

    class Exploding:
        file_type = FileType.PE

        def matches(self, header: bytes) -> bool:
            raise RuntimeError("detector is broken")

    registry = DetectorRegistry([Exploding(), ScriptDetector()])

    assert registry.detect(b"#!/bin/sh\n") is FileType.SCRIPT


def test_a_custom_registry_replaces_the_defaults() -> None:
    registry = DetectorRegistry([PEDetector()])

    assert registry.detect(pe_bytes()) is FileType.PE
    assert registry.detect(b"\x7fELF") is FileType.UNKNOWN
