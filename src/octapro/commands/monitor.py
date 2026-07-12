import logging
import time

from octapro.protocol.constants import SLOPE_NAMES as _SLOPE_NAMES

log = logging.getLogger("octapro.monitor")


def run_monitor(interval: float = 0.5) -> int:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    from octapro.logging import warn_unknown
    from octapro.protocol.channel import parse_channel_block
    from octapro.protocol.constants import (
        FILTER_TYPE_NAMES,
        LPF_BYPASS_HZ,
        SPEAKER_TYPE_NAMES,
    )
    from octapro.protocol.packet import InPacket, build_read_channel
    from octapro.transport import open_transport

    console = Console()

    def _snap(block) -> dict:
        active_eq = sum(
            1 for b in block.eq_bands if b.gain_db is not None and abs(b.gain_db) > 0.05
        )
        return {
            "speaker": block.speaker_type_byte,
            "gain": round(block.gain_db, 1),
            "delay": round(block.delay_ms, 2),
            "hpf_hz": block.hpf_freq_hz,
            "hpf_slope": block.hpf_slope_byte,
            "hpf_type": block.hpf_type_byte,
            "lpf_hz": block.lpf_freq_hz,
            "lpf_slope": block.lpf_slope_byte,
            "lpf_type": block.lpf_type_byte,
            "eq_active": active_eq,
        }

    def _slope_type(slope: int, ftype: int) -> str:
        return (
            f"{_SLOPE_NAMES.get(slope, f'0x{slope:02x}')} "
            f"{FILTER_TYPE_NAMES.get(ftype, f'0x{ftype:02x}')[:2]}"
        )

    def _spk(code: int) -> str:
        return SPEAKER_TYPE_NAMES.get(code, f"0x{code:02x}").split()[0]

    def _table(snaps: dict, changed: set) -> Table:
        t = Table(title="OctaPro Live Monitor  (Ctrl-C to stop)")
        t.add_column("CH", width=3)
        t.add_column("Spk", width=4)
        t.add_column("Gain", width=7, justify="right")
        t.add_column("Delay", width=8, justify="right")
        t.add_column("HPF Hz", width=9)
        t.add_column("HPF slope", width=13)
        t.add_column("LPF Hz", width=9)
        t.add_column("LPF slope", width=13)
        t.add_column("EQ", width=3, justify="right")
        for ch, s in sorted(snaps.items()):
            style = "bold green" if ch in changed else ""
            lpf = "bypass" if abs(s["lpf_hz"] - LPF_BYPASS_HZ) < 100 else f"{s['lpf_hz']:.1f}"
            t.add_row(
                str(ch),
                _spk(s["speaker"]),
                f"{s['gain']:+.1f}",
                f"{s['delay']:.2f}",
                f"{s['hpf_hz']:.1f}",
                _slope_type(s["hpf_slope"], s["hpf_type"]),
                lpf,
                _slope_type(s["lpf_slope"], s["lpf_type"]),
                str(s["eq_active"]),
                style=style,
            )
        return t

    try:
        with open_transport() as t:
            t.start_keepalive()
            snaps: dict[int, dict] = {}
            changed: set[int] = set()
            with Live(console=console, refresh_per_second=4) as live:
                while True:
                    changed.clear()
                    for ch in range(1, 11):
                        pkt = build_read_channel(ch)
                        resp = t.transact(bytes(pkt))
                        block = parse_channel_block(InPacket(resp).data, ch=ch, warn=warn_unknown)
                        snap = _snap(block)
                        if ch in snaps and snap != snaps[ch]:
                            changed.add(ch)
                            log.info("CH%d changed: %s", ch, snap)
                        snaps[ch] = snap
                    live.update(_table(snaps, changed))
                    time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\nMonitor stopped.")
    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0
