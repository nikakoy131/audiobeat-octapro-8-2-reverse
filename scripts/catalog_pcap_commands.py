#!/usr/bin/env python3
"""Catalog every unique (CMD, ADDR, SUB) signature seen in a USB pcap.

Usage:
    uv run python scripts/catalog_pcap_commands.py <pcap> [<pcap> ...]

Notes:
    * pcaps are USBPcap captures of HID CONTROL transfers
    * OUT payload (host→device) starts with e0 a2
    * IN payload (device→host) has 2-byte status prefix, then e0 a2
    * CMD 0x0a uses a single-byte SUB at [6] (rest of [7:11] is float32);
      all other CMDs use a 2-byte LE SUB at [6:8].

Known CMDs:
    0x04 WRITE_PARAM   — register-style write (e.g. keepalive 0xa515, firmware 0x80f0)
    0x05 READ/COMMIT   — channel readback (addr=0x00b0) and DSP commit (addr=0xNNb7)
    0x08 UNKNOWN8      — seen in handshake; sub=0x0206 vs 0x8206 (two variants)
    0x0a WRITE_DSP     — real-time DSP write; sub 0x05=HPF, 0x26=GAIN (+ LPF, EQ, etc)
    0x1c UNKNOWN1C     — seen in handshake; sub=0x0121
"""
from __future__ import annotations
import struct
import sys
from collections import defaultdict
from pathlib import Path

from scapy.all import rdpcap

MAGIC = bytes([0xe0, 0xa2])


def extract_hid_payloads(pcap_path: Path):
    """Yield (frame_num, 256-byte OUT payload) for each OUT HID SET_REPORT frame."""
    for i, pkt in enumerate(rdpcap(str(pcap_path)), start=1):
        raw = bytes(pkt)
        # OUT: USBPcap pseudoheader (28B) + SETUP stage (8B) + 256B HID payload
        if len(raw) >= 36 + 256 and raw[36:38] == MAGIC:
            yield i, raw[36:36 + 256]


def main(pcaps: list[str]) -> None:
    unique = defaultdict(list)  # (cmd, addr, sub) -> list of (file, frame, first16)

    for p in pcaps:
        path = Path(p)
        for frame, payload in extract_hid_payloads(path):
            cmd = payload[2]
            if payload[3] != 0x00 or cmd not in (0x04, 0x05, 0x08, 0x0a, 0x1c):
                continue
            addr = struct.unpack('<H', payload[4:6])[0]
            if cmd == 0x0a:
                sub = payload[6]
            else:
                sub = struct.unpack('<H', payload[6:8])[0]
            key = (cmd, addr, sub)
            unique[key].append((path.name, frame, payload[:16].hex(' ')))

    print(f"Total unique (CMD, ADDR, SUB) signatures: {len(unique)}\n")
    print(f"{'CMD':<4} {'ADDR':<6} {'SUB':<6} {'COUNT':<6}  FIRST SAMPLE (first 16 bytes)")
    print("-" * 100)
    for (cmd, addr, sub), hits in sorted(unique.items()):
        first = hits[0]
        sub_fmt = f"0x{sub:04x}" if cmd != 0x0a else f"0x{sub:02x}"
        print(f"0x{cmd:02x} 0x{addr:04x} {sub_fmt:<6} {len(hits):<6}  "
              f"{first[0]}#{first[1]:>5}  {first[2]}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
