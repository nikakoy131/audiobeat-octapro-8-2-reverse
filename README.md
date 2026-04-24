# Audiobeat OctaPro 8.2 — Protocol Reverse Engineering + CLI

This repository documents the ongoing efforts to reverse engineer the USB HID communication protocol for the **Audiobeat OctaPro 8.2** (and related SP601) Car DSP Amplifier, and provides a Python CLI tool (`octaproctl`) to interact with the device.

## Hardware Overview

| Field | Value |
|---|---|
| Device | Audiobeat OctaPro 8.2 / SP601 (OEM: Guangzhou Nisson / Sennuopu HIFI-X12) |
| DSP | Analog Devices ADAU1452 |
| MCU | BMP885B |
| VID | `0x8888` |
| PID | `0x1234` |
| USB speed | Full Speed (12 Mb/s) |
| Channels | 10 total (CH1-CH8 amplified, CH9-CH10 RCA line out) |

## Protocol Summary

The device uses **USB HID CONTROL** transfers (not interrupt) with 256-byte payloads.

### Commands

| CMD | Name | Description |
|:---:|:---|:---|
| `0x04` | `WRITE_PARAM` | Write to device registers (firmware read, keepalive, init). |
| `0x05` | `READ_BLOCK` | Read full 256-byte parameter state of a channel. |
| `0x0a` | `WRITE_DSP` | Real-time write of DSP RAM parameters (float32). |

### Packet Structure (OUT)

```
[e0 a2] [CMD] [00] [ADDR uint16 LE] [REG/SUB uint16 LE] [CSUM] [DATA...]
```

**Checksum:** `(sum(pkt[4:13]) - 0x20) & 0xFF`  
Exception: CMD `0x0a` stores the checksum at byte **[13]**, not [8].

See [`PROTOCOL.md`](PROTOCOL.md) for the full reference.

---

## CLI Tool — `octaproctl`

### Prerequisites

The Python `hid` package requires the native hidapi library:

```bash
# macOS
brew install hidapi

# Ubuntu / Debian
sudo apt install libhidapi-dev
```

### Install

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and set up
git clone https://github.com/nikakoy131/audiobeat-octapro-8-2-reverse
cd audiobeat-octapro-8-2-reverse
uv sync

# Verify
uv run octaproctl --version
```

### Quickstart

```bash
# Device info (firmware banner)
uv run octaproctl info

# Read all 10 DSP channels
uv run octaproctl read channel all

# Read a single channel
uv run octaproctl read channel 7

# Parse a .dat preset file — no device needed
uv run octaproctl parse-dat dsp_m2.dat

# Hex-dump a channel block with field annotations
uv run octaproctl dump channel 7 --annotate

# Live monitor — highlights parameter changes in real time
uv run octaproctl monitor

# Decode a pcapng capture offline (requires tshark)
uv run octaproctl decode-pcap usb2.pcapng

# Write HPF — DRY RUN by default (prints packet, sends nothing)
uv run octaproctl write hpf --channel 7 --freq 25

# Write HPF — actually apply
uv run octaproctl write hpf --channel 7 --freq 25 --commit

# Write gain — dry run
uv run octaproctl write gain --channel 7 --db -3.0
```

### All Commands

```
octaproctl info                                       device firmware + info
octaproctl read channel <N|all>                       decode live channel block(s)
octaproctl read master                                decode master (CH0) block
octaproctl dump channel <N> [--annotate]              hex dump raw channel block
octaproctl monitor [--interval 0.5]                   live poll + diff highlight
octaproctl parse-dat <file> [--channel N]             offline .dat preset decode
octaproctl decode-pcap <file> [--out jsonl]           offline pcapng decode (needs tshark)
octaproctl probe <hex> [--commit]                     send raw packet
octaproctl write hpf --channel N --freq Hz [--slope C] [--commit]
octaproctl write gain --channel N --db F [--commit]
```

Global flags: `-v/--verbose`, `-q/--quiet`, `--log-file PATH`, `--no-keepalive`

### Read-Only by Default

Every write command (`write hpf`, `write gain`, `probe`) defaults to **dry-run**:  
it builds the packet, prints the hex + intent, and exits — without touching the device.  
Add `--commit` to actually transmit.

### Research Logging

Every session appends structured events to a JSONL research log:

- **macOS:** `~/Library/Logs/octapro/research.jsonl`
- **Linux:** `~/.local/state/octapro/research.jsonl`

Events include every packet in/out and a `decode_note` entry for any unknown byte  
(unknown status codes, sub-addresses, slope codes, Q bytes, unexpected trailers, etc.).  
The file is `jq`-greppable: `jq 'select(.kind=="decode_note")' research.jsonl`

---

## Development

```bash
uv sync            # install all deps including dev tools
uv run pytest      # run tests
uv run ruff check  # lint
uv run mypy src    # type check
```

Tests that parse `dsp_m2.dat` assert CH7/CH8 LPF≈80 Hz (sub), CH5/CH6 LPF≈3500 Hz (tweeters),  
CH1-CH4/CH9-CH10 LPF≈20600 Hz (bypass). These run without a device.

### Releasing

```bash
git tag v0.1.0
git push --tags
```

GitHub Actions (`release.yml`) builds a wheel + sdist and attaches them to the Release.

---

## Documentation

| File | Purpose |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | Full protocol reference — packet layout, checksum, commands, channel block format, Python reference client |
| [`CONTEXT_USER.md`](CONTEXT_USER.md) | Device feature inventory and priority-ordered "Still to Capture" list |
| [`FINDINGS_DAT.md`](FINDINGS_DAT.md) | Analysis of `dsp_m2.dat` (US002 preset format) |
| [`FINDINGS_EXE.md`](FINDINGS_EXE.md) | Analysis of the vendor Windows EXE (Qt/HID class structure) |
| [`FINDINGS_WIRESHARK.md`](FINDINGS_WIRESHARK.md) | Analysis of `usb1.pcapng` and `usb2.pcapng` |

## Project Roadmap

- [x] USB HID handshake sequence documented
- [x] Channel parameter readback (`CMD 0x05`)
- [x] HPF frequency/slope write (`CMD 0x0a`)
- [x] Channel gain write (`CMD 0x0a`)
- [x] `.dat` preset file parser
- [x] Alpha CLI (`octaproctl`) with research logging
- [ ] LPF frequency write (sub-address TBD)
- [ ] EQ band gain/Q write
- [ ] Routing matrix write
- [ ] MUTE, phase, delay commands
- [ ] Preset save/load
