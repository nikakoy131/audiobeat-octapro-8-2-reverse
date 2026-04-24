# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Reverse-engineering research **and** a working Python CLI (`octaproctl`) for the **Audiobeat OctaPro 8.2 / SP601 Car DSP Amplifier** (OEM: Guangzhou Nisson / Sennuopu HIFI-X12).

Work here is:
- Analyzing USB packet captures (`.pcapng`) with Wireshark/tshark to discover new commands
- Maintaining and extending the `octaproctl` Python CLI that talks to the device via `hidapi`
- Documenting protocol findings in the `.md` files

## Toolchain

- **Package manager / venv:** `uv` — use `uv run <cmd>` for everything; never activate the venv manually
- **Python:** 3.11 (`.python-version`)
- **Build:** `hatchling` + `hatch-vcs` — version is derived from git tags
- **Lint:** `uv run ruff check src tests` (line-length 100)
- **Types:** `uv run mypy src`
- **Tests:** `uv run pytest` — 57 tests, all offline (no device needed)
- **All three must be clean before committing**

## Project Layout

```
src/octapro/
  cli.py               typer app — octaproctl binary
  logging.py           Rich console + JSONL research log + warn_unknown()
  errors.py            DeviceNotFound, TransportTimeout, ParseError, ChecksumMismatch
  protocol/
    constants.py       VID/PID, CMD codes, slope codes, EQ band table
    packet.py          build_read_channel, build_write_dsp, build_dsp_commit, compute_checksum
    channel.py         242-byte READ_BLOCK response decoder
    dat.py             US002 .dat preset parser (10 × 238-byte blocks)
    eq.py              31-band × 6-byte EQ block parser
    routing.py         32-byte routing matrix parser
    gain.py            byte ↔ dB, mute=0x80
  transport/
    hid.py             HidTransport: open/close, transact (lock-protected), keepalive thread
  commands/
    info.py            handshake + firmware banner
    read.py            read channel(s), decoded table output
    dump.py            raw hex + annotated hex of a block
    dat.py             parse-dat <file>
    monitor.py         live poll loop, diff highlight
    probe.py           raw packet sender (--commit gate)
    write.py           write hpf / write gain (dry-run default)
    decode_pcap.py     offline pcapng decode (tshark required)
tests/
  test_packet.py       checksum, packet builders
  test_channel.py      242-byte block decoder
  test_dat.py          real dsp_m2.dat parse (asserts CH7/8 LPF≈80Hz, CH5/6 LPF≈3500Hz)
  test_eq.py           31-band EQ parser
  test_gain.py         byte↔dB roundtrip incl. mute
```

## Key Files

| File | Purpose |
|------|---------|
| `PROTOCOL.md` | Primary protocol reference — packet layout, checksum, commands, channel block format |
| `CONTEXT_USER.md` | Device feature inventory and priority-ordered "Still to Capture" list |
| `FINDINGS_*.md` | Analysis notes from Wireshark, EXE, and DAT file investigation |
| `usb1.pcapng` | 2736 packets — enumeration + full channel readback |
| `usb2.pcapng` | 566 packets — live EQ/filter parameter changes |
| `dsp_m2.dat` | Preset export (US002 format, 2387 bytes, 10×238-byte channel blocks) |

## Protocol Quick Reference

**Device:** VID=`0x8888`, PID=`0x1234`, USB Full Speed, HID CONTROL transfers (not Interrupt)

**OUT payload** (256 bytes): `[e0 a2] [CMD] [00] [ADDR uint16 LE] [SUB uint16 LE] [CSUM] [DATA...]`

**Checksum (universal):** `(sum(pkt[4:13]) - 0x20) & 0xFF`
- Exception: CMD `0x0a` places checksum at byte **[13]**, not [8]

**Channel address:** `ADDR = 0x00b7 + channel_number × 0x0100` (CH1=`0x01b7` … CH10=`0x0ab7`)

**Gain encoding:** `gain_byte = round(gain_dB × 10) + 0x78`; mute = `0x80`

**Known commands:**
- `0x04` WRITE_PARAM — write register (firmware string at `0x80f0`, keepalive at `0xa515`)
- `0x05` READ_BLOCK — read full channel state (256-byte response)
- `0x05` (addr=`0xNNb7`, sub=`0x01`) — DSP commit trigger after WRITE_DSP batch
- `0x0a` WRITE_DSP — real-time DSP write; sub `0x05`=HPF freq, sub `0x26`=GAIN

**Known slope codes:** `0x03`=12 dB/oct, `0x05`=36 dB/oct, `0x01`=unknown (seen in dsp_m2.dat CH3/4)

## Adding New Write Commands

Pattern for adding a new `write <param>` subcommand (e.g. LPF, EQ band gain):

1. Add the sub-address constant to `protocol/constants.py`
2. Add `run_write_<param>` to `commands/write.py` following the `run_write_hpf` pattern:
   - build packet with `build_write_dsp`
   - dry-run path: `_dry_run_print(intent, bytes(pkt))`
   - commit path: `transact(dsp_write)` then `transact(dsp_commit)`
3. Wire the CLI command in `cli.py` under `write_app`
4. Add a test in `tests/test_packet.py` or a new file

## Research Logging

`warn_unknown(kind, observed, context)` in `logging.py` fires on any unexpected byte — slope codes, Q values, unknown commands, unexpected trailers. Every call:
- Prints a WARN line to the console pointing at the log file
- Appends a `decode_note` JSON record to the research log

**Log locations:**
- macOS: `~/Library/Logs/octapro/research.jsonl`
- Linux: `~/.local/state/octapro/research.jsonl`

Query: `jq 'select(.kind=="decode_note")' research.jsonl`

## What Is Still Unknown

See `CONTEXT_USER.md → Still to Capture` for the priority-ordered list. High-priority items:
- LPF write sub-address and TYPE_BYTE
- EQ band gain/Q write addresses
- Routing matrix write commands
- MUTE, phase, delay, preset save/load
- Slope code `0x01` meaning (seen on CH3/4 HPF in dsp_m2.dat)

## Useful tshark One-Liners

```bash
# Dump all URB OUT payloads (host→device)
tshark -r usb1.pcapng -Y "usb.transfer_type == 2 && usb.endpoint_address.direction == 0" -T fields -e usb.capdata

# Follow a single parameter change
tshark -r usb2.pcapng -Y "usb.capdata" -T fields -e frame.number -e usb.capdata | head -40
```
