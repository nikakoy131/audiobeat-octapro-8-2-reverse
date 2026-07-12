#!/usr/bin/env python3
"""Live BLE WRITE verification: mute a channel, then unmute it (self-reversing).

Confirms the write path over Bluetooth end to end using the safest possible
state change — a mute that is immediately reverted. Reads the channel block
before/after each step and diffs the raw bytes, so the change is confirmed both
audibly (the channel goes silent then returns) and programmatically (and it
locates the mute bit inside the read block as a bonus).

Sends, in order (all to AE10, with response), on channel N:
    session-open -> read block -> MUTE -> read block -> UNMUTE -> read block
Ends with the channel UNMUTED (original state restored).

Run:  uv run --extra ble python scripts/ble_mute_test.py --id <uuid> [--channel 1]
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from bleak import BleakClient

sys.path.insert(0, "src")
from octapro.protocol.packet import build_mute, build_read_channel, build_session_open  # noqa: E402


def u(short: str) -> str:
    return f"0000{short.lower()}-0000-1000-8000-00805f9b34fb"


WRITE_CHAR = u("ae10")
NOTIFY_MAIN = u("ae02")
ACK_PREFIXES = (b"\xee\xbb", b"\xee\x55", b"\xbe\x70\x1d\x00", b"\xbe\x70\x22")


def diff(a: bytes, b: bytes) -> list[str]:
    out = []
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            out.append(f"byte[{i}]: 0x{a[i]:02x} -> 0x{b[i]:02x}")
    if len(a) != len(b):
        out.append(f"length {len(a)} -> {len(b)}")
    return out


class Reader:
    """Accumulates AE02 notifications into one e0a2 frame (block at offset 6)."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.done = asyncio.Event()

    def on_notify(self, _s, data: bytearray) -> None:
        d = bytes(data)
        if any(d.startswith(p) for p in ACK_PREFIXES):
            return
        self.buf.extend(d)
        if len(self.buf) >= 4 and self.buf[:2] == b"\xe0\xa2":
            total = int.from_bytes(self.buf[2:4], "little") + 4
            if len(self.buf) >= total:
                self.done.set()

    def reset(self) -> None:
        self.buf.clear()
        self.done.clear()

    def block(self) -> bytes:
        return bytes(self.buf)[6:]  # channel block starts at byte 6 over BLE


async def run(args: argparse.Namespace) -> int:
    ch = args.channel
    rd = Reader()

    async with BleakClient(args.id) as client:
        print(f"Connected: {client.is_connected}  MTU: {client.mtu_size}", flush=True)
        await client.start_notify(NOTIFY_MAIN, rd.on_notify)

        async def write(name: str, pkt: bytes) -> None:
            payload = pkt.rstrip(b"\x00")
            print(f">>> {name}: {payload.hex(' ')}", flush=True)
            await client.write_gatt_char(WRITE_CHAR, payload, response=True)

        async def read_block(label: str) -> bytes:
            rd.reset()
            await client.write_gatt_char(
                WRITE_CHAR, bytes(build_read_channel(ch)).rstrip(b"\x00"), response=True
            )
            try:
                await asyncio.wait_for(rd.done.wait(), timeout=3.0)
            except TimeoutError:
                print(f"  ({label}) read timed out", flush=True)
            b = rd.block()
            print(f"  ({label}) block {len(b)}B", flush=True)
            return b

        await write("session_open", bytes(build_session_open()))
        await asyncio.sleep(0.3)

        base = await read_block("before")

        print(f"\n--- MUTING CH{ch} (listen: it should go silent) ---", flush=True)
        await write(f"mute CH{ch}", bytes(build_mute(ch, True)))
        await asyncio.sleep(args.hold)
        muted = await read_block("muted")
        d1 = diff(base, muted)
        print(f"  block diff after MUTE: {d1 or 'no byte changed (?)'}", flush=True)

        print(f"\n--- UNMUTING CH{ch} (listen: it should return) ---", flush=True)
        await write(f"unmute CH{ch}", bytes(build_mute(ch, False)))
        await asyncio.sleep(args.hold)
        restored = await read_block("after")
        d2 = diff(muted, restored)
        print(f"  block diff after UNMUTE: {d2 or 'no byte changed (?)'}", flush=True)

        ok = base == restored
        print(f"\nround-trip restored original block: {ok}", flush=True)
        if d1:
            print(f"==> mute bit located in read block: {d1}", flush=True)
        print("==> BLE WRITE path confirmed (channel muted then unmuted)."
              if d1 else "==> writes sent; if you heard the mute/unmute it works "
              "(block mute bit not observed).", flush=True)
        return 0 if (d1 and ok) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", required=True)
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--hold", type=float, default=3.0, help="seconds to stay muted")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
