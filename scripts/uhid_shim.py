#!/usr/bin/env python3
"""Fake the OctaPro's interface-4 HID device via Linux /dev/uhid, so the
vendor Windows app (under wine) connects to us instead of real hardware.

See docs/LINUX_UHID_SHIM_PLAN.md for the full plan and rationale. In short:
the real device's DSP interface has no USB endpoints (all traffic is HID
control transfers), and we want to capture the exact packet the app sends
when the user drags the Main-volume fader -- a write we've never seen and
don't want to guess at again by probing the live device.

This script:
  1. Creates a virtual HID device via UHID_CREATE2 with the real device's
     VID/PID and interface-4 report descriptor (docs/iface4_report_descriptor.bin).
  2. Replays known request/response pairs from docs/replay_table.json (built
     by scripts/build_replay_table.py from the real captures) so the app's
     handshake, keepalive, and channel readback all succeed and it reaches
     "Connected".
  3. For writes we actually understand (currently: master volume, CMD 0x08
     SUB 0x0c -- see PROTOCOL.md), patches the live replayed state so later
     reads reflect what was written instead of a stale captured snapshot --
     e.g. dragging the Main fader no longer "snaps back". Anything we don't
     understand yet still gets a generic ack and is logged as UNMATCHED, so
     the log remains useful for decoding the next command (mute, EQ, source
     switch, ...).

Usage (needs root, or a udev rule granting access to /dev/uhid):
    sudo uv run python scripts/uhid_shim.py
    # in another terminal: run the app under wine, drag the Main fader,
    # then check .analysis/uhid_shim.log (or this terminal's stdout) for
    # UNMATCHED lines.

Ctrl-C sends UHID_DESTROY and exits cleanly.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from pair_pcap_requests_responses import MAGIC, classify_out  # noqa: E402

UHID_DEV = "/dev/uhid"
REPORT_DESCRIPTOR_PATH = REPO_ROOT / "docs" / "iface4_report_descriptor.bin"
REPLAY_TABLE_PATH = REPO_ROOT / "docs" / "replay_table.json"
LOG_PATH = REPO_ROOT / ".analysis" / "uhid_shim.log"

VID = 0x8888
PID = 0x1234
DEVICE_NAME = b"Car DSP AMP"
BUS_USB = 0x03

HID_MAX_DESCRIPTOR_SIZE = 4096
UHID_DATA_MAX = 4096

# Event-type enum, order fixed by `enum uhid_event_type` in <linux/uhid.h>.
(
    UHID_LEGACY_CREATE,
    UHID_DESTROY,
    UHID_START,
    UHID_STOP,
    UHID_OPEN,
    UHID_CLOSE,
    UHID_OUTPUT,
    UHID_LEGACY_OUTPUT_EV,
    UHID_LEGACY_INPUT,
    UHID_GET_REPORT,
    UHID_GET_REPORT_REPLY,
    UHID_CREATE2,
    UHID_INPUT2,
    UHID_SET_REPORT,
    UHID_SET_REPORT_REPLY,
) = range(15)

ACK_SHORT = bytes([0x02, 0x00, 0xEE, 0xBB]) + bytes(252)  # generic "ee bb" ack, 256B

# Windows/wine HID stacks prepend a report-ID byte (0x00, since our descriptor
# declares no report IDs) to every Set/GetOutputReport buffer. The real
# device -- and every signature in docs/replay_table.json, built from raw
# USB captures -- never has this prefix. Every request must be de-framed
# before matching, or every signature lookup silently misses.
KEEPALIVE_SIG = "04:00b0:a515"     # CMD 0x04 WRITE_PARAM keepalive echo
MASTER_READ_SIG = "05:00b0:0004"   # CMD 0x05 READ_BLOCK master/CH0
MASTER_VOLUME_ADDR = bytes([0xB7, 0x00])  # channel_addr(0), LE
MASTER_VOLUME_SUB_BYTE = 0x0C
MUTE_SUB_BYTE_MASTER = 0x0D   # CMD 0x05 byte[6] for master mute; byte[7]=1/0
MUTE_SUB_BYTE_CHANNEL = 0x01  # CMD 0x05 byte[6] for per-channel mute
PHASE_SUB_BYTE = 0x02         # CMD 0x05 byte[6] for per-channel phase invert
BRIDGE_SUB_BYTE = 0x28        # CMD 0x1c byte[6] for CH7+CH8 bridge (state in byte[19])

# Absolute byte offsets in the 256B IN response (8B header + data offset,
# per src/octapro/protocol/channel.py / packet.py parse_keepalive_knob_vol).
KEEPALIVE_VOLUME_OFFSET = 12   # float32 LE
KEEPALIVE_CHECKSUM_OFFSET = 16
MASTER_BLOCK_VOLUME_OFFSET = 8 + 9  # header(8) + MASTER_VOLUME_OFFSET(9)


def _split_report_id(data: bytes) -> tuple[int, bytes]:
    """Return (prefix_len, normalized_256B_payload) for a raw uhid buffer.

    prefix_len is informational only (logged) -- replies are always sent as
    a flat 256 bytes; wine's extra leading report-ID byte on writes does not
    need to be mirrored back on reads (see commit discussion in shim log
    history: mirroring it broke the connection handshake).
    """
    if len(data) >= 2 and data[0:2] == MAGIC:
        return 0, data[:256].ljust(256, b"\x00")
    if len(data) >= 3 and data[1:3] == MAGIC:
        return 1, data[1:257].ljust(256, b"\x00")
    return 0, data[:256].ljust(256, b"\x00")  # unrecognized framing, best effort


# ---------------------------------------------------------------------------
# ctypes mirror of <linux/uhid.h> (all structs are __attribute__((packed)))
# ---------------------------------------------------------------------------

class uhid_create2_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("name", ctypes.c_uint8 * 128),
        ("phys", ctypes.c_uint8 * 64),
        ("uniq", ctypes.c_uint8 * 64),
        ("rd_size", ctypes.c_uint16),
        ("bus", ctypes.c_uint16),
        ("vendor", ctypes.c_uint32),
        ("product", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("country", ctypes.c_uint32),
        ("rd_data", ctypes.c_uint8 * HID_MAX_DESCRIPTOR_SIZE),
    ]


class uhid_input2_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * UHID_DATA_MAX),
    ]


class uhid_output_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("data", ctypes.c_uint8 * UHID_DATA_MAX),
        ("size", ctypes.c_uint16),
        ("rtype", ctypes.c_uint8),
    ]


class uhid_get_report_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("rnum", ctypes.c_uint8),
        ("rtype", ctypes.c_uint8),
    ]


class uhid_get_report_reply_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("err", ctypes.c_uint16),
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * UHID_DATA_MAX),
    ]


class uhid_set_report_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("rnum", ctypes.c_uint8),
        ("rtype", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_uint8 * UHID_DATA_MAX),
    ]


class uhid_set_report_reply_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("id", ctypes.c_uint32),
        ("err", ctypes.c_uint16),
    ]


class uhid_start_req(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("dev_flags", ctypes.c_uint64)]


class uhid_event_union(ctypes.Union):
    _pack_ = 1
    _fields_ = [
        ("create2", uhid_create2_req),
        ("input2", uhid_input2_req),
        ("output", uhid_output_req),
        ("get_report", uhid_get_report_req),
        ("get_report_reply", uhid_get_report_reply_req),
        ("set_report", uhid_set_report_req),
        ("set_report_reply", uhid_set_report_reply_req),
        ("start", uhid_start_req),
    ]


class uhid_event(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("u", uhid_event_union),
    ]


EVENT_SIZE = ctypes.sizeof(uhid_event)


def _set_bytes(field: ctypes.Array, data: bytes) -> None:
    ctypes.memmove(field, data, min(len(data), len(field)))


# ---------------------------------------------------------------------------
# Replay table
# ---------------------------------------------------------------------------

class ReplayTable:
    def __init__(self, path: Path):
        raw = json.loads(path.read_text())
        self.by_sig = {k: bytes.fromhex(v) for k, v in raw["by_signature"].items()}


# ---------------------------------------------------------------------------
# Shim
# ---------------------------------------------------------------------------

class UhidShim:
    def __init__(
        self, device_path: str, report_descriptor: bytes, table: ReplayTable, log_path: Path
    ):
        self.table = table
        # Mutable per-signature response state, seeded from the static replay
        # table. Writes we understand (currently: master volume) patch this
        # in place, so later reads reflect what was actually written instead
        # of replaying a stale captured snapshot.
        self.live: dict[str, bytearray] = {
            sig: bytearray(resp) for sig, resp in table.by_sig.items()
        }
        self.last_response = bytes(256)
        try:
            self.fd = os.open(device_path, os.O_RDWR)
        except OSError as e:
            raise SystemExit(
                f"cannot open {device_path}: {e}. Run with sudo, or add a udev "
                f"rule granting your user access to /dev/uhid."
            ) from e
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = log_path.open("a")
        self._create(report_descriptor)

    def _write_event(self, ev: uhid_event) -> None:
        os.write(self.fd, ctypes.string_at(ctypes.addressof(ev), ctypes.sizeof(ev)))

    def _create(self, rd: bytes) -> None:
        ev = uhid_event()
        ev.type = UHID_CREATE2
        c = ev.u.create2
        _set_bytes(c.name, DEVICE_NAME)
        c.rd_size = len(rd)
        c.bus = BUS_USB
        c.vendor = VID
        c.product = PID
        c.version = 0
        c.country = 0
        _set_bytes(c.rd_data, rd)
        self._write_event(ev)
        self._log(f"CREATE2 sent (rd_size={len(rd)}, vid=0x{VID:04x}, pid=0x{PID:04x})")

    def destroy(self) -> None:
        ev = uhid_event()
        ev.type = UHID_DESTROY
        try:
            self._write_event(ev)
        except OSError:
            pass
        os.close(self.fd)
        self._log("DESTROY sent, fd closed")
        self.log_file.close()

    def _log(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        self.log_file.write(line + "\n")
        self.log_file.flush()

    def _send_input2(self, payload: bytes) -> None:
        ev = uhid_event()
        ev.type = UHID_INPUT2
        ev.u.input2.size = len(payload)
        _set_bytes(ev.u.input2.data, payload)
        self._write_event(ev)

    def _lookup(self, payload: bytes) -> tuple[bytes, bool]:
        """Return (response, matched) for a de-framed 256B OUT payload."""
        if len(payload) < 8:
            return ACK_SHORT, False
        cmd, addr, sub, _name = classify_out(payload)
        sig = f"{cmd:02x}:{addr:04x}:{sub:04x}"
        if sig in self.live:
            return bytes(self.live[sig]), True
        return ACK_SHORT, False

    def _apply_write_effects(self, payload: bytes) -> str | None:
        """Patch self.live if this OUTPUT is a write we understand. Returns
        a human-readable description of what was applied, or None."""
        if (
            len(payload) >= 11
            and payload[2] == 0x08
            and payload[4:6] == MASTER_VOLUME_ADDR
            and payload[6] == MASTER_VOLUME_SUB_BYTE
        ):
            db = struct.unpack_from("<f", payload, 7)[0]
            self._set_master_volume(db)
            return f"MASTER VOLUME WRITE -> {db:+.2f} dB (live state updated)"
        if (
            len(payload) >= 8
            and payload[2] == 0x05
            and payload[4:6] == MASTER_VOLUME_ADDR
            and payload[6] == MUTE_SUB_BYTE_MASTER
        ):
            state = "MUTE" if payload[7] else "UNMUTE"
            return f"MASTER {state} (CMD 0x05 sub 0x0d)"
        if (
            len(payload) >= 8
            and payload[2] == 0x05
            and payload[4] == 0xB7
            and 1 <= payload[5] <= 10
            and payload[6] == MUTE_SUB_BYTE_CHANNEL
            and payload[7] in (0x00, 0x01)
        ):
            ch = payload[5]
            state = "MUTE" if payload[7] else "UNMUTE"
            return f"CH{ch} {state} (CMD 0x05 sub 0x0{payload[7]}01)"
        if (
            len(payload) >= 8
            and payload[2] == 0x05
            and payload[4] == 0xB7
            and 1 <= payload[5] <= 10
            and payload[6] == PHASE_SUB_BYTE
            and payload[7] in (0x00, 0x01)
        ):
            ch = payload[5]
            state = "180 (inverted)" if payload[7] else "0 (normal)"
            return f"CH{ch} PHASE {state} (CMD 0x05 sub 0x02)"
        if (
            len(payload) >= 32
            and payload[2] == 0x1C
            and payload[4:6] == MASTER_VOLUME_ADDR
            and payload[6] == BRIDGE_SUB_BYTE
        ):
            bridged = bool(payload[19] & 0x80)
            return f"BRIDGE CH7+CH8 {'ON' if bridged else 'OFF'} (CMD 0x1c sub 0x28)"
        return None

    def _set_master_volume(self, db: float) -> None:
        fbytes = struct.pack("<f", db)
        ka = self.live.get(KEEPALIVE_SIG)
        if ka is not None:
            ka[KEEPALIVE_VOLUME_OFFSET : KEEPALIVE_VOLUME_OFFSET + 4] = fbytes
            ka[KEEPALIVE_CHECKSUM_OFFSET] = (sum(ka[8:16]) - 0x70) & 0xFF
        mr = self.live.get(MASTER_READ_SIG)
        if mr is not None:
            mr[MASTER_BLOCK_VOLUME_OFFSET : MASTER_BLOCK_VOLUME_OFFSET + 4] = fbytes

    def _log_request(
        self, kind: str, payload: bytes, matched: bool, extra: str = "", note: str | None = None
    ) -> None:
        cmd, addr, sub, name = classify_out(payload) if len(payload) >= 8 else (0, 0, 0, "?")
        tag = note or (
            "known" if matched else "**UNMATCHED -- candidate for a not-yet-decoded command**"
        )
        self._log(
            f"{kind}{extra} cmd=0x{cmd:02x} addr=0x{addr:04x} sub=0x{sub:04x} [{name}] {tag}\n"
            f"    req: {payload.hex(' ')}"
        )

    def _handle_output(self, ev: uhid_event) -> None:
        size = ev.u.output.size
        raw = bytes(ev.u.output.data[:size])
        _prefix_len, payload = _split_report_id(raw)
        note = self._apply_write_effects(payload)
        response, matched = self._lookup(payload)
        self._log_request(
            "OUTPUT",
            payload,
            matched or bool(note),
            extra=f" rtype={ev.u.output.rtype} size={size}",
            note=note,
        )
        self.last_response = response
        self._send_input2(response)

    def _handle_get_report(self, ev: uhid_event) -> None:
        req_id = ev.u.get_report.id
        self._log(
            f"GET_REPORT id={req_id} rnum={ev.u.get_report.rnum} "
            f"rtype={ev.u.get_report.rtype} -> replaying last response"
        )
        reply = uhid_event()
        reply.type = UHID_GET_REPORT_REPLY
        reply.u.get_report_reply.id = req_id
        reply.u.get_report_reply.err = 0
        reply.u.get_report_reply.size = len(self.last_response)
        _set_bytes(reply.u.get_report_reply.data, self.last_response)
        self._write_event(reply)

    def _handle_set_report(self, ev: uhid_event) -> None:
        req_id = ev.u.set_report.id
        size = ev.u.set_report.size
        raw = bytes(ev.u.set_report.data[:size])
        _prefix_len, payload = _split_report_id(raw)
        note = self._apply_write_effects(payload)
        response, matched = self._lookup(payload)
        self._log_request(
            "SET_REPORT",
            payload,
            matched or bool(note),
            extra=f" id={req_id} rtype={ev.u.set_report.rtype} size={size}",
            note=note,
        )
        self.last_response = response
        reply = uhid_event()
        reply.type = UHID_SET_REPORT_REPLY
        reply.u.set_report_reply.id = req_id
        reply.u.set_report_reply.err = 0
        self._write_event(reply)

    def run(self) -> None:
        self._log(f"listening on fd={self.fd} ...")
        try:
            while True:
                raw = os.read(self.fd, EVENT_SIZE)
                if not raw:
                    break
                ev = uhid_event.from_buffer_copy(raw.ljust(EVENT_SIZE, b"\x00"))
                if ev.type == UHID_START:
                    self._log(f"START dev_flags=0x{ev.u.start.dev_flags:x}")
                elif ev.type == UHID_OPEN:
                    self._log("OPEN (hidraw node opened)")
                elif ev.type == UHID_CLOSE:
                    self._log("CLOSE (hidraw node closed)")
                elif ev.type == UHID_STOP:
                    self._log("STOP")
                elif ev.type == UHID_OUTPUT:
                    self._handle_output(ev)
                elif ev.type == UHID_GET_REPORT:
                    self._handle_get_report(ev)
                elif ev.type == UHID_SET_REPORT:
                    self._handle_set_report(ev)
                else:
                    self._log(f"unhandled event type={ev.type}")
        except KeyboardInterrupt:
            self._log("interrupted, shutting down")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--device", default=UHID_DEV)
    p.add_argument("--report-descriptor", default=str(REPORT_DESCRIPTOR_PATH))
    p.add_argument("--replay-table", default=str(REPLAY_TABLE_PATH))
    p.add_argument("--log", default=str(LOG_PATH))
    args = p.parse_args()

    rd = Path(args.report_descriptor).read_bytes()
    table = ReplayTable(Path(args.replay_table))
    shim = UhidShim(args.device, rd, table, Path(args.log))
    try:
        shim.run()
    finally:
        shim.destroy()


if __name__ == "__main__":
    main()
