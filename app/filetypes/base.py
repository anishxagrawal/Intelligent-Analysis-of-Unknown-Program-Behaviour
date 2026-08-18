"""What a file type detector is.

Two rules shape everything in this package, and both are about honesty rather
than coverage.

**The extension is never consulted.** It is attacker-controlled text. A sample
named ``invoice.pdf`` that begins with ``MZ`` is a PE executable, and calling it
a PDF because of its name is how a analysis pipeline gets pointed at the wrong
tooling by whoever submitted the file.

**Nothing is guessed.** A file that matches no detector is recorded as
``unknown``, not as the closest thing. "We do not know" is a usable answer -
downstream code can route it to a human, or to a broader detector added later.
A wrong answer is not usable, and worse, it looks like knowledge.

Detection reads a fixed-size header and nothing else. It runs on every
submission, it must not depend on having the whole file in memory, and a format
that cannot be recognised from its first few hundred bytes is a format this
package declines to claim.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

#: How many leading bytes detectors are given. Large enough for the ZIP local
#: header plus its first entry name, which is the deepest look any detector
#: here needs; small enough to hold in memory for every request without
#: thinking about it.
HEADER_SIZE = 512


class FileType(StrEnum):
    """Container formats this system recognises.

    Container, not behaviour. ``pe`` says the bytes are a Windows executable
    image; it says nothing about what that executable does. Stage 1 identifies
    the envelope so Stage 2 knows which tools to reach for, and stops there.
    """

    PE = "pe"
    ELF = "elf"
    MACH_O = "mach_o"
    SCRIPT = "script"
    OLE = "ole"
    OOXML = "ooxml"
    ARCHIVE = "archive"
    PDF = "pdf"

    #: No detector claimed it. Deliberately a real value rather than null, so
    #: "nothing recognised this" is distinguishable from "detection never ran".
    UNKNOWN = "unknown"


@runtime_checkable
class Detector(Protocol):
    """Recognises one container format from a file header."""

    #: What this detector reports when it matches.
    file_type: FileType

    def matches(self, header: bytes) -> bool:
        """Whether ``header`` begins a file of this type.

        Must tolerate a short or empty header, because an empty upload reaches
        here like any other.
        """
        ...
