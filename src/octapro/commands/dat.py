import logging
from pathlib import Path

log = logging.getLogger("octapro.dat")

_SLOPE_NAMES = {0x03: "12 dB/oct", 0x05: "36 dB/oct"}


def run_parse_dat(path: Path, channel: int | None = None) -> int:
    from rich import box
    from rich.console import Console
    from rich.table import Table

    from octapro.logging import warn_unknown
    from octapro.protocol.constants import LPF_BYPASS_HZ
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

    channels = preset.channels
    if channel is not None:
        channels = [c for c in channels if c.index == channel]
        if not channels:
            log.error("Channel %d not found in preset", channel)
            return 1

    table = Table(title=f"Preset: {path.name}", box=box.SIMPLE_HEAD)
    table.add_column("CH", style="bold", width=3)
    table.add_column("HPF Hz", width=9)
    table.add_column("HPF slope", width=11)
    table.add_column("LPF Hz", width=9)
    table.add_column("LPF slope", width=11)
    table.add_column("EQ active", width=12)

    for ch in channels:
        active = [b for b in ch.eq_bands if b.gain_db is not None and abs(b.gain_db) > 0.05]
        eq_str = f"{len(active)} band(s)" if active else "flat"
        lpf_str = "bypass" if abs(ch.lpf_freq_hz - LPF_BYPASS_HZ) < 100 else f"{ch.lpf_freq_hz:.1f}"
        hpf_str = f"{ch.hpf_freq_hz:.1f}" if ch.hpf_freq_hz > 10 else f"~{ch.hpf_freq_hz:.1f} (?)"
        table.add_row(
            str(ch.index),
            hpf_str,
            _SLOPE_NAMES.get(ch.hpf_slope_byte, f"0x{ch.hpf_slope_byte:02x}"),
            lpf_str,
            _SLOPE_NAMES.get(ch.lpf_slope_byte, f"0x{ch.lpf_slope_byte:02x}"),
            eq_str,
        )

    console.print(table)

    # Per-channel unknown bytes — logged at DEBUG so they show with -v
    for ch in channels:
        for k, v in ch.unknown_bytes.items():
            log.debug("CH%d unknown %s = %s", ch.index, k, v)

    return 0
