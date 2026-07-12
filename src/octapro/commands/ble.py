"""BLE discovery and pairing — `octaproctl ble scan` / `ble connect`.

Uses `bleak` directly (lazy import) rather than `BleTransport`, since
scanning is inherently different from device I/O (no session-open, no
`transact()`). Distilled from `scripts/ble_scan.py`.
"""

import logging
from typing import Any

log = logging.getLogger("octapro.ble")


def _import_bleak() -> Any:
    try:
        import bleak
    except ImportError as e:
        raise ImportError(
            "The 'bleak' package is not installed.\n"
            "  Install the BLE extra:  uv sync --extra ble"
        ) from e
    return bleak


async def _scan(bleak: Any, seconds: float) -> list[Any]:
    found = await bleak.BleakScanner.discover(timeout=seconds, return_adv=True)
    return sorted(found.items(), key=lambda kv: kv[1][1].rssi or -999, reverse=True)


def run_ble_scan(seconds: float = 8.0, show_all: bool = False) -> int:
    import asyncio

    from rich.console import Console
    from rich.table import Table

    from octapro.config import DEFAULT_BLE_NAME

    console = Console()
    try:
        bleak = _import_bleak()
    except ImportError as exc:
        log.error("%s", exc)
        return 1

    console.print(f"Scanning {seconds:.0f}s for BLE peripherals...")
    try:
        results = asyncio.run(_scan(bleak, seconds))
    except Exception as exc:
        log.error("Scan failed: %s", exc)
        return 1

    table = Table(title="BLE peripherals")
    table.add_column("")
    table.add_column("Name")
    table.add_column("Address")
    table.add_column("RSSI", justify="right")
    hits: list[str] = []
    for _addr, (dev, adv) in results:
        name = adv.local_name or dev.name or "(no name)"
        is_target = name == DEFAULT_BLE_NAME
        if not (show_all or is_target):
            continue
        if is_target:
            hits.append(dev.address)
        table.add_row(
            "*" if is_target else " ",
            name,
            dev.address,
            f"{adv.rssi}" if adv.rssi is not None else "?",
        )
    console.print(table)

    if not hits:
        suffix = "" if show_all else " Re-run with --all to list every peripheral."
        console.print(f"[yellow]{DEFAULT_BLE_NAME!r} not found.[/yellow]{suffix}")
        return 2
    console.print(
        f"Found {DEFAULT_BLE_NAME!r}. Use `octaproctl ble connect {hits[0]}`, "
        "or `octaproctl ble connect` to pick interactively."
    )
    return 0


def run_ble_connect(address: str | None = None, seconds: float = 8.0) -> int:
    import asyncio

    from rich.console import Console

    from octapro.config import DEFAULT_BLE_NAME, load_config, save_config

    console = Console()
    try:
        bleak = _import_bleak()
    except ImportError as exc:
        log.error("%s", exc)
        return 1

    name = DEFAULT_BLE_NAME
    if address is None:
        console.print(f"Scanning {seconds:.0f}s for BLE peripherals...")
        try:
            results = asyncio.run(_scan(bleak, seconds))
        except Exception as exc:
            log.error("Scan failed: %s", exc)
            return 1

        candidates = [
            (dev.address, adv.local_name or dev.name or "(no name)", adv.rssi)
            for _addr, (dev, adv) in results
        ]
        if not candidates:
            log.error("No BLE peripherals found. Is the device powered on and in range?")
            return 1
        for i, (addr, cand_name, rssi) in enumerate(candidates, start=1):
            console.print(f"  {i}) {cand_name}   {addr}   {rssi} dBm")
        choice = console.input("Select a device number: ").strip()
        try:
            idx = int(choice)
            if not 1 <= idx <= len(candidates):
                raise ValueError
        except ValueError:
            log.error("Invalid selection: %r", choice)
            return 1
        address, name, _ = candidates[idx - 1]

    cfg = load_config()
    cfg.transport = "ble"
    cfg.ble.address = address
    if name:
        cfg.ble.name = name
    path = save_config(cfg)
    console.print(f"[green]Saved[/green] transport=ble address={address!r} -> {path}")
    return 0
