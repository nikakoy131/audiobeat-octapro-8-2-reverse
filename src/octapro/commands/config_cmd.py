"""`octaproctl config show|path|set-transport` — inspect/manage the saved
transport config (see `octapro.config`)."""

import logging
from typing import cast

log = logging.getLogger("octapro.config")


def run_config_show() -> int:
    from rich.console import Console
    from rich.table import Table

    from octapro.config import config_path, load_config
    from octapro.transport import resolve

    console = Console()
    cfg = load_config()
    resolved = resolve()

    table = Table(title="octaproctl config", show_header=False)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Config file", str(config_path()))
    table.add_row("Saved transport", cfg.transport)
    table.add_row("Effective transport", resolved.kind)
    if resolved.kind == "ble":
        table.add_row(
            "BLE address", resolved.address or "(none — resolved by name at connect time)"
        )
        table.add_row("BLE name", cfg.ble.name)
    else:
        table.add_row("USB device index", str(resolved.device_index))
    console.print(table)
    return 0


def run_config_path() -> int:
    from octapro.config import config_path

    print(config_path())
    return 0


def run_config_set_transport(transport: str) -> int:
    from octapro.config import TransportKind, load_config, save_config

    transport = transport.strip().lower()
    if transport not in ("usb", "ble"):
        log.error("transport must be 'usb' or 'ble', got %r", transport)
        return 1
    cfg = load_config()
    cfg.transport = cast(TransportKind, transport)
    path = save_config(cfg)
    log.info("Saved transport=%s -> %s", transport, path)
    return 0
