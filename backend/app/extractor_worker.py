"""Standalone PE extractor worker.

Reads raw PE bytes from stdin, parses them in-process, writes a single
line of JSON to stdout, exits.

Wire protocol (deliberately tiny so this can run in a sandbox container
with --network=none --read-only):

  stdin   : raw PE bytes (binary, no length prefix — read until EOF)
  stdout  : exactly one JSON document
  exit 0  : success; stdout is `{"ok": true, "features": {...}}`
  exit 2  : parse failure; stdout is `{"ok": false, "error": "..."}`
  exit 3  : system / unexpected failure; stdout is `{"ok": false, "error": "..."}`

The worker is designed to be invoked two ways:

  1. As a subprocess of the API process (`SubprocessExtractor`), giving
     OS-level isolation today. setrlimit + timeout enforced by the caller.
  2. As the entrypoint of a separate, locked-down container (per
     SECURITY.md): --network=none --read-only --cap-drop=all --user=10001
     --memory=512m --cpus=1 --ulimit ... — all enforced by the
     orchestrator, not by this script.

This script never writes to disk, never touches the network, and refuses
to import anything beyond `pefile` and stdlib. Adding more imports here
is a security regression — keep it tight.
"""

from __future__ import annotations

import json
import sys


def _emit(payload: dict, exit_code: int) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")))
    sys.stdout.flush()
    sys.exit(exit_code)


def main() -> None:
    # `sys.stdin.buffer` is the raw bytes channel — `sys.stdin` would
    # decode and corrupt arbitrary binary content.
    try:
        data = sys.stdin.buffer.read()
    except Exception as exc:  # last-resort safety net at the IPC boundary
        _emit({"ok": False, "error": f"stdin read failed: {exc!s}"}, 3)

    if not data:
        _emit({"ok": False, "error": "no input received"}, 2)

    # Local import: keeps the worker startup cheap and confines the
    # `pefile` blast radius to this process when run as a sidecar.
    # Local import — keeps the worker startup cheap and confines the
    # `pefile` blast radius to this process when run as a sidecar.
    from app.services.pe_features import PEParseError, extract_features

    try:
        features = extract_features(data)
    except PEParseError as exc:
        _emit({"ok": False, "error": f"pe_parse_error: {exc!s}"}, 2)
    except Exception as exc:  # last-resort safety net
        _emit({"ok": False, "error": f"unexpected: {type(exc).__name__}"}, 3)

    _emit({"ok": True, "features": features.to_dict()}, 0)


if __name__ == "__main__":
    main()
