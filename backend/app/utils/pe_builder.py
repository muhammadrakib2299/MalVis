"""Build a minimal but valid PE32 file in memory.

The output is just enough for `pefile` to parse without errors: DOS stub →
NT signature → file header → optional header (with all 16 data directories
zeroed) → one `.text` section. No imports, no resources, no data.

Used by:
  - Unit tests, to feed the extractor a real PE without shipping a binary
    fixture (per-project policy: no executables in the repo).
  - The samples module (`app/services/samples.py`), to construct the
    "Try a sample" gallery entries deterministically. Same logic, no
    duplication.
"""

from __future__ import annotations

import struct

# COFF / NT constants
IMAGE_DOS_SIGNATURE = 0x5A4D  # "MZ" little-endian → 4D 5A on disk
IMAGE_NT_SIGNATURE = 0x00004550  # "PE\0\0"
IMAGE_FILE_MACHINE_I386 = 0x014C
IMAGE_NT_OPTIONAL_HDR32_MAGIC = 0x10B

NUMBER_OF_DATA_DIRECTORIES = 16
SIZE_OF_OPTIONAL_HEADER_PE32 = 96 + (NUMBER_OF_DATA_DIRECTORIES * 8)  # 224

# Section characteristics: CODE | EXECUTE | READ
IMAGE_SCN_CNT_CODE = 0x00000020
IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000


def build_minimal_pe(
    *,
    machine: int = IMAGE_FILE_MACHINE_I386,
    section_name: bytes = b".text",
    section_payload: bytes = b"\x90" * 64,
) -> bytes:
    """Return bytes for a parseable PE32 with one section.

    `section_payload` is written verbatim and its length is reflected in the
    `.text` section's SizeOfRawData. Useful for tweaking entropy in tests
    (e.g. random bytes → high entropy, zeros → low) and for constructing
    distinctly-shaped sample binaries for the gallery.
    """
    # --- DOS header (64 bytes) -------------------------------------------
    # Only e_magic and e_lfanew matter to pefile; everything else can be 0.
    dos_header = bytearray(64)
    struct.pack_into("<H", dos_header, 0, IMAGE_DOS_SIGNATURE)  # e_magic
    struct.pack_into("<I", dos_header, 60, 64)  # e_lfanew → NT header at 64

    # --- NT signature (4) ------------------------------------------------
    nt_signature = struct.pack("<I", IMAGE_NT_SIGNATURE)

    # --- File header (20) ------------------------------------------------
    file_header = struct.pack(
        "<HHIIIHH",
        machine,  # Machine
        1,  # NumberOfSections
        0,  # TimeDateStamp
        0,  # PointerToSymbolTable
        0,  # NumberOfSymbols
        SIZE_OF_OPTIONAL_HEADER_PE32,  # SizeOfOptionalHeader
        0x0102,  # Characteristics (EXECUTABLE_IMAGE | 32BIT_MACHINE)
    )

    # --- Optional header (PE32, 96 standard bytes) -----------------------
    optional_standard = struct.pack(
        "<HBBIIIIII",
        IMAGE_NT_OPTIONAL_HDR32_MAGIC,  # Magic
        14,  # MajorLinkerVersion
        0,  # MinorLinkerVersion
        len(section_payload),  # SizeOfCode
        0,  # SizeOfInitializedData
        0,  # SizeOfUninitializedData
        0x1000,  # AddressOfEntryPoint
        0x1000,  # BaseOfCode
        0x2000,  # BaseOfData (PE32 only)
    )
    optional_windows = struct.pack(
        "<IIIHHHHHHIIIIHHIIIIII",
        0x00400000,  # ImageBase
        0x1000,  # SectionAlignment
        0x200,  # FileAlignment
        6,  # MajorOSVersion
        0,  # MinorOSVersion
        0,  # MajorImageVersion
        0,  # MinorImageVersion
        6,  # MajorSubsystemVersion
        0,  # MinorSubsystemVersion
        0,  # Win32VersionValue (reserved)
        0x2000,  # SizeOfImage
        0x200,  # SizeOfHeaders
        0,  # CheckSum
        3,  # Subsystem (CONSOLE)
        0x8160,  # DllCharacteristics
        0x100000,  # SizeOfStackReserve
        0x1000,  # SizeOfStackCommit
        0x100000,  # SizeOfHeapReserve
        0x1000,  # SizeOfHeapCommit
        0,  # LoaderFlags
        NUMBER_OF_DATA_DIRECTORIES,  # NumberOfRvaAndSizes
    )
    # 16 data directories, all zero (no imports, no security, etc.)
    data_directories = b"\x00" * (NUMBER_OF_DATA_DIRECTORIES * 8)
    optional_header = optional_standard + optional_windows + data_directories
    assert len(optional_header) == SIZE_OF_OPTIONAL_HEADER_PE32, (
        f"optional header size mismatch: {len(optional_header)}"
    )

    # --- Section header (40) ---------------------------------------------
    name_padded = section_name[:8].ljust(8, b"\x00")
    raw_data_offset = 0x200  # placed right after the headers (file-aligned)
    section_header = struct.pack(
        "<8sIIIIIIHHI",
        name_padded,
        len(section_payload),  # VirtualSize
        0x1000,  # VirtualAddress
        len(section_payload),  # SizeOfRawData
        raw_data_offset,  # PointerToRawData
        0,  # PointerToRelocations
        0,  # PointerToLinenumbers
        0,  # NumberOfRelocations
        0,  # NumberOfLinenumbers
        IMAGE_SCN_CNT_CODE | IMAGE_SCN_MEM_EXECUTE | IMAGE_SCN_MEM_READ,
    )

    headers = bytes(dos_header) + nt_signature + file_header + optional_header + section_header

    # Pad to raw_data_offset, then append the section bytes.
    padded = headers + b"\x00" * (raw_data_offset - len(headers))
    return padded + section_payload
