#!/usr/bin/env python3
"""Full read-only snapshot of the live device over BLE: master + all 10 channels.

Captures the actual installed configuration (gain, delay, HPF/LPF, speaker type,
mute, EQ deviations, routing) so a future session has a reference for guessing
the real-world channel layout (which output likely drives which speaker) without
re-deriving it from scratch. Purely reads — no writes, safe to run any time.

Writes two files under research/device-snapshots/<timestamp>/:
  snapshot.json    full decoded data (machine-readable)
  summary.md       human-readable per-channel table + notes

Run:  uv run --extra ble python scripts/ble_snapshot.py --id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bleak import BleakClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from octapro.protocol.channel import parse_channel_block, parse_master_block  # noqa: E402
from octapro.protocol.constants import (  # noqa: E402
    FILTER_TYPE_NAMES,
    ROUTING_INPUT_NAMES,
    SLOPE_NAMES,
    SPEAKER_TYPE_NAMES,
)
from octapro.protocol.packet import build_read_channel, build_session_open  # noqa: E402

MUTE_BYTE_OFFSET = 29  # live-found 2026-07-12 via ble_mute_test.py diff (CH1 & CH4)


def u(short: str) -> str:
    return f"0000{short.lower()}-0000-1000-8000-00805f9b34fb"


WRITE_CHAR = u("ae10")
NOTIFY_MAIN = u("ae02")
ACK_PREFIXES = (b"\xee\xbb", b"\xee\x55", b"\xbe\x70\x1d\x00", b"\xbe\x70\x22")


class Reader:
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


def eq_deviations(bands) -> list[dict]:
    out = []
    for b in bands:
        if b.gain_db is not None and abs(b.gain_db) > 0.05:
            out.append({"band": b.index + 1, "freq_hz": b.freq_hz, "gain_db": b.gain_db})
    return out


async def snapshot(args: argparse.Namespace) -> int:
    rd = Reader()
    result: dict = {"captured_at": datetime.now(UTC).isoformat(), "channels": {}}

    async with BleakClient(args.id) as client:
        print(f"Connected: {client.is_connected}  MTU: {client.mtu_size}", flush=True)
        await client.start_notify(NOTIFY_MAIN, rd.on_notify)

        so = bytes(build_session_open()).rstrip(b"\x00")
        await client.write_gatt_char(WRITE_CHAR, so, response=True)
        await asyncio.sleep(0.3)

        async def read_ch(ch: int) -> bytes:
            rd.reset()
            pkt = bytes(build_read_channel(ch)).rstrip(b"\x00")
            await client.write_gatt_char(WRITE_CHAR, pkt, response=True)
            await asyncio.wait_for(rd.done.wait(), timeout=3.0)
            resp = bytes(rd.buf)
            datalen = int.from_bytes(resp[2:4], "little")
            return resp[6 : 6 + datalen]

        print("Reading CH0 (master)...", flush=True)
        m = parse_master_block(await read_ch(0))
        result["master"] = {
            "volume_db": round(m.volume_db, 2),
            "noise_gate_db": round(m.noise_gate_db, 2),
            "firmware": m.firmware,
        }
        print(f"  volume={m.volume_db:.2f}dB firmware={m.firmware!r}", flush=True)

        for ch in range(1, 11):
            print(f"Reading CH{ch}...", flush=True)
            data = await read_ch(ch)
            block = parse_channel_block(data, ch=ch)
            muted = bool(data[MUTE_BYTE_OFFSET]) if len(data) > MUTE_BYTE_OFFSET else None
            lpf_bypass = block.lpf_freq_hz > 20000
            result["channels"][ch] = {
                "gain_db": round(block.gain_db, 2),
                "delay_ms": round(block.delay_ms, 3),
                "muted": muted,
                "hpf": {
                    "freq_hz": round(block.hpf_freq_hz, 1),
                    "slope": SLOPE_NAMES.get(block.hpf_slope_byte, block.hpf_slope_byte),
                    "type": FILTER_TYPE_NAMES.get(block.hpf_type_byte, block.hpf_type_byte),
                },
                "lpf": {
                    "freq_hz": round(block.lpf_freq_hz, 1),
                    "bypass": lpf_bypass,
                    "slope": SLOPE_NAMES.get(block.lpf_slope_byte, block.lpf_slope_byte),
                    "type": FILTER_TYPE_NAMES.get(block.lpf_type_byte, block.lpf_type_byte),
                },
                "speaker_type": SPEAKER_TYPE_NAMES.get(
                    block.speaker_type_byte, f"0x{block.speaker_type_byte:02x}"
                ),
                "eq_deviations": eq_deviations(block.eq_bands),
                "routing_db": [
                    None if v == float("-inf") else v for v in block.routing.values
                ],
            }
            print(f"  gain={block.gain_db:+.1f}dB delay={block.delay_ms:.2f}ms "
                  f"HPF={block.hpf_freq_hz:.0f}Hz "
                  f"LPF={'bypass' if lpf_bypass else f'{block.lpf_freq_hz:.0f}Hz'} "
                  f"speaker={result['channels'][ch]['speaker_type']} "
                  f"muted={muted}", flush=True)

    outdir = ROOT / "research" / "device-snapshots" / datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "snapshot.json").write_text(json.dumps(result, indent=2))

    lines = [
        f"# Device snapshot — {result['captured_at']}",
        "",
        f"Master volume: **{result['master']['volume_db']:.2f} dB** "
        f"(firmware `{result['master']['firmware']}`)",
        "",
        "| CH | Gain | Delay | Muted | HPF | LPF | Speaker | EQ tweaks | Dominant routing input |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    input_names = ROUTING_INPUT_NAMES
    for ch, c in result["channels"].items():
        hpf = f"{c['hpf']['freq_hz']:.0f}Hz {c['hpf']['slope']} {c['hpf']['type']}"
        lpf = "bypass" if c["lpf"]["bypass"] else f"{c['lpf']['freq_hz']:.0f}Hz {c['lpf']['slope']}"
        eq = ", ".join(f"b{e['band']}={e['gain_db']:+.1f}dB" for e in c["eq_deviations"]) or "flat"
        routing_pairs = [
            (input_names[i] if i < len(input_names) else f"in{i}", v)
            for i, v in enumerate(c["routing_db"]) if v is not None
        ]
        routing_pairs.sort(key=lambda p: -p[1])
        dom = ", ".join(f"{n}({v:+.0f}dB)" for n, v in routing_pairs[:2]) or "none"
        lines.append(
            f"| {ch} | {c['gain_db']:+.1f}dB | {c['delay_ms']:.2f}ms | "
            f"{'yes' if c['muted'] else 'no'} | {hpf} | {lpf} | {c['speaker_type']} | "
            f"{eq} | {dom} |"
        )
    lines += [
        "",
        "Notes for guessing physical layout: HPF-only channels with a high cutoff "
        "(e.g. >2kHz) are likely tweeters/mids; low LPF (e.g. <150Hz) with speaker "
        "type suggesting sub is likely the subwoofer; \"dominant routing input\" shows "
        "which physical input feeds that output the most.",
    ]
    (outdir / "summary.md").write_text("\n".join(lines) + "\n")

    print(f"\nWrote {outdir / 'snapshot.json'}", flush=True)
    print(f"Wrote {outdir / 'summary.md'}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", required=True)
    args = ap.parse_args()
    return asyncio.run(snapshot(args))


if __name__ == "__main__":
    raise SystemExit(main())
