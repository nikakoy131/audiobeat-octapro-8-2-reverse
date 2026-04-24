"""Logging setup: Rich console handler + JSONL research file sink.

Usage:
    from octapro.logging import setup_logging, warn_unknown, research
"""

import json
import logging
import os
import platform
import struct
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

_console = Console(stderr=True)
_research_lock = threading.Lock()
_research_path: Path | None = None
_research_fh: Any = None

log = logging.getLogger("octapro")


def default_research_log_path() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Logs" / "octapro" / "research.jsonl"
    xdg = os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))
    return Path(xdg) / "octapro" / "research.jsonl"


def setup_logging(
    verbose: bool = False,
    quiet: bool = False,
    log_file: Path | None = None,
) -> None:
    global _research_path, _research_fh

    level = logging.DEBUG if verbose else (logging.WARNING if quiet else logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, rich_tracebacks=True, show_path=False)],
    )

    _research_path = log_file or default_research_log_path()
    _research_path.parent.mkdir(parents=True, exist_ok=True)
    _research_fh = _research_path.open("a", encoding="utf-8")


def _write_research(event: dict[str, Any]) -> None:
    if _research_fh is None:
        return
    event.setdefault("ts", datetime.now(UTC).isoformat())
    with _research_lock:
        _research_fh.write(json.dumps(event) + "\n")
        _research_fh.flush()


def research(kind: str, **fields: Any) -> None:
    """Write a structured event to the research JSONL log."""
    _write_research({"kind": kind, **fields})


def warn_unknown(kind: str, observed: Any, context: str = "") -> None:
    """Log a decode warning both to the console and the research JSONL file."""
    suffix = f"  -> {_research_path}" if _research_path else ""
    ctx = f" ({context})" if context else ""
    log.warning("UNKNOWN %s=%r%s%s", kind, observed, ctx, suffix)
    _write_research({
        "kind": "decode_note",
        "type": kind,
        "observed": str(observed),
        "context": context,
    })


def log_packet_out(cmd: int, addr: int, sub: int, pkt: bytes) -> None:
    research(
        "packet_out",
        cmd=f"0x{cmd:02x}",
        addr=f"0x{addr:04x}",
        sub=f"0x{sub:04x}",
        hex=pkt.hex(),
    )
    log.debug("OUT cmd=0x%02x addr=0x%04x sub=0x%04x  %s…", cmd, addr, sub, pkt[:16].hex())


def log_packet_in(pkt: bytes) -> None:
    status = struct.unpack_from("<H", pkt, 0)[0] if len(pkt) >= 2 else 0
    research("packet_in", status=f"0x{status:04x}", hex=pkt.hex())
    log.debug("IN  status=0x%04x  %s…", status, pkt[:16].hex())
