import logging

log = logging.getLogger("octapro.write")


def _dry_run_print(intent: str, pkt: bytes) -> None:
    from rich.console import Console

    console = Console()
    console.print(f"[bold yellow]DRY RUN[/bold yellow]  {intent}")
    console.print("[dim]No packet sent. Add --commit to actually write to the device.[/dim]\n")
    console.print("[bold]OUT packet (256 bytes):[/bold]")
    for i in range(0, min(64, len(pkt)), 16):
        row = pkt[i : i + 16]
        ann = ""
        if i == 0:
            ann = f"  ← magic={pkt[0]:02x}{pkt[1]:02x} cmd=0x{pkt[2]:02x}"
        elif i == 16:
            ann = ""
        console.print("  " + " ".join(f"{b:02x}" for b in row) + ann)
    if len(pkt) > 64:
        console.print("  … (rest zeros)")


def run_write_hpf(
    channel: int,
    freq: float,
    slope: int,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out, warn_unknown
    from octapro.protocol.constants import KNOWN_SLOPES, SUB_HPF_FREQ, TYPE_HPF
    from octapro.protocol.packet import build_dsp_commit, build_write_dsp, channel_addr

    if slope not in KNOWN_SLOPES:
        warn_unknown(
            "hpf_slope_code",
            f"0x{slope:02x}",
            f"write hpf ch={channel} — unverified, proceed with caution",
        )

    addr = channel_addr(channel)
    pkt = build_write_dsp(
        addr=addr, sub_byte=SUB_HPF_FREQ, float_val=freq, param_byte=slope, type_byte=TYPE_HPF
    )
    intent = f"CH{channel} HPF → {freq:.1f} Hz  slope=0x{slope:02x} ({slope})"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(0x0A, addr, SUB_HPF_FREQ, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)

            commit_pkt = build_dsp_commit(channel)
            log_packet_out(0x05, addr, 0x01, bytes(commit_pkt))
            resp2 = t.transact(bytes(commit_pkt))
            log_packet_in(resp2)

            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_gain(
    channel: int,
    db: float,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import SUB_GAIN, TYPE_GAIN, WRITE_DSP_GAIN_FLOAT_REF
    from octapro.protocol.gain import db_to_byte
    from octapro.protocol.packet import build_dsp_commit, build_write_dsp, channel_addr

    addr = channel_addr(channel)
    gain_byte = db_to_byte(db)
    pkt = build_write_dsp(
        addr=addr,
        sub_byte=SUB_GAIN,
        float_val=WRITE_DSP_GAIN_FLOAT_REF,
        param_byte=gain_byte,
        type_byte=TYPE_GAIN,
    )
    intent = f"CH{channel} GAIN → {db:+.1f} dB  (byte=0x{gain_byte:02x})"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(0x0A, addr, SUB_GAIN, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)

            commit_pkt = build_dsp_commit(channel)
            resp2 = t.transact(bytes(commit_pkt))
            log_packet_in(resp2)

            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0
