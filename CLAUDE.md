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
- **Tests:** `uv run pytest` — 59 tests, all offline (no device needed)
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
    hid.py             HidTransport (pyusb, interface 4): open incl. session-open,
                       transact = SET_REPORT+GET_REPORT pair (lock-protected), keepalive thread
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

**Transport:** interface 4 (no interrupt endpoints → OS HID stacks don't bind; must use
pyusb/libusb, not hidapi). OUT = SET_REPORT (0x21/0x09/wValue 0x0200), IN = GET_REPORT
(0xA1/0x01/wValue 0x0100). A **session-open packet** (CMD `0x05` addr=`0x00b7` sub=`0x1103`)
is mandatory after connect — otherwise READ_BLOCK returns a short `ee 55` refusal ACK.
`HidTransport.open()` sends it automatically. Live-verified 2026-07-04 (fw
`A239-A-DP603-U5.6-250110-DSP1452-BMP885`).

**OUT payload** (256 bytes): `[e0 a2] [CMD] [00] [ADDR uint16 LE] [SUB uint16 LE] [CSUM] [DATA...]`

**Checksum (universal):** `(sum(pkt[4:13]) - 0x20) & 0xFF`
- Exception: CMD `0x0a` places checksum at byte **[13]**, not [8]

**Channel address:** `ADDR = 0x00b7 + channel_number × 0x0100` (CH1=`0x01b7` … CH10=`0x0ab7`)

**Gain encoding:** `gain_byte = round(gain_dB × 10) + 0x78`; mute = `0x80`

**Known commands:**
- `0x04` WRITE_PARAM — write register (firmware string at `0x80f0`, keepalive at `0xa515`)
- `0x05` (addr=`0x00b7`, sub=`0x1103`) — session open, mandatory first packet
- `0x05` READ_BLOCK — read full channel state; wire bytes [6:8] are `04 CH`
  (LE u16 sub = `(CH << 8) | 0x04` — byte order matters, the checksum can't catch a swap)
- `0x05` (addr=`0xNNb7`, sub=`0x01`) — DSP commit trigger after WRITE_DSP batch
- `0x05` **channel-flag family** (addr=`0xNNb7`, byte[6]=selector,
  byte[7]=`01`/`00`) — per-channel booleans, live-decoded 2026-07-06 via uhid
  shim. Selectors: `0x01`=mute, `0x02`=phase invert, `0x07`=EQ pass/bypass,
  `0x0d`=master mute (ch0). CLI: `write mute`, `write phase`, `write eq-pass`.
  Builder: `build_channel_flag(ch, sel, on)`. See PROTOCOL.md "CMD 0x05
  channel-flag family". EQ RST (reset) also uses selector `0x07` but at the
  fixed master addr with the channel in byte[7]: `write eq-reset`,
  `build_eq_reset(ch)`. **Solo is NOT a device command** — the app (and
  `write solo`) mutes every other channel via this same mute selector
  (live-verified 2026-07-06); helper `commands.write.solo_packets(ch, on)`.
- `0x0a` WRITE_DSP — real-time DSP write; sub `0x05`=HPF freq; **EQ band
  = sub `0x08 + (band-1)`** (band 1..31 → sub `0x08`..`0x26`), one atomic
  packet carries freq[7:11]+gain[11]+Q[12] (Q byte = round(Q×10)), no trailer,
  no commit. All three live-verified. `write eq`, builder `build_eq_band`,
  `constants.eq_band_sub`, `eq.q_to_byte`. (The old `sub 0x26 GAIN` from pcaps
  was actually EQ band 31, not a channel gain.)
  **DANGER: never send `0x0a` to CH0 (addr `0x00b7`)** — it force-switches the
  input source to high level (payload ignored), not a volume write.
- `0x08` **float-write family** — float32 at `[7:11]`, checksum `[11]`, applies
  immediately. Sub-byte `[6]` selects the parameter: master volume = `0x0c`
  addr `0x00b7`; channel N fader = `0x03` (dB); channel N delay = `0x04` (ms);
  all channel subs at addr `0xNNb7`. Live-captured via the uhid shim. CLI:
  `write master`, `write gain`, `write delay`. Builders:
  `build_write_master_volume`, `build_channel_gain`, `build_channel_delay`
  (shared `_build_volume_write`). See PROTOCOL.md "CMD 0x08 float-write family".
- `0x1c` BRIDGE (sub `0x28`, addr `0x00b7`) — bridge CH7+CH8 (only bridgeable
  pair). Fixed 23-byte payload; state in byte[19] bit `0x80`, checksum at
  byte[31] over `sum(pkt[4:31])`. CLI: `write bridge --on|--off`. Builder:
  `build_bridge(on)`. (sub `0x21` is a constant companion, not the write.)

**Master volume = one value per source, two controls** (resolved 2026-07-05): the
software "Main" fader and the remote knob (0–35 steps) both show the CH0 block
float [9:13] (= keepalive echo float); each input source stores its own level.
CLI: `read master` (CH0 block), `read knob-vol` (keepalive; also shows the input
source — keepalive byte [11]: 0=high level, 1=low level, 2=opt, 3=USB AUDIO).
CH0 block [27:31] float = factory noise gate (−88.0).

**Slope codes** (live-verified 2026-07-06): `dB/oct = (code+1)*6`, so `0x00`=6
… `0x05`=36 … `0x07`=48. (Corrects the old guess — `0x03` is 24 dB not 12;
dsp_m2.dat's "unknown `0x01`" is 12 dB.) **Filter type** byte: `0x00`=Linkwitz-
Riley, `0x01`=Bessel, `0x02`=Butterworth. HPF=CMD 0x0a sub `0x05`, LPF=sub
`0x06`; both freq[7:11]+slope[11]+type[12]. `write hpf`/`write lpf`.

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

See `CONTEXT_USER.md → Still to Capture` for the priority-ordered list.
Most DSP params are now solved (2026-07-06 via the uhid shim): master vol,
faders, delay, mute, phase, bridge, 31-band EQ (gain/freq/Q), EQ pass/reset,
HPF+LPF (freq/slope/type). High-priority remaining:
- Routing matrix write commands
- Input source switching (read-side IDs known)
- Speaker type; preset save/recall (M1–M6)
- EQ "reset all" variant (only per-channel reset captured)

## Analysis Tools (installed on this machine)

### System tools
| Tool | Location | Use |
|------|----------|-----|
| `tshark` | `/usr/bin/tshark` | CLI PCAP dissection — primary PCAP tool |
| `radare2` / `r2` | `/usr/bin/radare2` | Disassembly, binary patching, scripting |
| `ghidra` | `/snap/bin/ghidra` | Decompiler — best for finding undiscovered HID commands in the EXE |
| `binwalk` | `/usr/bin/binwalk` | Entropy map, detect compressed/embedded sections in the EXE |
| `7z` | `/usr/bin/7z` | Unpack NSIS/Inno Setup installers to extract embedded DAT/config files |
| `wine` | `/usr/bin/wine` | Run the Windows config EXE to generate live USB traffic for capture |
| `strings` | `/usr/bin/strings` | Quick string scan of the binary |
| `xxd` / `hexdump` | `/usr/bin/` | Raw hex inspection |
| `foremost` | `/usr/bin/foremost` | File carving from raw binary dumps |
| `yara` | `/usr/bin/yara` | Pattern rules — scan for HID magic bytes (`e0 a2`) across the binary |
| `jq` | `/usr/bin/jq` | Query `research.jsonl` |

### Python libraries (in project venv)
| Library | Use |
|---------|-----|
| `pefile` | Parse PE headers, import table, resources from the Windows EXE |
| `scapy` | Scriptable PCAP parsing as an alternative to tshark |
| `capstone` | Disassembly engine callable from Python scripts |

### Recommended workflow for EXE analysis
1. `7z l <setup.exe>` — check if it's a self-extracting installer; unpack with `7z x`
2. `binwalk <app.exe>` — entropy map to find compressed/encrypted sections
3. `strings <app.exe> | grep -iE "hid|usb|0x|e0a2"` — quick string pass
4. `pefile` (Python) — dump imports, section names, embedded resources
5. `ghidra` — decompile to C pseudocode; search for HID `WriteFile`/`HidD_SetOutputReport` calls to find command-building functions
6. `yara` — write a rule for the `e0 a2` HID magic and scan the binary + memory dumps

## Useful tshark One-Liners

```bash
# Dump all URB OUT payloads (host→device)
tshark -r usb1.pcapng -Y "usb.transfer_type == 2 && usb.endpoint_address.direction == 0" -T fields -e usb.capdata

# Follow a single parameter change
tshark -r usb2.pcapng -Y "usb.capdata" -T fields -e frame.number -e usb.capdata | head -40
```
