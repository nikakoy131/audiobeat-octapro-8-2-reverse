# Audiobeat OctaPro 8.2 — Protocol Reverse Engineering + CLI

This repository documents the fully reverse-engineered USB HID communication protocol for the **Audiobeat OctaPro 8.2** (and related SP601) Car DSP Amplifier, and provides a Python CLI tool (`octaproctl`) to read and write every device parameter: faders, EQ, crossovers, routing, presets, and more.

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
| `0x05` | `READ_BLOCK` | Read full 256-byte parameter state of a channel (CH0 = master). |
| `0x05` | session open | `addr=0x00b7 sub=0x1103` — mandatory first packet after connect. |
| `0x05` | channel-flag | `addr=0xNNb7`, byte[6]=selector — per-channel booleans: `0x01`=mute, `0x02`=phase, `0x0d`=master mute. |
| `0x08` | float write | Master fader (sub `0x0c`), channel faders (sub `0x03`, dB), channel delay (sub `0x04`, ms) — float32 at `[7:11]`, applies immediately. |
| `0x0a` | `WRITE_DSP` | Real-time DSP RAM writes (float32) — HPF, and 31-band EQ (sub-byte = band slot `0x08+band-1`, carries freq+gain+Q). |
| `0x08` | preset save/recall | `addr=0x00b7 sub=0x06` — byte[7]=`0x80|slot` saves, `slot` recalls (M1-M6). |
| `0x1c` | bridge | `addr=0x00b7 sub=0x28` — bridge CH7+CH8 (state in byte[19] bit `0x80`). |
| `0x20` | routing | `addr=0x0Nb7` — one packet per output channel, full 14-input crosspoint row. |

Commands for master volume, mute, phase, and bridge were captured 2026-07-05/06
by impersonating the device with a Linux `uhid` shim (see
[`docs/LINUX_UHID_SHIM_PLAN.md`](docs/LINUX_UHID_SHIM_PLAN.md) and
`scripts/uhid_shim.py`) and replaying the vendor app's own traffic under wine —
no live-device guessing.

> ⚠️ **Never send `WRITE_DSP` (`0x0a`) to CH0** — it force-switches the input
> source, it is **not** a master-volume write. Use `write master` (CMD `0x08`).

### Packet Structure (OUT)

```
[e0 a2] [CMD] [00] [ADDR uint16 LE] [REG/SUB uint16 LE] [CSUM] [DATA...]
```

**Checksum:** `(sum(pkt[4:13]) - 0x20) & 0xFF`  
Exceptions: CMD `0x0a` stores it at byte **[13]**; CMD `0x08` at **[11]**; CMD `0x1c` sums **[4:31]** and stores at **[31]**.

See [`PROTOCOL.md`](PROTOCOL.md) for the full reference.

---

## CLI Tool — `octaproctl`

### Prerequisites

The CLI talks to the device with `pyusb`, which needs the native libusb library:

```bash
# macOS
brew install libusb

# Ubuntu / Debian
sudo apt install libusb-1.0-0
```

**Why libusb and not hidapi:** the DSP protocol lives on USB interface 4, a
HID-class interface with *no interrupt endpoints* (every exchange is a
SET_REPORT/GET_REPORT control-transfer pair). Because that interface is not
HID-compliant, the OS HID stack never binds to it — on macOS it doesn't exist
as a HID device at all (only interface 3, the media-key remote, does). libusb
drives the unclaimed interface directly, exactly mirroring the vendor app's
traffic.

To talk to the device over Bluetooth LE instead, install the optional `ble`
extra (pulls in `bleak`):

```bash
uv sync --extra ble
```

See [Transports](#transports) below.

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

# Read a single channel — includes a 31-band EQ table with bar visualization
uv run octaproctl read channel 7

# Read the master block (CH0) — master volume (software "Main" fader) + firmware
uv run octaproctl read master

# Read knob-vol — the remote-panel knob volume (decoded from the keepalive echo)
uv run octaproctl read knob-vol

# Show a .dat preset file — no device needed
uv run octaproctl preset show dsp_m2.dat

# Hex-dump a channel block with field annotations
uv run octaproctl dump 7 --annotate

# Live monitor — highlights parameter changes in real time
uv run octaproctl monitor

# Decode a pcapng capture offline (requires tshark)
uv run octaproctl decode-pcap usb2.pcapng

# Write HPF — DRY RUN by default (prints packet, sends nothing)
uv run octaproctl write hpf --channel 7 --freq 25 --slope-db 36 --type bessel

# Write HPF — actually apply
uv run octaproctl write hpf --channel 7 --freq 25 --commit

# Write LPF — same options
uv run octaproctl write lpf --channel 7 --freq 3000 --slope-db 48 --type butterworth

# Write channel fader/gain (CMD 0x08) — dry run
uv run octaproctl write gain --channel 3 --db -6.0

# Write MASTER (Main) volume — the real command (CMD 0x08), dry run
uv run octaproctl write master --db -6.0

# Channel time-alignment delay (CMD 0x08) — ms, dry run
uv run octaproctl write delay --channel 2 --ms 1.512

# EQ band — gain + freq + Q in one atomic write (CMD 0x0a), band 1-31
uv run octaproctl write eq --channel 1 --band 18 --db 6.0
uv run octaproctl write eq --channel 3 --band 15 --freq 520 --q 2.9

# Mute / phase / bridge — all dry-run unless --commit
uv run octaproctl write mute --channel 7 --on
uv run octaproctl write phase --channel 6 --invert
uv run octaproctl write bridge --on            # CH7+CH8 (only bridgeable pair)
```

### All Commands

```
octaproctl info                                       device firmware + info
octaproctl read channel <N|all>                       decode live channel block(s)
octaproctl read master                                decode master (CH0) block
octaproctl read knob-vol                              remote-knob volume (keepalive echo)
octaproctl dump <N> [--annotate]                      hex dump raw channel block
octaproctl monitor [--interval 0.5]                   live poll + diff highlight
octaproctl preset show <file> [--channel N]           offline .dat preset decode
octaproctl preset export <file>                       read device → write US002 .dat preset
octaproctl preset import <file> [-c N] [--skip-flat-eq] [--commit]   apply .dat preset to device
octaproctl preset save --slot N [--commit]             save current settings to M1-M6 (overwrites)
octaproctl preset recall --slot N [--commit]           recall/load preset M1-M6
octaproctl decode-pcap <file> [--out jsonl]           offline pcapng decode (needs tshark)
octaproctl probe <hex> [--commit]                     send raw packet
octaproctl write hpf --channel N --freq Hz [--slope-db D] [--type T] [--commit]
octaproctl write lpf --channel N --freq Hz [--slope-db D] [--type T] [--commit]
octaproctl write gain --channel N --db F [--commit]   channel fader (N=1..10, CMD 0x08)
octaproctl write delay --channel N --ms F [--commit]  channel time-align delay (CMD 0x08)
octaproctl write eq --channel N --band B [--db F] [--freq Hz] [--q Q] [--commit]   31-band EQ (CMD 0x0a)
octaproctl write eq-pass --channel N --on|--off [--commit]   bypass/engage channel EQ
octaproctl write eq-reset --channel N | --all [--commit]     flatten one channel's EQ, or all (RST)
octaproctl write master --db F [--commit]             master (Main) volume, CMD 0x08
octaproctl write mute --channel N --on|--off [--commit]     N=0 = master mute
octaproctl write solo --channel N --on|--off [--commit]     mutes all other channels (macro)
octaproctl write speaker-type --channel N --type hf|mf|lf|mhf|mlf|ff [--commit]
octaproctl write source --tier high|low --to <name> [--commit]   tier high: bt/usb-disk; low: high-level/low-level/opt/usb-audio
octaproctl write routing --output N --levels "p1,...,p14" [--commit]    full 14-input routing row
octaproctl write noise-gate get|set --db X|on|off [--commit]   noise gate (FACTORY-LOCKED)
octaproctl write phase --channel N --invert|--normal [--commit]
octaproctl write bridge --on|--off [--commit]         CH7+CH8 bridge
octaproctl ble scan [--seconds N] [--all]             find the device's BLE peripheral
octaproctl ble connect [ADDRESS] [--seconds N]        save a BLE device as the default transport
octaproctl config show                                effective transport + config file path
octaproctl config path                                print the config file path
octaproctl config set-transport usb|ble               persist the default transport
```

Global flags: `-v/--verbose`, `-q/--quiet`, `--log-file PATH`, `--no-keepalive`,
`--transport usb|ble` (before the subcommand — see [Transports](#transports)),
`--address TEXT` (BLE peripheral address override, use with `--transport ble`)

### Read-Only by Default

Every write command defaults to **dry-run**:  
it builds the packet, prints the hex + intent, and exits — without touching the device.  
Add `--commit` to actually transmit.

### Transports

`octaproctl` talks to the device over USB HID (default) or Bluetooth LE — both
carry the identical `e0 a2 …` protocol (see
[`docs/findings/BLE.md`](docs/findings/BLE.md)), so every command works
unchanged over either link.

**Selecting a transport, in precedence order:**

1. **Per-invocation override** — global flags placed *before* the subcommand:
   ```bash
   uv run octaproctl --transport ble read channel 1
   uv run octaproctl --transport ble --address AA:BB:CC:DD:EE:FF write mute --channel 3 --commit
   ```
2. **Saved config** — set once, used by every subsequent command:
   ```bash
   uv run octaproctl ble scan                 # find the device (needs the `ble` extra)
   uv run octaproctl ble connect               # scan + pick interactively, saves it
   uv run octaproctl ble connect <address>     # or save a known address directly
   uv run octaproctl config show               # confirm what's effective
   uv run octaproctl config set-transport usb  # switch back to USB
   ```
3. **Default** — USB, device index 0, if nothing above applies.

**Config file** (JSON, created by `ble connect`/`config set-transport`):

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/octapro/config.json` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/octapro/config.json` |

```json
{
  "transport": "ble",
  "ble": {"address": "AA:BB:CC:DD:EE:FF", "name": "AB OctaPro BLE"},
  "usb": {"device_index": 0}
}
```

BLE needs the `ble` extra (`uv sync --extra ble`) and, on macOS, a one-time
Bluetooth permission grant for the terminal app hosting Python (System
Settings → Privacy & Security → Bluetooth). The peripheral only accepts one
central at a time — disconnect the phone/WeChat app first.

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
| [`docs/context_user.md`](docs/context_user.md) | Device feature inventory and capture log (complete — all parameters reverse-engineered) |
| [`docs/findings/DAT.md`](docs/findings/DAT.md) | Analysis of `dsp_m2.dat` (US002 preset format) |
| [`docs/findings/EXE.md`](docs/findings/EXE.md) | Analysis of the vendor Windows EXE (Qt/HID class structure) |
| [`docs/findings/WIRESHARK.md`](docs/findings/WIRESHARK.md) | Analysis of `usb1.pcapng` and `usb2.pcapng` |
| [`docs/findings/MANUAL_GAP.md`](docs/findings/MANUAL_GAP.md) | Gap analysis of the HIFI-X12 manual vs. reverse-engineered protocol |
| [`docs/findings/BLE.md`](docs/findings/BLE.md) | Bluetooth LE control discovery — advertised HID-over-GATT + vendor serial bridge, and the macOS access wall |
| [`docs/LINUX_UHID_SHIM_PLAN.md`](docs/LINUX_UHID_SHIM_PLAN.md) | The `uhid` virtual-amplifier capture rig (how the write commands were found) |
| [`docs/HID_DESCRIPTORS.md`](docs/HID_DESCRIPTORS.md) | Live-dumped USB config + interface-4 HID report descriptors |

## Project Roadmap (USB CLI App)

### Completed Features (Read/Write over USB)
- [x] **Handshake & Session Setup:** Connection probes and mandatory session-open sequencing.
- [x] **Hardware Transport:** PyUSB interface claiming & SET_REPORT/GET_REPORT on Interface 4.
- [x] **Master Volume Extraction:** Read master block (CH0) and knob volume from keepalive echoes.
- [x] **Channel Block Readback:** Decode full 242-byte channel block (HPF/LPF, EQ table, routing matrix).
- [x] **Preset Parsing:** Offline `.dat` preset parser supporting the `US002` format.
- [x] **Parametric EQ Decoding:** Decode gain and frequencies for all 31 EQ bands.
- [x] **Crossover (HPF + LPF):** Frequency, slope (6–48 dB/oct, all 8 verified), and filter type
  (Linkwitz-Riley / Bessel / Butterworth) — CMD `0x0a` sub `0x05`/`0x06`, live-verified 2026-07-06.
- [x] **Channel Faders:** Per-channel output level (CMD `0x08` sub `0x03`, float32 dB — live-verified CH3 → −6.0 dB, 2026-07-06).
- [x] **Time Alignment (Delay):** Per-channel delay (CMD `0x08` sub `0x04`, float32 ms — live-verified CH2 → 1.512 ms, 2026-07-06).
- [x] **31-band Parametric EQ:** Band gain, center frequency, and Q (CMD `0x0a`, one atomic write, sub-byte = band slot — all three live-verified, 2026-07-06).
- [x] **Linux `uhid` capture rig:** Impersonate the device (VID/PID + iface-4 report descriptor)
  so the vendor Windows app connects under wine and its write packets can be captured directly —
  no live-device guessing. See [`docs/LINUX_UHID_SHIM_PLAN.md`](docs/LINUX_UHID_SHIM_PLAN.md).
- [x] **Master Volume Write:** `write master` — CMD `0x08`, direct float32 dB (captured 2026-07-05).
- [x] **Mute:** `write mute` — master and per-channel (CMD `0x05` channel-flag family, 2026-07-06).
- [x] **Phase Inversion (0°/180°):** `write phase` (CMD `0x05` selector `0x02`, 2026-07-06).
- [x] **Solo:** `write solo` — client-side macro (mutes all other channels), no device command (2026-07-06).
- [x] **CH7+CH8 Bridging:** `write bridge` (CMD `0x1c`, 2026-07-06).
- [x] **BLE Transport:** every command also runs over Bluetooth LE
  (`BleTransport`, the `0xAE00` GATT bridge) — selected via `octaproctl ble
  connect` / `--transport ble`, config persisted per-user; see
  [Transports](#transports) (2026-07-12).

### Crossover & Equalizer — DONE
- [x] **HPF + LPF** — frequency, slope (all 8 steps 6–48 dB/oct), filter type (LR/Bessel/Butterworth).
- [x] **31-band EQ** — gain, center frequency, and Q (one atomic write per band).
- [x] **EQ Pass** (`write eq-pass`) and **EQ Reset/RST** (`write eq-reset`, per-channel + `--all`) — CMD `0x05` selector `0x07`.

### Device Protocol — Fully Reverse-Engineered
- [x] **Speaker Type** (`write speaker-type`) — CMD `0x05` selector `0x30`, 1..6 enum (2026-07-06).
- [x] **Input Source Switching** (`write source --tier high|low`) — CMD `0x05` @ `0x00b7`, two registers (2026-07-06).
- [x] **Input Routing Matrix** (`write routing`) — CMD `0x20`, per-output 14-input row, value=`0x80`+%, all CH1-10 (2026-07-06).
- [x] **Preset Save & Recall** (`preset save` / `preset recall`) — CMD `0x08` sub `0x06`, slots M1-M6 (2026-07-06).
- [x] **Noise Gate** (`write noise-gate get|set|on|off`) — CMD 0x04 reg `0xa212` / CMD 0x08 sub `0x12` / CMD 0x05 sel `0x29`; factory-locked (2026-07-06).
- [x] **`.dat` Import / Export** (`preset import` / `preset export`) — full US002 round-trip: gain, delay, HPF/LPF (freq/slope/type), speaker type, 31-band EQ (routing excluded — read-format only). Hidden block fields (gain/delay/filter type/speaker type) decoded 2026-07-06.

### Future Ideas (exploratory — not scoped or started)

The device protocol itself is done; these are directions for what to build *on top of* it.

- **Control over Bluetooth, not just USB.** The vendor Windows app has a
  `CommunicationWorkerFactory` abstraction with four transport backends —
  `CommunicationWHidWorker` (USB HID), `CommunicationBleWorker`,
  `CommunicationComWorker` (serial), `CommunicationTcpWorker` — see
  [`docs/findings/EXE.md`](docs/findings/EXE.md) "Communication layer". So BLE
  control is architecturally real on the app side. **SOLVED 2026-07-12** (branch
  `feat/ble-discovery`, see [`docs/findings/BLE.md`](docs/findings/BLE.md)): the
  BLE link carries the **identical `e0 a2 …` protocol as USB** — same commands,
  checksum, and float encoding — recovered from the WeChat mini-program's own JS.
  Transport: service `0xAE00`, write commands (short, unpadded, with response) to
  characteristic `0xAE10`, responses via notifications on `0xAE02`, after the same
  session-open packet. The advertised HID service `0x1812` is an OS-reserved red
  herring the applet never uses. **Live-verified 2026-07-12** — a channel read over
  BLE decodes with the unchanged `parse_channel_block`. **`BleTransport` shipped**
  (`src/octapro/transport/ble.py`, same branch): every CLI command now runs over
  either USB or BLE, selected via `octaproctl ble connect` / `--transport ble` —
  see [Transports](#transports).
- **Cross-platform GUI, heavily tested.** Since this project has been almost
  entirely AI-assisted so far, lean into that for a GUI layer too: a
  Tauri/Flutter-style desktop+mobile front end over the existing Python
  protocol/`octaproctl` layer, backed by a much larger automated test suite
  (golden-packet tests, property-based encoding tests, `.dat` round-trip
  contract tests) rather than manual QA carrying the correctness burden.
- **Android app.** Depends on solving a control transport Android can use —
  either BLE (see above) or USB-OTG host mode replaying the same control
  packets `octaproctl` sends today. Worth scoping both before committing to one.
- **User-friendly UI with speaker layout mapped to channels.** A visual mixer
  showing each channel by its physical role (front-left tweeter, sub, etc.)
  instead of a bare channel number, using the already-decoded `speaker_type`
  field (`SPEAKER_TYPE_NAMES` in `protocol/constants.py`) to drive the layout.
- **REW (Room EQ Wizard) integration.** Translate REW's measured/target filter
  export into the device's 31-band EQ (`write eq` / `preset import`) for
  measurement-driven tuning, and/or export the device's current EQ curve back
  into a REW-importable format.
- **RC-knob control from an external Android device.** Use a phone as a
  wireless remote for master volume (mirrors the physical rotary remote /
  `read knob-vol`), instead of the hardware knob. Depends on the same control-
  transport question as the Android app above.

