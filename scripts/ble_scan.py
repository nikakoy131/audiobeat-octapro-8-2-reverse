#!/usr/bin/env python3
"""Scan for the OctaPro's BLE control peripheral (`AB OctaPro BLE`).

Part of the Bluetooth reverse-engineering effort (docs/findings/BLE.md). The
device also exposes control over Bluetooth LE for the WeChat mini-program; this
script confirms it is advertising and captures the details we need to connect:
the CoreBluetooth peripheral UUID (macOS gives a system UUID, not a MAC), RSSI,
and any advertised service UUIDs / manufacturer data.

Run:  uv run --extra ble python scripts/ble_scan.py [--seconds N] [--all]

macOS notes:
  * First BLE access prompts for Bluetooth permission for the *terminal app*
    hosting Python (System Settings -> Privacy & Security -> Bluetooth). If this
    prints zero devices with Bluetooth on, grant that permission and re-run.
  * The phone / WeChat app must be disconnected from the amp — a BLE peripheral
    usually accepts only one central at a time.
"""

from __future__ import annotations

import argparse
import asyncio

from bleak import BleakScanner

TARGET_NAME = "AB OctaPro BLE"


async def scan(seconds: float, show_all: bool) -> int:
    print(f"Scanning {seconds:.0f}s for BLE peripherals "
          f"(looking for {TARGET_NAME!r})...\n")
    # return_adv=True -> {address: (BLEDevice, AdvertisementData)}
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)

    if not found:
        print("No BLE peripherals seen at all. Check: Bluetooth on, terminal has "
              "Bluetooth permission, device powered.")
        return 1

    hits = 0
    for _addr, (dev, adv) in sorted(
        found.items(), key=lambda kv: kv[1][1].rssi or -999, reverse=True
    ):
        name = adv.local_name or dev.name or "(no name)"
        is_target = (name == TARGET_NAME)
        if not (show_all or is_target):
            continue
        hits += is_target
        mark = "  <== TARGET" if is_target else ""
        print(f"{'*' if is_target else '-'} {name}{mark}")
        print(f"    peripheral id : {dev.address}")   # CoreBluetooth UUID on macOS
        print(f"    rssi          : {adv.rssi} dBm")
        if adv.service_uuids:
            print(f"    service uuids : {', '.join(adv.service_uuids)}")
        if adv.manufacturer_data:
            md = {k: v.hex() for k, v in adv.manufacturer_data.items()}
            print(f"    manufacturer  : {md}")
        if adv.service_data:
            sd = {k: v.hex() for k, v in adv.service_data.items()}
            print(f"    service data  : {sd}")
        print()

    if not hits:
        print(f"{TARGET_NAME!r} not found. "
              f"{'' if show_all else 'Re-run with --all to list every peripheral.'}")
        return 2
    print(f"Found {TARGET_NAME!r}. Use the peripheral id above with ble_enum.py.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=8.0, help="scan duration")
    ap.add_argument("--all", action="store_true", help="list every peripheral, not just the target")
    args = ap.parse_args()
    return asyncio.run(scan(args.seconds, args.all))


if __name__ == "__main__":
    raise SystemExit(main())
