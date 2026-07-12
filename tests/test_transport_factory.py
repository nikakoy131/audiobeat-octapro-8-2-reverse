"""Offline tests for octapro.transport (the open_transport() factory).

Verifies transport selection without ever opening a device, and confirms
BleTransport can be constructed with `bleak` absent (its import is lazy,
deferred to open()) — so this file must pass without the `ble` extra
installed, exactly like the rest of the offline test suite.
"""

import octapro.transport as transport_mod
from octapro.transport import open_transport, resolve, set_override
from octapro.transport.ble import BleTransport
from octapro.transport.hid import HidTransport


class TestOpenTransportFactory:
    def teardown_method(self):
        set_override(None, None)  # don't leak overrides across tests

    def test_default_no_config_no_override_returns_hid(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "octapro.config.config_path", lambda: tmp_path / "no-such-config.json"
        )
        set_override(None, None)
        t = open_transport()
        assert isinstance(t, HidTransport)

    def test_override_selects_ble_without_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "octapro.config.config_path", lambda: tmp_path / "no-such-config.json"
        )
        set_override("ble", "AA:BB")
        t = open_transport()
        assert isinstance(t, BleTransport)
        assert t._address == "AA:BB"

    def test_override_selects_usb_and_clears_after(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "octapro.config.config_path", lambda: tmp_path / "no-such-config.json"
        )
        set_override("usb", None)
        assert isinstance(open_transport(), HidTransport)
        set_override(None, None)
        resolved = resolve()
        assert resolved.kind == "usb"  # falls back to default, no lingering override

    def test_ble_transport_constructs_without_bleak_installed(self):
        # bleak is only imported lazily inside BleTransport.open(); merely
        # constructing the instance must not require the `ble` extra.
        t = BleTransport(address="some-address")
        assert t._address == "some-address"

    def test_set_override_module_state(self):
        set_override("ble", "xyz")
        assert transport_mod._override_transport == "ble"
        assert transport_mod._override_address == "xyz"
        set_override(None, None)
        assert transport_mod._override_transport is None
