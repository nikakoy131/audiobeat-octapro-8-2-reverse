import logging

log = logging.getLogger("octapro.read")

_SLOPE_NAMES = {0x03: "12 dB/oct", 0x05: "36 dB/oct"}

# EQ bar meter: diverging around 0 dB, ±12.8 dB = encoding limit of the gain byte
_EQ_MAX_DB = 12.8
_EQ_HALF_CELLS = 12


def _fmt_freq(hz: float) -> str:
    return f"{hz / 1000:g}k" if hz >= 1000 else f"{hz:g}"


def _eq_bar(gain_db: float | None):
    """Exact-width Text bar: cut extends left (red), boost right (cyan), dim 0-line.

    Built as rich.Text, not markup — Rich trims trailing spaces off markup
    strings before justifying, which would drift the 0-line off center.
    """
    from rich.text import Text

    h = _EQ_HALF_CELLS
    t = Text()
    if gain_db is None:
        t.append(" " * h)
        t.append("✕", style="red bold")
        t.append(" " * h)
        return t
    cells = min(h, round(abs(gain_db) / _EQ_MAX_DB * h))
    if gain_db > 0 and cells:
        t.append(" " * h)
        t.append("│", style="dim")
        t.append("█" * cells, style="cyan")
        t.append(" " * (h - cells))
    elif gain_db < 0 and cells:
        t.append(" " * (h - cells))
        t.append("█" * cells, style="red")
        t.append("│", style="dim")
        t.append(" " * h)
    else:
        t.append(" " * h)
        t.append("│", style="dim")
        t.append(" " * h)
    return t


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
            # single-channel read gets the full 31-band EQ meter
            show_eq = len(channels) == 1
            for ch in channels:
                _read_and_print(t, ch, show_eq=show_eq)
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


def run_read_volume(no_keepalive: bool = False) -> int:
    from rich.console import Console
    from rich.table import Table

    from octapro.logging import log_packet_in, log_packet_out, warn_unknown
    from octapro.protocol.constants import REG_KEEPALIVE, STATUS_KEEPALIVE
    from octapro.protocol.packet import InPacket, build_keepalive, parse_keepalive_volume
    from octapro.transport.hid import HidTransport

    console = Console()
    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            pkt = build_keepalive()
            log_packet_out(0x04, 0x00B0, REG_KEEPALIVE, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            ip = InPacket(resp)
            if ip.status != STATUS_KEEPALIVE:
                warn_unknown("in_status", f"0x{ip.status:04x}", "keepalive for volume read")
            volume_db, trailer_ok = parse_keepalive_volume(resp)
            if not trailer_ok:
                warn_unknown(
                    "keepalive_trailer",
                    f"0x{resp[16]:02x}",
                    f"expected (sum(resp[8:16])-0x70)&0xff = "
                    f"0x{(sum(resp[8:16]) - 0x70) & 0xFF:02x}",
                )
            table = Table(title="Main Volume", show_header=False, min_width=40)
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Main volume", f"{volume_db:+.2f} dB")
            table.add_row("Range", "−60.0 … +6.0 dB (remote knob 0–35)")
            table.add_row("Raw float32", resp[12:16].hex(" "))
            console.print(table)
    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0


def _read_and_print(transport, ch: int, show_eq: bool = False) -> None:
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

    if show_eq:
        _print_eq_table(console, ch, block.eq_bands)


def _print_eq_table(console, ch: int, bands) -> None:
    from rich.table import Table

    table = Table(
        title=f"Channel {ch} — 31-band EQ",
        caption="Q ≈ q_byte / 10 — encoding hypothesis, unverified (PROTOCOL.md)",
        caption_justify="right",
    )
    # header is exactly bar-width (2*half+1) with "0" above the center line
    h = _EQ_HALF_CELLS
    bar_header = f"−{_EQ_MAX_DB:g}".ljust(h) + "0" + f"+{_EQ_MAX_DB:g}".rjust(h)
    table.add_column("#", justify="right", style="bold")
    table.add_column("Freq", justify="right")
    table.add_column(bar_header, justify="left", no_wrap=True)
    table.add_column("Gain", justify="right")
    table.add_column("Q", justify="right")

    for b in bands:
        flat = b.gain_db is not None and abs(b.gain_db) <= 0.05
        gain_str = "MUTE" if b.gain_db is None else f"{b.gain_db:+.1f}"
        q_str = f"0x{b.q_byte:02x} (≈{b.q_byte / 10:.1f})"
        style = "dim" if flat else ""
        table.add_row(
            str(b.index + 1), _fmt_freq(b.freq_hz), _eq_bar(b.gain_db),
            gain_str, q_str, style=style,
        )
    console.print(table)
