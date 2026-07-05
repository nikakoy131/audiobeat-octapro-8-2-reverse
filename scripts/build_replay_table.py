#!/usr/bin/env python3
"""Build a request->response replay table from real-device pcaps, for the
Linux uhid virtual-amplifier shim (see docs/LINUX_UHID_SHIM_PLAN.md).

Reuses the OUT/IN framing + classification logic from
pair_pcap_requests_responses.py so the two scripts never disagree about how
to parse a frame.

Usage:
    uv run python scripts/build_replay_table.py [pcap ...]

Defaults to usb1.pcapng usb2.pcapng (repo root) if no paths given. Writes
docs/replay_table.json:

    {
      "by_exact_request": {"<256B OUT hex>": "<256B IN hex>", ...},
      "by_signature":     {"cmd:addr:sub hex triple": "<256B IN hex>", ...}
    }

`by_exact_request` is tried first (our packet builders are pure functions of
their arguments, so identical commands produce byte-identical OUT payloads
across captures); `by_signature` is a fallback in case the shim sees a
request that matches a known command's (cmd, addr, sub) but not its exact
bytes (e.g. a live value baked into the payload).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scapy.all import rdpcap

sys.path.insert(0, str(Path(__file__).parent))
from pair_pcap_requests_responses import classify_out, parse_pkt  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_PCAPS = ["usb1.pcapng", "usb2.pcapng"]
OUTPUT_PATH = REPO_ROOT / "docs" / "replay_table.json"


def signature_key(payload: bytes) -> str:
    cmd, addr, sub, _name = classify_out(payload)
    return f"{cmd:02x}:{addr:04x}:{sub:04x}"


def collect_pairs(pcap_path: Path) -> list[tuple[bytes, bytes]]:
    """Return [(out_payload, in_payload), ...] pairs from one pcap.

    Only pairs an OUT with the *immediately following* event, and only if
    that's an IN. Scanning further ahead (as an earlier version of this
    script did, within a window of 5 events) is unsound: some commands
    (e.g. the session-open packet, usb1.pcapng frame 107) get no reply at
    all in the capture, and the wider window would silently pair them with
    the next unrelated command's reply instead. That mispairing broke the
    Linux uhid shim's handshake (docs/LINUX_UHID_SHIM_PLAN.md) -- it kept
    replaying a firmware-string blob in answer to session-open, and the
    real app just retried the connection forever.

    A command with no immediate IN here should fall back to a generic ack
    in the shim (see scripts/uhid_shim.py ACK_SHORT), not a guessed reply.
    """
    events = []
    for pkt in rdpcap(str(pcap_path)):
        d, pl = parse_pkt(bytes(pkt))
        if d is not None:
            events.append((d, pl))

    pairs = []
    for i, (d, pl) in enumerate(events):
        if d != 0:
            continue
        if i + 1 < len(events) and events[i + 1][0] == 1:
            pairs.append((pl, events[i + 1][1]))
    return pairs


def main(pcap_paths: list[str]) -> None:
    by_exact_request: dict[str, str] = {}
    by_signature: dict[str, str] = {}

    total_pairs = 0
    for pcap_name in pcap_paths:
        pcap_path = REPO_ROOT / pcap_name
        if not pcap_path.exists():
            print(f"skip (not found): {pcap_path}", file=sys.stderr)
            continue
        pairs = collect_pairs(pcap_path)
        total_pairs += len(pairs)
        print(f"{pcap_name}: {len(pairs)} request/response pairs")
        for out_pl, in_pl in pairs:
            req_key = out_pl.hex()
            if req_key not in by_exact_request:
                by_exact_request[req_key] = in_pl.hex()
            sig_key = signature_key(out_pl)
            if sig_key not in by_signature:
                by_signature[sig_key] = in_pl.hex()

    table = {"by_exact_request": by_exact_request, "by_signature": by_signature}
    OUTPUT_PATH.write_text(json.dumps(table, indent=2) + "\n")

    print(f"\ntotal pairs seen:      {total_pairs}")
    print(f"unique exact requests: {len(by_exact_request)}")
    print(f"unique signatures:     {len(by_signature)}")
    print(f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}")

    print("\nsignatures captured:")
    for sig in sorted(by_signature):
        print(f"  {sig}")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_PCAPS)
