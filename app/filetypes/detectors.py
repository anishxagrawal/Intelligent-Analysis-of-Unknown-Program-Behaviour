"""One class per format.

Each detector is small enough to read in full, and each carries the signature it
looks for as data. Adding a format means adding a class here and registering it;
no existing detector changes, which is the point of the split.

Signature references are in the comments so a future reader can check a claim
against the specification rather than trusting the constant.
"""

from __future__ import annotations

from app.filetypes.base import Detector, FileType


class PEDetector:
    """Windows PE: EXE, DLL, SYS.

    The DOS stub magic ``MZ`` is checked, and then the ``PE\\0\\0`` signature it
    points at. ``MZ`` alone is not enough: every DOS-era binary starts with it,
    and so does anything that wants to be mistaken for an executable.
    """

    file_type = FileType.PE

    DOS_MAGIC = b"MZ"

    #: Offset of e_lfanew in the DOS header, which holds the offset of the PE
    #: signature. PE/COFF specification, section 2.1.
    E_LFANEW_OFFSET = 0x3C

    def matches(self, header: bytes) -> bool:
        if not header.startswith(self.DOS_MAGIC):
            return False

        if len(header) < self.E_LFANEW_OFFSET + 4:
            # Too short to follow the pointer. A truncated header claiming MZ
            # is reported as PE anyway: refusing would misfile every sample
            # under 64 bytes, and MZ is a deliberate marker, not a coincidence.
            return True

        pe_offset = int.from_bytes(
            header[self.E_LFANEW_OFFSET : self.E_LFANEW_OFFSET + 4], "little"
        )
        if pe_offset + 4 > len(header):
            # The signature lies beyond the header window. Still a PE claim.
            return True

        return header[pe_offset : pe_offset + 4] == b"PE\x00\x00"


class ELFDetector:
    """Linux and BSD executables and shared objects."""

    file_type = FileType.ELF

    #: ELF specification, e_ident: 0x7F followed by "ELF".
    MAGIC = b"\x7fELF"

    def matches(self, header: bytes) -> bool:
        return header.startswith(self.MAGIC)


class MachODetector:
    """macOS executables, thin and fat.

    Included because a submission is whatever somebody uploads, and reporting a
    Mach-O binary as ``unknown`` would be a worse answer than the true one.
    """

    file_type = FileType.MACH_O

    #: 32- and 64-bit, each in both byte orders, plus the universal ("fat")
    #: archive magic.
    MAGICS = (
        b"\xfe\xed\xfa\xce",
        b"\xfe\xed\xfa\xcf",
        b"\xce\xfa\xed\xfe",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
    )

    def matches(self, header: bytes) -> bool:
        return header.startswith(self.MAGICS)


class OLEDetector:
    """Legacy Office documents: .doc, .xls, .ppt, and .msi.

    Formally the Compound File Binary Format. Still a common malware carrier
    because the macro surface predates most of the defences built since.
    """

    file_type = FileType.OLE

    #: Compound File Binary Format specification, section 2.2.
    MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

    def matches(self, header: bytes) -> bool:
        return header.startswith(self.MAGIC)


class PDFDetector:
    """PDF documents."""

    file_type = FileType.PDF

    MAGIC = b"%PDF-"

    def matches(self, header: bytes) -> bool:
        return header.startswith(self.MAGIC)


class OOXMLDetector:
    """Modern Office documents: .docx, .xlsx, .pptx.

    OOXML files are ZIP archives, so this detector has to run before the archive
    detector and has to look past the magic number to tell them apart.

    The discriminator is the first entry in the archive. OOXML writers place
    ``[Content_Types].xml`` first, by specification, so its name appears in the
    first local file header. That is a property of the format rather than a
    heuristic, and it is checked without decompressing anything.

    A crafted archive could of course place that name first without being a real
    OOXML document. The consequence is a misfiled container, not a security
    boundary crossed - nothing here decides whether a file is safe.
    """

    file_type = FileType.OOXML

    ZIP_MAGIC = b"PK\x03\x04"
    CONTENT_TYPES = b"[Content_Types].xml"

    def matches(self, header: bytes) -> bool:
        return header.startswith(self.ZIP_MAGIC) and self.CONTENT_TYPES in header


class ArchiveDetector:
    """Containers that hold other files.

    Registered after the OOXML detector, because every OOXML document is also a
    ZIP and the more specific answer is the more useful one.
    """

    file_type = FileType.ARCHIVE

    MAGICS = (
        b"PK\x03\x04",  # ZIP, and everything built on it
        b"PK\x05\x06",  # empty ZIP
        b"Rar!\x1a\x07",  # RAR
        b"7z\xbc\xaf\x27\x1c",  # 7-Zip
        b"\x1f\x8b",  # gzip
        b"BZh",  # bzip2
        b"\xfd7zXZ\x00",  # xz
    )

    def matches(self, header: bytes) -> bool:
        return header.startswith(self.MAGICS)


class ScriptDetector:
    """Text that something will interpret.

    Scripts have no magic number, which makes this the one detector that has to
    reason rather than compare. It accepts two kinds of evidence:

      * a shebang line, which is an explicit instruction to an interpreter
      * a known marker near the start of an otherwise printable file

    It runs last, so anything with a real signature has already been claimed.
    Anything it is unsure about stays ``unknown``, which is the correct answer
    rather than a failure.
    """

    file_type = FileType.SCRIPT

    SHEBANG = b"#!"

    #: Markers that only appear in files meant to be executed by an interpreter.
    #: Matched case-insensitively against the start of the file.
    MARKERS = (
        b"<?php",
        b"<script",
        b"@echo off",
        b"param(",
        b"function ",
        b"import ",
        b"#requires",
        b"using namespace system",
    )

    def matches(self, header: bytes) -> bool:
        if header.startswith(self.SHEBANG):
            return True
        if not header or not self._is_text(header):
            return False
        return header.lower().lstrip().startswith(self.MARKERS)

    @staticmethod
    def _is_text(header: bytes) -> bool:
        """Whether the header looks like text rather than binary.

        A NUL byte is the giveaway: the text encodings in scope here do not
        contain one, and binary formats almost always do within a few hundred
        bytes.

        Up to three trailing bytes are dropped before decoding, because the
        header is a fixed-size window that can end in the middle of a UTF-8
        sequence. That says nothing about the file.
        """
        if b"\x00" in header:
            return False
        return any(_decodes(header[: len(header) - trim]) for trim in (0, 1, 2, 3))


def _decodes(chunk: bytes) -> bool:
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


#: Registration order is the resolution order, and it is deliberate: specific
#: formats first, then general containers, then the one detector that has to
#: infer. See :class:`OOXMLDetector` and :class:`ScriptDetector`.
DEFAULT_DETECTORS: tuple[Detector, ...] = (
    PEDetector(),
    ELFDetector(),
    MachODetector(),
    OLEDetector(),
    PDFDetector(),
    OOXMLDetector(),
    ArchiveDetector(),
    ScriptDetector(),
)
