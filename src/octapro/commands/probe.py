import logging

log = logging.getLogger("octapro.probe")


def run_probe(hex_bytes: str, commit: bool) -> int:
    from rich.console import Console

    from octapro.logging import log_packet_in, log_packet_out

    console = Console()
    raw_hex = hex_bytes.replace(" ", "").replace(":", "")
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError as exc:
        log.error("Invalid hex input: %s", exc)
        return 1

    if len(raw) != 256:
        log.error("Packet must be exactly 256 bytes, got %d", len(raw))
        return 1

    console.print(f"[bold]Probe packet ({len(raw)} bytes):[/bold]")
    for i in range(0, 32, 16):
        row = raw[i : i + 16]
        console.print("  " + " ".join(f"{b:02x}" for b in row))
    console.print("  …")

    if not commit:
        console.print("\n[yellow]DRY RUN[/yellow] — packet not sent. Add --commit to transmit.")
        return 0

    from octapro.transport.hid import HidTransport

    try:
        with HidTransport() as t:
            cmd = raw[2]
            addr = int.from_bytes(raw[4:6], "little")
            sub = int.from_bytes(raw[6:8], "little")
            log_packet_out(cmd, addr, sub, raw)
            resp = t.transact(raw)
            log_packet_in(resp)
            status = int.from_bytes(resp[:2], "little")
            console.print(f"\n[bold]IN response[/bold]: status=0x{status:04x}  {resp[:16].hex()}…")
    except Exception as exc:
        log.error("Probe failed: %s", exc)
        return 1
    return 0
