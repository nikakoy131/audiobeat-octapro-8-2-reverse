import logging
import time

log = logging.getLogger("octapro.monitor")

_SLOPE_NAMES = {0x03: "12 dB/oct", 0x05: "36 dB/oct"}


def run_monitor(interval: float = 0.5) -> int:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    from octapro.logging import warn_unknown
    from octapro.protocol.channel import parse_channel_block
    from octapro.protocol.constants import LPF_BYPASS_HZ
    from octapro.protocol.packet import InPacket, build_read_channel
    from octapro.transport.hid import HidTransport

    console = Console()

    def _snap(block) -> dict:
        return {
            "hpf_hz": block.hpf_freq_hz,
            "hpf_slope": block.hpf_slope_byte,
            "lpf_hz": block.lpf_freq_hz,
            "lpf_slope": block.lpf_slope_byte,
        }

    def _table(snaps: dict, changed: set) -> Table:
        t = Table(title="OctaPro Live Monitor  (Ctrl-C to stop)")
        t.add_column("CH", width=3)
        t.add_column("HPF Hz", width=9)
        t.add_column("HPF slope", width=11)
        t.add_column("LPF Hz", width=9)
        t.add_column("LPF slope", width=11)
        for ch, s in sorted(snaps.items()):
            style = "bold green" if ch in changed else ""
            lpf = "bypass" if abs(s["lpf_hz"] - LPF_BYPASS_HZ) < 100 else f"{s['lpf_hz']:.1f}"
            t.add_row(
                str(ch),
                f"{s['hpf_hz']:.1f}",
                _SLOPE_NAMES.get(s["hpf_slope"], f"0x{s['hpf_slope']:02x}"),
                lpf,
                _SLOPE_NAMES.get(s["lpf_slope"], f"0x{s['lpf_slope']:02x}"),
                style=style,
            )
        return t

    try:
        with HidTransport() as t:
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
