import logging
import struct

log = logging.getLogger("octapro.dump")


def run_dump_channel(channel: int, annotate: bool = False, no_keepalive: bool = False) -> int:
    from rich import box
    from rich.console import Console
    from rich.table import Table

    from octapro.logging import log_packet_in, log_packet_out
    from octapro.protocol.packet import InPacket, build_read_channel
    from octapro.transport.hid import HidTransport

    console = Console()
    try:
        with HidTransport() as t:
            if not no_keepalive:
                t.start_keepalive()
            pkt = build_read_channel(channel)
            log_packet_out(0x05, 0x00B0, (0x04 << 8) | channel, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
    except Exception as exc:
        log.error("%s", exc)
        return 1

    data = InPacket(resp).data

    if annotate:
        table = Table(title=f"CH{channel} block — annotated", box=box.SIMPLE_HEAD)
        table.add_column("Bytes", style="dim")
        table.add_column("Hex")
        table.add_column("Meaning")
        for off, hex_str, meaning in _annotate(data):
            table.add_row(off, hex_str, meaning)
        console.print(table)
    else:
        console.print(f"[bold]CH{channel} raw block ({len(data)} bytes)[/]")
        for i in range(0, len(data), 16):
            row = data[i : i + 16]
            console.print(f"  {i:3d}  " + " ".join(f"{b:02x}" for b in row))

    return 0


def _f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0] if off + 4 <= len(data) else 0.0


def _annotate(data: bytes) -> list[tuple[str, str, str]]:
    def _h(s: int, e: int) -> str:
        return data[s:e].hex() if e <= len(data) else "???"

    def _b(i: int) -> str:
        return f"0x{data[i]:02x}" if i < len(data) else "???"

    return [
        ("0", _b(0), "prefix (expect 0x00)"),
        ("1:33", _h(1, 33), "routing matrix (32 bytes signed-int8 /10.0 dB)"),
        ("33:39", _h(33, 39), "UNKNOWN (6 bytes)"),
        ("39:43", _h(39, 43), f"HPF freq float32 = {_f32(data, 39):.2f} Hz"),
        ("43", _b(43), "HPF slope code  (0x05=36 dB/oct, 0x03=12 dB/oct)"),
        ("44", _b(44), "UNKNOWN byte"),
        ("45:49", _h(45, 49), f"LPF freq float32 = {_f32(data, 45):.2f} Hz"),
        ("49", _b(49), "LPF slope code"),
        ("50:52", _h(50, 52), "UNKNOWN flags"),
        ("52", _b(52), "EQ section marker (expect 0x06)"),
        ("53:239", f"[{len(data[53:239])} bytes]", "EQ block: 31 bands × 6 bytes"),
        ("239", _b(239), "trailing byte (varies per channel)"),
        ("240:242", _h(240, 242), "padding zeros"),
    ]
