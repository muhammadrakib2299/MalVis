"""Backwards-compatible re-export. The real implementation now lives in
`app.utils.pe_builder` so production code (the samples module) and tests
share one definition. Tests import from here so existing test files don't
need to change.
"""

from app.utils.pe_builder import (  # noqa: F401
    IMAGE_DOS_SIGNATURE,
    IMAGE_FILE_MACHINE_I386,
    IMAGE_NT_OPTIONAL_HDR32_MAGIC,
    IMAGE_NT_SIGNATURE,
    IMAGE_SCN_CNT_CODE,
    IMAGE_SCN_MEM_EXECUTE,
    IMAGE_SCN_MEM_READ,
    NUMBER_OF_DATA_DIRECTORIES,
    SIZE_OF_OPTIONAL_HEADER_PE32,
    build_minimal_pe,
)
