"""Persistent transport selection — which link (USB or BLE) `octaproctl` talks
to the device over, and its address, so commands don't need a flag on every
invocation.

Config file (JSON), one per user, following the same per-OS convention as the
research log (see `logging.py:default_research_log_path`):
    macOS:  ~/Library/Application Support/octapro/config.json
    Linux:  ${XDG_CONFIG_HOME:-~/.config}/octapro/config.json

Precedence for the *effective* transport on any command: an explicit
`--transport`/`--address` CLI override > the saved config > default ("usb").
`octapro.transport.resolve()` applies this; see README.md "Transports".
"""

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, cast

TransportKind = Literal["usb", "ble"]

DEFAULT_BLE_NAME = "AB OctaPro BLE"


@dataclass
class BleConfig:
    address: str | None = None
    name: str = DEFAULT_BLE_NAME


@dataclass
class UsbConfig:
    device_index: int = 0


@dataclass
class Config:
    transport: TransportKind = "usb"
    ble: BleConfig = field(default_factory=BleConfig)
    usb: UsbConfig = field(default_factory=UsbConfig)


@dataclass
class ResolvedTransport:
    kind: TransportKind
    address: str | None  # BLE address/name; unused for USB
    device_index: int  # USB device index; unused for BLE


def config_path() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "octapro" / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "octapro" / "config.json"


def load_config(path: Path | None = None) -> Config:
    """Load the saved config, or defaults (transport=usb) if none exists/is invalid."""
    p = path or config_path()
    if not p.exists():
        return Config()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Config()
    ble_raw = raw.get("ble") or {}
    usb_raw = raw.get("usb") or {}
    ble = BleConfig(
        address=ble_raw.get("address"), name=ble_raw.get("name", DEFAULT_BLE_NAME)
    )
    usb = UsbConfig(device_index=usb_raw.get("device_index", 0))
    transport = raw.get("transport", "usb")
    if transport not in ("usb", "ble"):
        transport = "usb"
    return Config(transport=cast(TransportKind, transport), ble=ble, usb=usb)


def save_config(cfg: Config, path: Path | None = None) -> Path:
    """Write `cfg` as JSON to `path` (or the default config path)."""
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")
    return p


def resolve_transport(
    override_transport: str | None = None,
    override_address: str | None = None,
    cfg: Config | None = None,
) -> ResolvedTransport:
    """Effective transport selection: CLI override > saved config > default (usb)."""
    cfg = cfg or load_config()
    kind = override_transport or cfg.transport
    if kind not in ("usb", "ble"):
        raise ValueError(f"transport must be 'usb' or 'ble', got {kind!r}")
    if kind == "ble":
        address = override_address or cfg.ble.address
        return ResolvedTransport(kind="ble", address=address, device_index=cfg.usb.device_index)
    return ResolvedTransport(
        kind="usb", address=override_address, device_index=cfg.usb.device_index
    )
