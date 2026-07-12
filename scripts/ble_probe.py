#!/usr/bin/env python3
"""Verify the OctaPro BLE control path with the framing recovered from the applet.

The applet's own JavaScript (docs/findings/BLE.md, "How this was obtained")
settled the framing: the BLE link carries the *identical* `e0 a2 …` packets as
USB. The recipe:
    service      0xAE00
    write char   0xAE10   (write WITH response), send the SHORT packet (no 256 pad)
    notify char  0xAE02   (responses; concatenate until the framed length is met)
    handshake    write session-open `e0 a2 05 00 b7 00 03 11 ab` first
This sends only the two non-destructive commands (session-open + READ_BLOCK), so
it is safe to run against the device (read policy). A clean channel-block decode
confirms BLE == USB protocol end to end.

Run:  uv run --extra ble python scripts/ble_probe.py --id <peripheral-uuid>
      [--channel N]

An `ee55` reply instead of a block means session-open wasn't honored; anything on
AE04/AE05 (also subscribed, for visibility) is logged too.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from bleak import BleakClient

sys.path.insert(0, "src")
from octapro.protocol.channel import parse_channel_block  # noqa: E402
from octapro.protocol.packet import build_read_channel, build_session_open  # noqa: E402


def u(short: str) -> str:
    return f"0000{short.lower()}-0000-1000-8000-00805f9b34fb"


WRITE_CHAR = u("ae10")
NOTIFY_MAIN = u("ae02")
NOTIFY_EXTRA = [u("ae04"), u("ae05")]

# ACK / status frames the applet discards (docs/findings/BLE.md "Response framing")
ACK_PREFIXES = (b"\xee\xbb", b"\xee\x55", b"\xbe\x70\x1d\x00", b"\xbe\x70\x22")


def expected_len(buf: bytes) -> int | None:
    """Total e0a2 response length = u16_LE(bytes[2:4]) + 4, per the applet."""
    if len(buf) < 4 or buf[:2] != b"\xe0\xa2":
        return None
    return int.from_bytes(buf[2:4], "little") + 4


async def verify(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    buf = bytearray()
    done = asyncio.Event()

    def on_main(_s, data: bytearray) -> None:
        d = bytes(data)
        print(f"  [{time.monotonic()-t0:6.3f}s] AE02 ({len(d)}B): {d.hex(' ')}", flush=True)
        if any(d.startswith(p) for p in ACK_PREFIXES):
            print("    (ACK/status frame — ignored for reassembly)", flush=True)
            return
        buf.extend(d)
        n = expected_len(bytes(buf))
        if n is not None and len(buf) >= n:
            done.set()

    def on_extra(name: str):
        def cb(_s, data: bytearray) -> None:
            print(f"  [{time.monotonic()-t0:6.3f}s] {name} ({len(data)}B): "
                  f"{bytes(data).hex(' ')}", flush=True)
        return cb

    print(f"Connecting to {args.id}...", flush=True)
    async with BleakClient(args.id) as client:
        print(f"Connected: {client.is_connected}   MTU: {client.mtu_size}", flush=True)
        await client.start_notify(NOTIFY_MAIN, on_main)
        for c in NOTIFY_EXTRA:
            try:
                await client.start_notify(c, on_extra(c[4:8]))
            except Exception as exc:  # noqa: BLE001 - research script
                print(f"subscribe {c[4:8]} failed: {exc}", flush=True)

        async def send(name: str, pkt: bytes) -> None:
            payload = pkt.rstrip(b"\x00")  # short packet, NOT padded to 256
            print(f">>> {name} -> AE10 ({len(payload)}B, with response): "
                  f"{payload.hex(' ')}", flush=True)
            await client.write_gatt_char(WRITE_CHAR, payload, response=True)

        await send("session_open", bytes(build_session_open()))
        await asyncio.sleep(0.4)
        buf.clear()
        done.clear()
        await send(f"read_channel({args.channel})", bytes(build_read_channel(args.channel)))
        try:
            await asyncio.wait_for(done.wait(), timeout=args.wait)
        except TimeoutError:
            print("\nNo complete response within timeout.", flush=True)

    resp = bytes(buf)
    print(f"\n===== reassembled AE02: {len(resp)}B =====", flush=True)
    if not resp:
        print("Nothing to decode. If AE10 rejected the write, retry with response=False, "
              "or check that session-open was accepted.")
        return 2
    print(resp.hex(' '), flush=True)
    # BLE response header is 2 bytes shorter than USB (no leading status word):
    #   [0:2]=e0a2  [2:4]=datalen u16 LE  [4:6]=addr  [6:]=channel block
    datalen = int.from_bytes(resp[2:4], "little")
    addr = int.from_bytes(resp[4:6], "little")
    data = resp[6:]
    print(f"magic={resp[:2].hex()} datalen={datalen} addr=0x{addr:04x} "
          f"blocklen={len(data)}", flush=True)
    try:
        block = parse_channel_block(data, ch=args.channel)
        print(f"\nDECODED CH{args.channel}: gain={block.gain_db:.1f}dB "
              f"delay={block.delay_ms:.3f}ms hpf={block.hpf_freq_hz:.1f}Hz "
              f"lpf={block.lpf_freq_hz:.1f}Hz speaker=0x{block.speaker_type_byte:02x}", flush=True)
        print("==> BLE carries the same e0 a2 protocol. Confirmed end to end.", flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - research script
        print(f"\nchannel-block decode failed: {exc}\n"
              "The BLE response header may pack differently than USB (datalen at [2:4] "
              "vs [4:6]); realign parse_channel_block offsets against this raw dump.", flush=True)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", required=True, help="CoreBluetooth peripheral UUID from ble_scan.py")
    ap.add_argument("--channel", type=int, default=1, help="channel to READ_BLOCK (1..10)")
    ap.add_argument("--wait", type=float, default=3.0, help="response wait (s)")
    args = ap.parse_args()
    return asyncio.run(verify(args))


if __name__ == "__main__":
    raise SystemExit(main())
