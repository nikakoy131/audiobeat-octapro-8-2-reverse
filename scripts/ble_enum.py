#!/usr/bin/env python3
"""Connect to the OctaPro BLE peripheral and dump its GATT table.

Part of the Bluetooth reverse-engineering effort (docs/findings/BLE.md). The
scan (ble_scan.py) showed the device advertises the HID-over-GATT service
(0x1812), so the DSP control almost certainly rides the same report-based HID
model as USB. This prints every service, characteristic (with properties), and
descriptor so we can identify the report characteristic(s) that carry the
`e0 a2 ...` packets, and — crucially on macOS — confirm whether the OS lets us
see/write them at all (the HID service is sometimes claimed by the OS HID stack,
the BLE analogue of the USB interface-4 problem).

Run:  uv run --extra ble python scripts/ble_enum.py [--id UUID | --name NAME]

For HID report characteristics (0x2A4D) it also reads the Report Reference
descriptor (0x2908 -> report id + type: 1=input, 2=output, 3=feature) and, for
readable characteristics, the current value.
"""

from __future__ import annotations

import argparse
import asyncio

from bleak import BleakClient, BleakScanner

TARGET_NAME = "AB OctaPro BLE"

# Well-known GATT UUIDs we expect on a HOGP device, for friendly labels.
KNOWN = {
    "00001812-0000-1000-8000-00805f9b34fb": "HID Service",
    "00002a4a-0000-1000-8000-00805f9b34fb": "HID Information",
    "00002a4b-0000-1000-8000-00805f9b34fb": "HID Report Map",
    "00002a4c-0000-1000-8000-00805f9b34fb": "HID Control Point",
    "00002a4d-0000-1000-8000-00805f9b34fb": "HID Report",
    "00002a4e-0000-1000-8000-00805f9b34fb": "HID Protocol Mode",
    "00002a22-0000-1000-8000-00805f9b34fb": "Boot Keyboard Input",
    "00002a32-0000-1000-8000-00805f9b34fb": "Boot Keyboard Output",
    "0000180a-0000-1000-8000-00805f9b34fb": "Device Information",
    "0000180f-0000-1000-8000-00805f9b34fb": "Battery Service",
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery Level",
    "00002908-0000-1000-8000-00805f9b34fb": "Report Reference",
    "00002902-0000-1000-8000-00805f9b34fb": "Client Char Config (CCCD)",
}
REPORT_TYPE = {1: "input", 2: "output", 3: "feature"}


def label(uuid: str) -> str:
    return KNOWN.get(uuid.lower(), "")


async def resolve_address(id_: str | None, name: str | None) -> str | None:
    if id_:
        return id_
    want = name or TARGET_NAME
    print(f"Scanning for {want!r}...")
    dev = await BleakScanner.find_device_by_name(want, timeout=10.0)
    return dev.address if dev else None


async def enum(id_: str | None, name: str | None, args_read: bool) -> int:
    address = await resolve_address(id_, name)
    if not address:
        print("Target not found in scan. Pass --id <peripheral uuid> from ble_scan.py.")
        return 1

    print(f"Connecting to {address}...", flush=True)
    async with BleakClient(address) as client:
        print(f"Connected: {client.is_connected}   MTU: {client.mtu_size}\n", flush=True)

        # Pass 1: structure only. Descriptor/characteristic reads on this device
        # can trip a CoreBluetooth null-value assertion inside bleak's delegate
        # that hangs the await, so the topology is printed first, unconditionally.
        for svc in client.services:
            print(f"[service] {svc.uuid}  {label(svc.uuid)}", flush=True)
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"  [char] {ch.uuid}  ({props})  {label(ch.uuid)}", flush=True)
                for d in ch.descriptors:
                    print(f"    [desc] {d.uuid}  {label(d.uuid)}", flush=True)
            print(flush=True)

        if args_read:
            # Pass 2 (opt-in): carefully read values. Guarded + time-boxed so a
            # single hanging read doesn't wedge the whole dump.
            print("--- reading values (--read) ---\n", flush=True)
            for svc in client.services:
                for ch in svc.characteristics:
                    if "read" in ch.properties:
                        try:
                            val = await asyncio.wait_for(
                                client.read_gatt_char(ch.uuid), timeout=5.0
                            )
                            print(f"  {ch.uuid} = {val.hex(' ')}  ({len(val)} bytes)", flush=True)
                        except Exception as exc:  # noqa: BLE001 - research script
                            print(f"  {ch.uuid} read failed: {exc}", flush=True)
                    for d in ch.descriptors:
                        try:
                            raw = await asyncio.wait_for(
                                client.read_gatt_descriptor(d.handle), timeout=5.0
                            )
                            extra = ""
                            if label(d.uuid).startswith("Report Reference") and len(raw) >= 2:
                                rtype = REPORT_TYPE.get(raw[1], raw[1])
                                extra = f"  (report id={raw[0]} type={rtype})"
                            print(f"    desc {d.uuid} = {raw.hex(' ')}{extra}", flush=True)
                        except Exception as exc:  # noqa: BLE001 - research script
                            print(f"    desc {d.uuid} read failed: {exc}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", help="CoreBluetooth peripheral UUID from ble_scan.py")
    ap.add_argument("--name", help=f"device name (default {TARGET_NAME!r})")
    ap.add_argument("--read", action="store_true", help="also read char/descriptor values")
    args = ap.parse_args()
    return asyncio.run(enum(args.id, args.name, args.read))


if __name__ == "__main__":
    raise SystemExit(main())
