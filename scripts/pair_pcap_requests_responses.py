#!/usr/bin/env python3
"""Pair every OUT request with its IN response, grouped by (CMD, ADDR, SUB).

Usage:
    uv run python scripts/pair_pcap_requests_responses.py <pcap>

Prints one block per unique signature:
    OUT packet header + first data bytes
    IN  response status, magic, data length, address, first data bytes

USBPcap frame layout (see catalog_pcap_commands.py for more):
    OUT SET_REPORT: 28B pseudoheader + 8B SETUP + 256B HID payload (magic at offset 36)
    IN  GET_REPORT: 28B pseudoheader + 256B HID payload with 2B status prefix, then magic at offset 30

IN response structure (256 bytes):
    [0:2]  STATUS (uint16 LE) — e.g. 0x000f = keepalive ack, 0x00f6 = full channel, 0x008d = master, 0x002f = short info, 0x006a = firmware
    [2:4]  magic 0xe0a2
    [4:6]  DATA_LEN (uint16 LE)
    [6:8]  ADDR echo
    [8+]   payload data
"""
from __future__ import annotations
import struct
import sys
from collections import defaultdict

from scapy.all import rdpcap

MAGIC = bytes([0xe0, 0xa2])


def parse_pkt(raw: bytes):
    """Classify a USBPcap frame and return (direction, 256-byte payload) or (None, None).

    direction: 0 = OUT (host→device), 1 = IN (device→host)
    """
    if len(raw) < 36 + 4:
        return None, None
    if len(raw) >= 36 + 256 and raw[36:38] == MAGIC:
        return 0, raw[36:36 + 256]
    if len(raw) >= 28 + 256 and raw[30:32] == MAGIC:
        return 1, raw[28:28 + 256]
    return None, None


def classify_out(payload: bytes):
    """Extract (cmd, addr, sub, name) from an OUT payload."""
    cmd = payload[2]
    addr = struct.unpack('<H', payload[4:6])[0]
    if cmd == 0x0a:
        sub = payload[6]
    else:
        sub = struct.unpack('<H', payload[6:8])[0]
    name = {
        0x04: 'WRITE_PARAM',
        0x05: 'READ/COMMIT',
        0x08: 'UNKNOWN8',
        0x0a: 'WRITE_DSP',
        0x1c: 'UNKNOWN1C',
    }.get(cmd, '?')
    return cmd, addr, sub, name


def main(pcap_path: str) -> None:
    events = []  # list of (frame, direction, payload)
    for i, pkt in enumerate(rdpcap(pcap_path), start=1):
        d, pl = parse_pkt(bytes(pkt))
        if d is not None:
            events.append((i, d, pl))

    # Pair each OUT with the next IN within a short window
    pairs = []
    for i, (frame, d, pl) in enumerate(events):
        if d != 0:
            continue
        resp = None
        for j in range(i + 1, min(i + 5, len(events))):
            f2, d2, pl2 = events[j]
            if d2 == 1:
                resp = (f2, pl2)
                break
        pairs.append((frame, pl, resp))

    # Group by (cmd, addr, sub)
    groups = defaultdict(list)
    for frame, pl, resp in pairs:
        sig = classify_out(pl)
        groups[sig[:3]].append((frame, pl, resp, sig[3]))

    for sig in sorted(groups):
        cmd, addr, sub = sig
        hits = groups[sig]
        name = hits[0][3]
        frame, pl, resp, _ = hits[0]
        sub_fmt = f"0x{sub:04x}" if cmd != 0x0a else f"0x{sub:02x}"
        print(f"=== CMD=0x{cmd:02x} ADDR=0x{addr:04x} SUB={sub_fmt} [{name}] — {len(hits)} hits ===")
        print(f"  OUT #{frame}: {pl[:24].hex(' ')}")
        if resp is None:
            print("  IN:  (none)")
        else:
            rf, rp = resp
            status = struct.unpack('<H', rp[0:2])[0]
            dlen = struct.unpack('<H', rp[4:6])[0]
            raddr = struct.unpack('<H', rp[6:8])[0]
            print(f"  IN  #{rf}: status=0x{status:04x} magic={rp[2:4].hex()} "
                  f"dlen=0x{dlen:04x} addr=0x{raddr:04x}")
            print(f"       head: {rp[:24].hex(' ')}")
            if status > 2:
                print(f"       data[8:48]: {rp[8:48].hex(' ')}")
        print()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
