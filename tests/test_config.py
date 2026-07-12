"""Offline tests for octapro.config — no device, no filesystem outside tmp_path."""

import pytest

from octapro.config import (
    Config,
    load_config,
    resolve_transport,
    save_config,
)


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "does-not-exist.json")
        assert cfg.transport == "usb"
        assert cfg.ble.address is None
        assert cfg.usb.device_index == 0

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text("not json{{{")
        cfg = load_config(p)
        assert cfg.transport == "usb"

    def test_invalid_transport_value_falls_back_to_usb(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text('{"transport": "carrier-pigeon"}')
        cfg = load_config(p)
        assert cfg.transport == "usb"


class TestSaveLoadRoundtrip:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "sub" / "config.json"  # parent dir must be created
        cfg = Config()
        cfg.transport = "ble"
        cfg.ble.address = "AA:BB:CC:DD:EE:FF"
        cfg.ble.name = "AB OctaPro BLE"
        saved_path = save_config(cfg, p)
        assert saved_path == p
        assert p.exists()

        loaded = load_config(p)
        assert loaded.transport == "ble"
        assert loaded.ble.address == "AA:BB:CC:DD:EE:FF"
        assert loaded.ble.name == "AB OctaPro BLE"

    def test_partial_ble_block_fills_defaults(self, tmp_path):
        p = tmp_path / "config.json"
        p.write_text('{"transport": "ble", "ble": {"address": "1234"}}')
        cfg = load_config(p)
        assert cfg.ble.address == "1234"
        assert cfg.ble.name == "AB OctaPro BLE"  # default filled in


class TestResolveTransport:
    def test_default_is_usb(self, tmp_path):
        cfg = load_config(tmp_path / "missing.json")
        resolved = resolve_transport(cfg=cfg)
        assert resolved.kind == "usb"

    def test_config_selects_ble(self):
        cfg = Config(transport="ble")
        cfg.ble.address = "saved-addr"
        resolved = resolve_transport(cfg=cfg)
        assert resolved.kind == "ble"
        assert resolved.address == "saved-addr"

    def test_cli_override_beats_config(self):
        cfg = Config(transport="ble")
        cfg.ble.address = "saved-addr"
        resolved = resolve_transport(override_transport="usb", cfg=cfg)
        assert resolved.kind == "usb"

    def test_cli_address_override_beats_config(self):
        cfg = Config(transport="ble")
        cfg.ble.address = "saved-addr"
        resolved = resolve_transport(
            override_transport="ble", override_address="cli-addr", cfg=cfg
        )
        assert resolved.kind == "ble"
        assert resolved.address == "cli-addr"

    def test_ble_without_any_address_is_none(self):
        cfg = Config(transport="ble")
        resolved = resolve_transport(cfg=cfg)
        assert resolved.kind == "ble"
        assert resolved.address is None

    def test_invalid_override_raises(self):
        with pytest.raises(ValueError):
            resolve_transport(override_transport="carrier-pigeon", cfg=Config())
