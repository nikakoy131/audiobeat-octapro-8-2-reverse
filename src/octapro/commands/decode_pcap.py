"""Offline USB capture decoder. Requires tshark in PATH."""

import json
import logging
import struct
import subprocess
from pathlib import Path

log = logging.getLogger("octapro.decode_pcap")


def run_decode_pcap(pcapng: Path, out: Path | None = None) -> int:
    from rich.console import Console

    from octapro.logging import research, warn_unknown
    from octapro.protocol.constants import KNOWN_CMDS, KNOWN_STATUSES

    console = Console()

    if not pcapng.exists():
        log.error("File not found: %s", pcapng)
        return 1

    try:
        result = subprocess.run(
            [
                "tshark", "-r", str(pcapng),
                "-Y", "usb.capdata",
                "-T", "fields",
                "-e", "frame.number",
                "-e", "usb.endpoint_address.direction",
                "-e", "usb.capdata",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        log.error("tshark not found — install Wireshark/tshark to use this command")
        return 1
    except subprocess.TimeoutExpired:
        log.error("tshark timed out after 120 s")
        return 1

    if result.returncode != 0:
        log.error("tshark error: %s", result.stderr.strip())
        return 1

    events: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3 or not parts[2]:
            continue
        frame_num_str, direction_str, capdata = parts[0], parts[1], parts[2]
        raw = bytes.fromhex(capdata.replace(":", ""))
        ev = _decode_packet(int(frame_num_str), direction_str, raw)
        events.append(ev)

        # Warn on unknowns
        if ev["direction"] == "OUT":
            cmd = int(ev.get("cmd", "0xff"), 16)
            if cmd not in KNOWN_CMDS:
                warn_unknown("cmd", ev["cmd"], f"frame {frame_num_str}")
        else:
            status = int(ev.get("status", "0xffff"), 16)
            if status not in KNOWN_STATUSES:
                warn_unknown("in_status", ev["status"], f"frame {frame_num_str}")

        _print_event(console, ev)

    research("pcap_decode", file=str(pcapng), events=len(events))
    log.info("Decoded %d frames from %s", len(events), pcapng.name)

    if out:
        out.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        log.info("Events written to %s", out)

    return 0


def _decode_packet(frame: int, direction_str: str, raw: bytes) -> dict:
    is_out = direction_str == "0"
    ev: dict = {"frame": frame, "direction": "OUT" if is_out else "IN", "len": len(raw)}

    if is_out and len(raw) >= 13:
        ev["magic"] = raw[0:2].hex()
        ev["cmd"] = f"0x{raw[2]:02x}"
        ev["addr"] = f"0x{struct.unpack_from('<H', raw, 4)[0]:04x}"
        ev["sub"] = f"0x{struct.unpack_from('<H', raw, 6)[0]:04x}"
        ev["csum"] = f"0x{raw[8]:02x}"
    elif not is_out and len(raw) >= 4:
        ev["status"] = f"0x{struct.unpack_from('<H', raw, 0)[0]:04x}"
        ev["magic"] = raw[2:4].hex()

    ev["hex_head"] = raw[:16].hex()
    return ev


def _print_event(console, ev: dict) -> None:
    frame = ev["frame"]
    if ev["direction"] == "OUT":
        console.print(
            f"  #{frame:4d} OUT  cmd={ev.get('cmd','?')} "
            f"addr={ev.get('addr','?')} sub={ev.get('sub','?')} "
            f"csum={ev.get('csum','?')}  {ev['hex_head']}…"
        )
    else:
        console.print(
            f"  #{frame:4d} IN   status={ev.get('status','?')} "
            f"magic={ev.get('magic','?')}  {ev['hex_head']}…"
        )
