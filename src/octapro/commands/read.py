import logging

log = logging.getLogger("octapro.read")

_SLOPE_NAMES = {0x03: "12 dB/oct", 0x05: "36 dB/oct"}


def run_read_channel(channel: str, no_keepalive: bool = False) -> int:
    from octapro.transport.hid import HidTransport

    try:
        channels = list(range(1, 11)) if channel.lower() == "all" else [int(channel)]
    except ValueError:
        log.error("channel must be 1-10 or 'all', got %r", channel)
        return 1
    if any(not 1 <= c <= 10 for c in channels):
        log.error("channel must be 1-10")
        return 1

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            for ch in channels:
                _read_and_print(t, ch)
    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0


def run_read_master(no_keepalive: bool = False) -> int:
    from rich.console import Console

    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.packet import InPacket, build_read_channel
    from octapro.transport.hid import HidTransport

    console = Console()
    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            pkt = build_read_channel(0)
            log_packet_out(0x05, 0x00B0, 0x04 << 8, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            ip = InPacket(resp)
            console.print(
                f"[bold]Master (CH0)[/] status=0x{ip.status:04x} dlen={ip.data_len}  "
                f"data[0:16]: {ip.data[:16].hex()}"
            )
    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0


def _read_and_print(transport, ch: int) -> None:
    from rich.console import Console
    from rich.table import Table

    from octapro.logging import log_packet_in, log_packet_out, warn_unknown
    from octapro.protocol.channel import parse_channel_block
    from octapro.protocol.constants import LPF_BYPASS_HZ
    from octapro.protocol.packet import InPacket, build_read_channel

    console = Console()
    pkt = build_read_channel(ch)
    log_packet_out(0x05, 0x00B0, (0x04 << 8) | ch, bytes(pkt))
    resp = transport.transact(bytes(pkt))
    log_packet_in(resp)

    ip = InPacket(resp)
    block = parse_channel_block(ip.data, ch=ch, warn=warn_unknown)

    lpf_str = (
        "bypass"
        if abs(block.lpf_freq_hz - LPF_BYPASS_HZ) < 100
        else f"{block.lpf_freq_hz:.1f} Hz"
    )
    hpf_str = f"{block.hpf_freq_hz:.1f} Hz"
    active_eq = [b for b in block.eq_bands if b.gain_db is not None and abs(b.gain_db) > 0.05]

    table = Table(title=f"Channel {ch}", show_header=False, min_width=40)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("HPF freq", hpf_str)
    table.add_row(
        "HPF slope",
        _SLOPE_NAMES.get(block.hpf_slope_byte, f"0x{block.hpf_slope_byte:02x} (unknown)"),
    )
    table.add_row("LPF freq", lpf_str)
    table.add_row(
        "LPF slope",
        _SLOPE_NAMES.get(block.lpf_slope_byte, f"0x{block.lpf_slope_byte:02x} (unknown)"),
    )
    table.add_row("EQ active bands", f"{len(active_eq)}" + ("" if active_eq else "  (flat)"))
    console.print(table)
