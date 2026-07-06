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


def run_write_crossover(
    kind: str,       # "hpf" or "lpf"
    channel: int,
    freq: float,
    slope_db: int,
    filter_type: str,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    """HPF/LPF write (CMD 0x0a sub 0x05/0x06): freq + slope (dB/oct) + type.

    Live-verified 2026-07-06 (ch8). No commit packet is sent — the app applies
    these immediately (the old build_dsp_commit step is now known to be a
    per-channel unmute, not a required commit; see PROTOCOL.md).
    """
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import (
        SUB_HPF_FREQ,
        SUB_LPF_FREQ,
        filter_type_code,
    )
    from octapro.protocol.packet import build_hpf, build_lpf, channel_addr

    try:
        ftype = filter_type_code(filter_type)
    except ValueError as exc:
        log.error("%s", exc)
        return 1
    try:
        build = build_hpf if kind == "hpf" else build_lpf
        pkt = build(channel, freq, slope_db, ftype)
    except ValueError as exc:
        log.error("%s", exc)
        return 1

    sub = SUB_HPF_FREQ if kind == "hpf" else SUB_LPF_FREQ
    intent = f"CH{channel} {kind.upper()} → {freq:.1f} Hz, {slope_db} dB/oct, {filter_type}"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(0x0A, channel_addr(channel), sub, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
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
    """Channel output fader/gain, ch=1..10 (CMD 0x08 sub 0x03).

    ch=0 is rejected — the master fader is `write master`. This is the
    command the vendor app actually sends for channel faders (live-verified
    CH3 → -6.0 dB, 2026-07-06), replacing the old CMD 0x0a WRITE_DSP guess.
    """
    if channel == 0:
        log.error("ch=0 is the master fader — use `write master --db <value>` instead.")
        return 1

    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_WRITE_MASTER_VOLUME, SUB_CHANNEL_GAIN
    from octapro.protocol.packet import build_channel_gain, channel_addr

    pkt = build_channel_gain(channel, db)
    intent = f"CH{channel} FADER → {db:+.2f} dB"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(
                CMD_WRITE_MASTER_VOLUME, channel_addr(channel), SUB_CHANNEL_GAIN, bytes(pkt)
            )
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_mute(
    channel: int,
    mute: bool,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_READ_BLOCK
    from octapro.protocol.packet import build_mute, channel_addr

    pkt = build_mute(channel, mute)
    label = "MASTER" if channel == 0 else f"CH{channel}"
    intent = f"{label} MUTE → {'ON' if mute else 'OFF'}"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(CMD_READ_BLOCK, channel_addr(channel), pkt[6], bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def solo_packets(channel: int, solo: bool) -> list[tuple[int, bytes]]:
    """The mute packets the vendor app sends for solo of `channel`.

    Solo is a client-side macro: mute (solo on) / unmute (solo off) every
    channel EXCEPT the soloed one. Returns [(ch, packet), ...] in channel order.
    """
    from octapro.protocol.constants import NUM_CHANNELS
    from octapro.protocol.packet import build_mute

    return [
        (ch, bytes(build_mute(ch, solo)))
        for ch in range(1, NUM_CHANNELS + 1)
        if ch != channel
    ]


def run_write_solo(
    channel: int,
    solo: bool,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    """Solo a channel (CH1..10).

    Solo is NOT a device command — live capture (2026-07-06) proved the vendor
    app implements it purely client-side as "mute every OTHER channel":
        solo ON  CHn  -> build_mute(other, on=True)  for every ch != n
        solo OFF CHn  -> build_mute(other, on=False) for every ch != n
    The app does not remember prior mute state; solo-off blindly unmutes the
    others. This command reproduces that macro over the existing mute write.
    """
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_READ_BLOCK, NUM_CHANNELS
    from octapro.protocol.packet import channel_addr

    if not 1 <= channel <= NUM_CHANNELS:
        log.error("solo channel must be 1..%d, got %d", NUM_CHANNELS, channel)
        return 1

    packets = solo_packets(channel, solo)
    others = [ch for ch, _ in packets]
    verb = "MUTE" if solo else "UNMUTE"
    intent = (
        f"SOLO CH{channel} {'ON' if solo else 'OFF'} "
        f"→ {verb} CH{{{','.join(str(c) for c in others)}}}"
    )

    if not commit:
        _dry_run_print(intent, bytes(packets[0][1]))
        from rich.console import Console

        Console().print(
            f"[dim]…plus {len(packets) - 1} more identical mute packets for the "
            f"other channels ({verb.lower()}).[/dim]"
        )
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            for ch, pkt in packets:
                log_packet_out(CMD_READ_BLOCK, channel_addr(ch), pkt[6], bytes(pkt))
                resp = t.transact(bytes(pkt))
                log_packet_in(resp)
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_eq(
    channel: int,
    band: int,
    db: float,
    q: float,
    freq: float | None,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_WRITE_DSP, EQ_BAND_CENTERS_HZ
    from octapro.protocol.packet import build_eq_band, channel_addr

    pkt = build_eq_band(channel, band, gain_db=db, freq_hz=freq, q=q)
    eff_freq = freq if freq is not None else EQ_BAND_CENTERS_HZ[band - 1]
    intent = f"CH{channel} EQ band {band} → {eff_freq:g} Hz, {db:+.1f} dB, Q {q:.1f}"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(CMD_WRITE_DSP, channel_addr(channel), pkt[6], bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_delay(
    channel: int,
    ms: float,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_WRITE_MASTER_VOLUME, SUB_CHANNEL_DELAY
    from octapro.protocol.packet import build_channel_delay, channel_addr

    pkt = build_channel_delay(channel, ms)
    intent = f"CH{channel} DELAY → {ms:.3f} ms"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(
                CMD_WRITE_MASTER_VOLUME, channel_addr(channel), SUB_CHANNEL_DELAY, bytes(pkt)
            )
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_eq_pass(
    channel: int,
    bypass: bool,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_READ_BLOCK, SUB_EQ_PASS
    from octapro.protocol.packet import build_eq_pass, channel_addr

    pkt = build_eq_pass(channel, bypass)
    intent = f"CH{channel} EQ PASS → {'BYPASS' if bypass else 'ENGAGED'}"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(CMD_READ_BLOCK, channel_addr(channel), SUB_EQ_PASS, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_eq_reset(
    channel: int,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_READ_BLOCK, SUB_EQ_PASS
    from octapro.protocol.packet import build_eq_reset, channel_addr

    pkt = build_eq_reset(channel)
    intent = f"CH{channel} EQ RESET (flatten all bands)"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(CMD_READ_BLOCK, channel_addr(0), SUB_EQ_PASS, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_phase(
    channel: int,
    invert: bool,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_READ_BLOCK
    from octapro.protocol.packet import build_phase, channel_addr

    pkt = build_phase(channel, invert)
    intent = f"CH{channel} PHASE → {'180° (inverted)' if invert else '0° (normal)'}"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(CMD_READ_BLOCK, channel_addr(channel), pkt[6], bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_bridge(
    bridged: bool,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import CMD_BRIDGE, SUB_BRIDGE
    from octapro.protocol.packet import build_bridge, channel_addr

    pkt = build_bridge(bridged)
    intent = f"BRIDGE CH7+CH8 → {'ON' if bridged else 'OFF'}"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(CMD_BRIDGE, channel_addr(0), SUB_BRIDGE, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0


def run_write_master(
    db: float,
    commit: bool,
    no_keepalive: bool = False,
) -> int:
    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.constants import SUB_MASTER_VOLUME
    from octapro.protocol.packet import build_write_master_volume, channel_addr

    pkt = build_write_master_volume(db)
    intent = f"MASTER volume → {db:+.2f} dB"

    if not commit:
        _dry_run_print(intent, bytes(pkt))
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            log_packet_out(0x08, channel_addr(0), SUB_MASTER_VOLUME, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            # No separate commit observed for this command — applies immediately.
            log.info("Written: %s", intent)
    except Exception as exc:
        log.error("Write failed: %s", exc)
        return 1
    return 0
