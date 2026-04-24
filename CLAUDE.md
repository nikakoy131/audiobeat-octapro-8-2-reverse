# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is a **reverse engineering research repository** — not a software project with a build system. The goal is to document and implement the USB HID communication protocol for the **Audiobeat OctaPro 8.2 / SP601 Car DSP Amplifier** (OEM: Guangzhou Nisson / Sennuopu HIFI-X12).

There are no build steps, test suites, or package manifests. Work here is primarily:
- Analyzing USB packet captures (`.pcapng` files) with Wireshark/tshark
- Writing/refining Python scripts that communicate with the device via `hidapi`
- Documenting protocol findings in the `.md` files

## Key Files

| File | Purpose |
|------|---------|
| `PROTOCOL.md` | The primary protocol reference — packet layout, checksum formulas, known commands, channel data block format |
| `CONTEXT_USER.md` | Device feature inventory and remaining capture targets (priority-ordered) |
| `FINDINGS_*.md` | Analysis notes from Wireshark, EXE, and DAT file investigation |
| `usb1.pcapng` | 2736 packets — enumeration + full channel readback |
| `usb2.pcapng` | 566 packets — live EQ/filter parameter changes |
| `dsp_m2.dat` | Preset export file (US002 format, 2387 bytes, 10×238-byte channel blocks) |

## Protocol Quick Reference

**Device:** VID=`0x8888`, PID=`0x1234`, USB Full Speed, HID CONTROL transfers (not Interrupt)

**OUT payload** (256 bytes): `[e0 a2] [CMD] [00] [ADDR uint16 LE] [REG uint16 LE] [CSUM] [DATA...]`

**Checksum (universal):** `(sum(pkt[4:13]) - 0x20) & 0xFF`
- Exception: CMD `0x0a` places checksum at byte **[13]**, not [8]

**Channel base address:** `ADDR = 0x00b7 + channel_number × 0x0100` (CH1=`0x01b7` … CH10=`0x0ab7`)

**Gain encoding:** `gain_byte = round(gain_dB × 10) + 0x78`; mute = `0x80`

**Known commands:**
- `0x04` WRITE_PARAM — write register (firmware string at `0x80f0`, keepalive at `0xa515`)
- `0x05` READ_BLOCK — read full channel state (256-byte response)
- `0x05` (addr=`0xNNb7`, sub=`0x01`) — DSP commit trigger after WRITE_DSP batch
- `0x0a` WRITE_DSP — real-time DSP write; sub `0x05`=HPF freq, sub `0x26`=GAIN

## Python Development (hidapi)

The reference Python client is embedded in `PROTOCOL.md` (the `macOS Client (hidapi)` section). Key points:
- Always prepend report ID `0x00` when calling `dev.write()`
- `send_ctrl` / `recv_ctrl` pattern: send 257 bytes (1 + 256), receive 256 bytes
- Keepalive must fire every ~500 ms after handshake or the device may disconnect
- After a WRITE_DSP sequence, send the DSP commit trigger (CMD `0x05`, addr=channel base, sub=`0x01`) once per modified channel

## What Is Still Unknown

See `CONTEXT_USER.md → Still to Capture` for the priority-ordered list. High-priority items:
- LPF write command (sub-address and TYPE_BYTE unknown)
- EQ band gain/Q write addresses
- Routing matrix write commands
- MUTE, phase, delay, preset save/load commands
- Slope codes beyond `0x05` (36 dB/oct) and `0x03` (12 dB/oct)

## Useful tshark One-Liners

```bash
# Dump all URB OUT payloads (host→device HID data)
tshark -r usb1.pcapng -Y "usb.transfer_type == 2 && usb.endpoint_address.direction == 0" -T fields -e usb.capdata

# Follow a single parameter change
tshark -r usb2.pcapng -Y "usb.capdata" -T fields -e frame.number -e usb.capdata | head -40
```
