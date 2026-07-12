"""Transport factory — selects USB or BLE based on the effective config.

`open_transport()` is what every command should use instead of importing
`HidTransport` (or `BleTransport`) directly; it returns an *unopened*
transport instance chosen by `octapro.config.resolve_transport()` (CLI
`--transport`/`--address` override > saved config > default "usb"). The CLI
root callback stashes any per-invocation override via `set_override()` before
a subcommand runs — see `cli.py`.
"""

from octapro.config import ResolvedTransport, resolve_transport
from octapro.transport.base import Transport

_override_transport: str | None = None
_override_address: str | None = None


def set_override(transport: str | None, address: str | None) -> None:
    """Stash a per-invocation `--transport`/`--address` override (or clear it)."""
    global _override_transport, _override_address
    _override_transport = transport
    _override_address = address


def resolve() -> ResolvedTransport:
    """The effective transport selection: override > saved config > default."""
    return resolve_transport(_override_transport, _override_address)


def open_transport() -> Transport:
    """Construct (but do not open) the transport selected by config/override."""
    resolved = resolve()
    if resolved.kind == "ble":
        from octapro.transport.ble import BleTransport

        return BleTransport(address=resolved.address)
    from octapro.transport.hid import HidTransport

    return HidTransport(device_index=resolved.device_index)
