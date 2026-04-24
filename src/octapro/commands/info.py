import logging

from octapro import __version__

log = logging.getLogger("octapro.info")


def run_info(no_keepalive: bool = False) -> int:
    from rich.console import Console
    from rich.table import Table

    from octapro.logging import log_packet_in, log_packet_out, research, warn_unknown
    from octapro.protocol.constants import REG_FIRMWARE, REG_INIT
    from octapro.protocol.packet import InPacket, build_write_param
    from octapro.transport.hid import HidTransport

    console = Console()

    try:
        with HidTransport() as t:
            research("session_start", app_version=__version__)

            # Init param (CMD 0x04 reg=0x9909)
            pkt = build_write_param(0x00B0, REG_INIT)
            log_packet_out(0x04, 0x00B0, REG_INIT, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            ip = InPacket(resp)
            if not ip.status_known:
                warn_unknown("in_status", f"0x{ip.status:04x}", "after REG_INIT")

            # Read firmware string (CMD 0x04 reg=0x80f0)
            pkt = build_write_param(0x00B0, REG_FIRMWARE)
            log_packet_out(0x04, 0x00B0, REG_FIRMWARE, bytes(pkt))
            resp = t.transact(bytes(pkt))
            log_packet_in(resp)
            firmware = resp[9:60].decode("ascii", errors="replace").rstrip("\x00").strip()
            research("version_banner", firmware=firmware, app_version=__version__)
            log.info("Firmware: %s", firmware)

            if not no_keepalive:
                t.start_keepalive()

            table = Table(title="OctaPro Device Info", show_header=False)
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Firmware", firmware)
            table.add_row("VID", "0x8888")
            table.add_row("PID", "0x1234")
            table.add_row("octaproctl version", __version__)
            console.print(table)

    except Exception as exc:
        log.error("%s", exc)
        return 1
    return 0
