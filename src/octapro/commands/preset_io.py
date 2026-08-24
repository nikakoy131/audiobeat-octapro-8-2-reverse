"""Import / export full .dat presets (US002 format).

Export reads all 10 channel blocks from the device and writes a US002 .dat.
Import parses a .dat and pushes every supported per-channel parameter (gain,
delay, HPF, LPF, speaker type, 31-band EQ) via the normal write commands.

Routing is NOT round-tripped by import: the .dat/read-block routing is a 30-byte
device read-format that does not map to the CMD 0x20 write format, so importing
skips it (export still copies the bytes verbatim).
"""

import logging
from pathlib import Path

from octapro.protocol.dat import BLOCK_LEN, HEADER_MAGIC, DatChannel

log = logging.getLogger("octapro.preset")

DAT_FOOTER = b"\x00\x00"  # trailing 2 bytes observed on every real export


def channel_payload_to_dat_block(payload: bytes) -> bytes:
    """A 242-byte device READ_BLOCK payload -> its 238-byte .dat block.

    The .dat block is the device block shifted by 1 (drop the [0] prefix and the
    [239] trailer / [240:242] padding).
    """
    return bytes(payload[1 : 1 + BLOCK_LEN]).ljust(BLOCK_LEN, b"\x00")


def serialize_dat(dat_blocks: list[bytes]) -> bytes:
    """US002 file = magic + 10×238-byte blocks + 2-byte footer."""
    if len(dat_blocks) != 10:
        raise ValueError(f"need 10 channel blocks, got {len(dat_blocks)}")
    return HEADER_MAGIC + b"".join(dat_blocks) + DAT_FOOTER


def dat_channel_packets(ch: DatChannel, include_flat_eq: bool = True) -> list[tuple[str, bytes]]:
    """Every write packet needed to apply one .dat channel (routing excluded).

    Returns [(label, packet), ...] in apply order. EQ bands that are flat
    (0 dB, default Q) are skipped when include_flat_eq is False.
    """
    from octapro.protocol.constants import EQ_DEFAULT_Q_BYTE, GAIN_ZERO_BYTE, slope_byte_to_db
    from octapro.protocol.packet import (
        build_channel_delay,
        build_channel_gain,
        build_eq_band,
        build_hpf,
        build_lpf,
        build_speaker_type,
    )

    n = ch.index
    out: list[tuple[str, bytes]] = [
        (f"CH{n} gain {ch.gain_db:+.1f} dB", bytes(build_channel_gain(n, ch.gain_db))),
        (f"CH{n} delay {ch.delay_ms:.2f} ms", bytes(build_channel_delay(n, ch.delay_ms))),
    ]
    if 1 <= ch.speaker_type_byte <= 6:
        code = ch.speaker_type_byte
        out.append((f"CH{n} speaker type {code}", bytes(build_speaker_type(n, code))))
    for kind, freq, slope, ftype, builder in (
        ("HPF", ch.hpf_freq_hz, ch.hpf_slope_byte, ch.hpf_type_byte, build_hpf),
        ("LPF", ch.lpf_freq_hz, ch.lpf_slope_byte, ch.lpf_type_byte, build_lpf),
    ):
        try:
            pkt = builder(n, freq, slope_byte_to_db(slope), ftype)
        except ValueError as exc:
            log.warning("CH%d %s skipped: %s", n, kind, exc)
            continue
        out.append((f"CH{n} {kind} {freq:.0f} Hz", bytes(pkt)))

    for band in ch.eq_bands:
        is_flat = band.gain_byte == GAIN_ZERO_BYTE and band.q_byte == EQ_DEFAULT_Q_BYTE
        if is_flat and not include_flat_eq:
            continue
        out.append(
            (
                f"CH{n} EQ band {band.index + 1}",
                bytes(build_eq_band(n, band.index + 1, band.gain_db, band.freq_hz, band.q)),
            )
        )
    return out


def run_export_dat(path: Path, no_keepalive: bool = False) -> int:
    """Read all 10 channels from the device and write a US002 .dat file."""
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.packet import InPacket, build_read_channel
    from octapro.transport import open_transport

    try:
        blocks: list[bytes] = []
        with open_transport() as t:
            if not no_keepalive:
                t.start_keepalive()
            for ch in range(1, 11):
                rd = build_read_channel(ch)
                log_packet_out(0x05, 0x00B0, (0x04 << 8) | ch, bytes(rd))
                resp = t.transact(bytes(rd))
                log_packet_in(resp)
                blocks.append(channel_payload_to_dat_block(InPacket(resp).data))
        data = serialize_dat(blocks)
        path.write_bytes(data)
    except Exception as exc:
        log.error("Export failed: %s", exc)
        return 1
    log.info("Exported %d bytes to %s", len(data), path)
    return 0


def run_import_dat(
    path: Path,
    commit: bool,
    channels: list[int] | None = None,
    include_flat_eq: bool = True,
    no_keepalive: bool = False,
) -> int:
    """Parse a .dat and push every supported parameter to the device.

    Dry-run (default) prints a per-channel summary; --commit sends the writes.
    Routing is skipped (see module docstring).
    """
    from rich.console import Console

    from octapro.logging import warn_unknown
    from octapro.protocol.dat import parse_dat

    console = Console()
    if not path.exists():
        log.error("File not found: %s", path)
        return 1
    try:
        preset = parse_dat(path, warn=warn_unknown)
    except Exception as exc:
        log.error("Parse error: %s", exc)
        return 1

    wanted = set(channels) if channels else set(range(1, 11))
    plan: list[tuple[str, bytes]] = []
    for ch in preset.channels:
        if ch.index in wanted:
            plan.extend(dat_channel_packets(ch, include_flat_eq=include_flat_eq))

    console.print(f"[bold]Import {path.name}[/bold] → {len(plan)} write packets "
                  f"(channels {sorted(wanted)}); routing NOT applied.")
    by_ch: dict[int, int] = {}
    for label, _ in plan:
        c = int(label.split()[0][2:])
        by_ch[c] = by_ch.get(c, 0) + 1
    for c in sorted(by_ch):
        console.print(f"  CH{c}: {by_ch[c]} packets")

    if not commit:
        console.print("[dim]Dry run — add --commit to actually send.[/dim]")
        return 0

    from octapro.logging import log_packet_in, log_packet_out
    from octapro.transport import open_transport

    try:
        with open_transport() as t:
            if not no_keepalive:
                t.start_keepalive()
            for _label, pkt in plan:
                log_packet_out(pkt[2], int.from_bytes(pkt[4:6], "little"), pkt[6], pkt)
                resp = t.transact(pkt)
                log_packet_in(resp)
            log.info("Imported %d packets from %s", len(plan), path)
    except Exception as exc:
        log.error("Import failed: %s", exc)
        return 1
    return 0
