# Changelog

All notable changes to `octaproctl` and the reverse-engineering research for the Audiobeat OctaPro 8.2 / SP601 are documented here.

## [0.2.0] — 2026-04-24

### Added

#### Analysis Scripts (`scripts/`)
- **`catalog_pcap_commands.py`** — Scapy-based tool that extracts all unique `(CMD, ADDR, SUB)` signatures from `.pcapng` files without requiring `tshark`. Handles USBPcap CONTROL-transfer offsets (OUT magic at raw byte 36, IN magic at byte 30). Produces a sorted table of every distinct command seen across captures.
- **`pair_pcap_requests_responses.py`** — Pairs each OUT request packet with its next IN response (within a 5-packet lookahead window) and prints per-signature status code, data length, address, and the first 48 bytes of response payload. Used to discover the keepalive-response float32 main-volume field and the two commit-trigger variants.

#### Research Findings (`FINDINGS_MANUAL_GAP.md`)
- Full inventory of all ~25 features listed in the HIFI-X12 EN V201120 manual cross-referenced against reverse-engineered protocol status (✅ confirmed / ⚠ partial / ❌ unknown / 🔶 candidate).
- Complete 55-signature command catalog derived from `usb1.pcapng` + `usb2.pcapng`.
- EXE static-analysis findings: allocator address (`0x117e850`), 1044-byte packet-builder struct layout, `[eax+8]=0xb7` as ADDR_LO, `[eax+0xf]` as PARAM_BYTE, and the three message-type families (0x02 single writes, 0x03 indexed/EQ-band writes at stride 0x28, 0x1a speaker-type writes with count=6).
- Speaker-type write hypothesis: 6 speaker types (HF/MF/LF/MHF/MLF/FF) mapped to EXE handler PARAM values 0x01–0x06 / 0x81–0x86.
- Keepalive response discovery: CMD 0x04 SUB `0xa515` IN response carries a little-endian `float32` main-volume value at payload bytes [4:8] (6.0 dB in `usb1`, 0.0 dB in `usb2`).
- Two commit-trigger variants identified: CMD 0x05 addr=`0xNNb7` with SUB `0x0001` (REG_HI=0x00) vs `0x0101` (REG_HI=0x01) — significance still under investigation.
- CMD `0x08` / `0x1c` carry a bit-doubling capability bitmap payload; not yet reverse-engineered.
- 14-item priority capture plan ranked by unlock value (LPF write, EQ band gain/Q, routing write, mute, phase, delay, preset save/load, speaker type, main volume, crossover type).

#### Protocol Documentation (`PROTOCOL.md`)
- Added confirmed IN-response status code table (`0x000f` keepalive, `0x002f` short info, `0x006a` firmware banner, `0x008d` master-channel block, `0x00f6` full channel-state block).
- Added CMD 0x05 commit-trigger section documenting the two SUB variants and commit-sequence timing.
- Added speaker-type write candidate section with PARAM encoding table.
- Added main-volume write hypothesis (WRITE_DSP sub-address not yet confirmed on wire).
- Added full 55-signature command catalog reference pointing to `FINDINGS_MANUAL_GAP.md`.

#### Project Dependencies (`pyproject.toml`)
- Added `pefile>=2024.8.26` — PE header / import-table / resource parsing for the Windows config EXE.
- Added `scapy>=2.7.0` — scriptable PCAP parsing (workaround for AppArmor-restricted `tshark` on Ubuntu).
- Added `capstone>=5.0.7` — Python-callable disassembly engine for EXE binary analysis.

#### Developer Tooling
- **`CLAUDE.md`** — Added comprehensive analysis toolchain section documenting every installed tool (`tshark`, `radare2`, `ghidra`, `binwalk`, `7z`, `wine`, `yara`, `foremost`, `xxd`) with recommended EXE analysis workflow and useful tshark one-liners.
- **`.gitignore`** — Added `.analysis/` scratch directory (holds pcap copies, disassembly dumps, and temporary analysis artifacts that should not be committed).

### Changed
- `PROTOCOL.md` "Still Unknown" section restructured and expanded with richer context from manual-gap analysis.

---

## [0.1.0] — 2026-04-23

Initial alpha release of the `octaproctl` CLI.

### Added
- `octaproctl info` — handshake + firmware banner
- `octaproctl read [CH]` — decode full channel state (HPF freq/slope, LPF freq/slope, EQ 31-band, gain/mute, routing)
- `octaproctl dump [CH]` — raw hex + annotated hex of a 242-byte READ_BLOCK response
- `octaproctl parse-dat <file>` — parse US002 `.dat` preset exports (10 × 238-byte channel blocks)
- `octaproctl monitor [CH]` — live poll loop with diff highlighting
- `octaproctl probe` — raw packet sender with `--commit` safety gate
- `octaproctl write hpf` / `write gain` — real-time DSP writes with dry-run default
- `octaproctl decode-pcap` — offline `.pcapng` decode (requires `tshark`)
- Full offline test suite: 57 tests covering checksum, packet builders, channel decoder, DAT parser, EQ parser, gain codec
- `PROTOCOL.md` — primary protocol reference (packet layout, checksum, channel block format, known commands)
- `CONTEXT_USER.md` — device feature inventory and "Still to Capture" priority list
