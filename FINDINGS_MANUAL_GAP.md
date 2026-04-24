# FINDINGS_MANUAL_GAP.md — Gap analysis of the HIFI-X12 manual vs reverse-engineered protocol

Comparison of what the manual (`docs/Sennuopu HIFI-X12 Manual EN V201120.pdf`) and the
desktop app (`Audiobeat OctaPro 8.2 V1.0.7_250801.exe`) expose vs what we can drive
today via `octaproctl`.

Date: 2026-04-24

---

## Manual feature inventory

Parsed from the English manual (17 pages). Feature → surface exposed to user → current RE status.

### Per-channel parameters (all 10 channels)

| Feature | Manual range | RE status | Notes |
|---------|--------------|-----------|-------|
| Volume (gain) | 0 → −60 dB | ✅ CMD 0x0a SUB 0x26 | gain_byte = round(dB × 10) + 0x78 |
| Mute | on/off | ❌ handler found in EXE (fcn.0046e940), not yet mapped to wire format |
| Solo | on/off | ❌ slot `on_soloValueChanged` found in EXE, not in pcap |
| Phase | 0° / 180° | ❌ handler `on_PhaselSwitchChanged` (typo in original; at fcn.0046eae? area) |
| HPF freq | 20 Hz – 20 kHz | ✅ CMD 0x0a SUB 0x05, float32 little-endian Hz |
| HPF slope | 6/12/18/24/30/36/42/48 dB/oct | ⚠ 2 of 8 values confirmed (0x03=12 dB, 0x05=36 dB) |
| HPF algorithm | Link / Bessel / Butter | ❌ `on_freqTypeChanged` slot, not mapped |
| LPF freq | 20 Hz – 20 kHz | ❌ readable in CMD 0x05 block, write command unknown |
| LPF slope | same 8 values | ❌ readable in block, write unknown |
| LPF algorithm | Link / Bessel / Butter | ❌ same as HPF algorithm |
| EQ band freq (31 bands) | 20 Hz – 20 kHz | ❌ readable in block, write unknown |
| EQ band gain | −12 dB → +12 dB | ❌ handlers `on_LineEditGainChanged` etc., not in pcap |
| EQ band Q | 0.4 – 20 | ❌ handler `on_LineEditQChanged` |
| EQ Pass | bypass toggle | ❌ slot `on_PEQPASSChanged` / `on_valuePEQPASSChanged` |
| Delay | 0–20 ms / 0–680 cm / 0–268 in | ❌ `WidgetDelayPic` handlers, no pcap |
| Bridge CH7+CH8 | toggle | ❌ slot `on_bridgeChanged` / `on_pushbuttonBridgeClick` |
| Speaker type | HF / MF / LF / MHF / MLF / FF (6) | 🔶 Strong static-analysis signal — see below |

### Global / system controls

| Feature | Manual range | RE status |
|---------|--------------|-----------|
| Main volume | +6 → −60 dB | ❌ probably CMD 0x04 SUB 0xa515 (keepalive response carries float32 state) |
| Main mute | toggle | ❌ unknown |
| Noise gate threshold | integer, factory set | ❌ `on_noiseAuto`, `on_noiseEnable` slots |
| Factory reset | confirm dialog | ❌ unknown |
| Firmware version query | string | ✅ CMD 0x04 SUB 0x80f0 (response ≈ 41 bytes) |
| Firmware upgrade | DFU-like | ❌ slot `on_pushbuttonUpgradeClick` |
| Language | EN / 中文 | UI-only (no wire command expected) |

### Input routing

| Feature | Options | RE status |
|---------|---------|-----------|
| Input source select | BT / U disk / Optical / High level / Low level / USB audio | ❌ `on_soundSourceChanged`, `on_SwitchChanged_High/Ble/USB/DSP` |
| Routing matrix (10×10 crosspoints, 0–100 %) | per-source mixing | ❌ 32-byte matrix visible in CMD 0x05 block readback; write command unknown |

### Presets / scenes

| Feature | Manual says | RE status |
|---------|-------------|-----------|
| 6 internal preset slots (M1–M6) | save / load on device | ❌ handlers `on_actionScene_1..16` present (16, not 6 — app supports more than device exposes) |
| Export / import .dat | US002 file format | ✅ parser implemented (`octaproctl parse-dat`), writer/apply flow not reversed |

---

## EXE static analysis (new)

File: `Audiobeat OctaPro 8.2 V1.0.7_250801.exe` (22 MB, PE32 i386, Qt+MinGW).

### Packet-builder buffer layout (inferred)

All per-channel write handlers call an allocator (at `0x117e850`, size 0x414 = 1044 B),
and then populate a common struct starting at the returned pointer `eax`:

```
eax[0]      DWORD  message type / opcode enum  (0x02, 0x03, 0x07, 0x1a, 0x22, 0x414, ...)
eax[4]      DWORD  count / length / sub-index  (value depends on type)
eax[8]      BYTE   ADDR_LO — 0xb7 for per-channel SP601 commands
eax[9]      BYTE   ADDR_HI — channel number (0x01..0x0a)
eax[0xa]    BYTE   parameter SUB / qualifier (observed: 0x00..0x04)
eax[0xf]    BYTE/DWORD/QWORD  payload value (byte, int, float32, or double depending on eax[0x30])
eax[0x10]   BYTE   type qualifier (0x00 / 0x01 / 0x02 / 0x81 seen)
...
```

The wire packet (`e0 a2 CMD 00 b7 CH SUB ...`) is assembled later by the transport
layer — these structs are the **application-level request**, not raw HID packets.

### Message type families (eax[0] values)

Collected from every function that writes `0xb7` at `[eax+0x8]`:

| eax[0] | eax[4] samples | Guess | Likely use |
|--------|----------------|-------|------------|
| 0x02   | 0x01, 0x07, 0x0e, 0x19, 0x1d..0x20, 0x26, 0x29, 0x2b | "single value write" | per-parameter writers — gain, mute, phase, etc. |
| 0x03   | 0x0f..0x12, 0x32, 0x5a, 0x82, 0xaa, 0xd2, 0xfa, 0x122, 0x14a, 0x172, 0x1c2 | "indexed write" — stride 0x28 | EQ bands (31 × 40-byte entries) |
| 0x07   | 0x28, 0x21 | "group write" | routing matrix? |
| 0x1a   | 0x06 | **Speaker type setter** | 14 occurrences; payload values 0x01..0x06 and 0x81..0x86 (toggle + selected) match HF/MF/LF/MHF/MLF/FF |
| 0x22   | 0x2e | — | ? |
| 0x414  | various | "bulk transfer" | allocator-adjacent; block reads/writes |

**Speaker type evidence:** the 12 instructions immediately after one `[eax+0x8]=0xb7`
site contain exactly `mov byte [eax+0xf], 0x01 … 0x06` and `0x81 … 0x86` as the only
non-zero immediates — a 6-way switch with the high bit flagging the selected entry.

### Handler function addresses (debug-string anchored)

Functions that print their Qt slot name in a qDebug line (making them trivial to locate):

| Slot / feature | Log string VA | Handler fcn. (first xref) |
|----------------|---------------|---------------------------|
| Mute | `on_MuteSwitchChanged_` @ `0x011c4302` | fcn.0046e940, fcn.0046f040 (second overload) |
| Mute (Chinese build) | `系统静音=` @ `0x011c3d34` | fcn.00460160 |
| Phase | `on_PhaselSwitchChanged_` @ (near `0x46eb23`) | same parent function as mute |
| SenSivity_Chose | `WidgetTitle_2::on_SenSivity_Chose Send dta********` | — |
| SenSivity_Chose_lab | ditto `_lab Send dta********` | — |
| Slider 1/2/3 | `on_sliderChanged_{1,2,3} temp=` @ `0xdbff2d` etc. | — |

### Still-unresolved slot names (present in MOC table, not yet located in code)

`on_HPFSlopePushbuttonClick`, `on_LPFSlopePushbuttonClick`, `on_HzChanged_1/2`,
`on_LineEditHzChanged`, `on_LineEditGainChanged`, `on_LineEditQChanged`,
`on_freqTypeChanged`, `on_PEQPASSChanged`, `on_valuePEQPASSChanged`,
`on_bridgeChanged`, `on_linkChanged`, `on_linkWholeChanged`, `on_routeSwitch`,
`on_soundSourceChanged`, `on_SwitchChanged_{High,Ble,USB,DSP}`, `on_SaveClick`,
`on_SaveModeClick`, `on_loadModeFile`, `on_saveModeFile`, `on_actionScene_{1..16}`,
`on_soloValueChanged`, `on_noiseAuto{Click}`, `on_noiseEnable{Click}`,
`on_pushbuttonUpgradeClick`, `on_pushbuttonBridgeClick`, `on_pushbuttonRouteClick`,
`on_pushbuttonSaveClick`, `WidgetDelayPic::on_buttonUp/Down`.

---

## Pcap findings (new / corrected)

Derived from `scripts/catalog_pcap_commands.py` and `scripts/pair_pcap_requests_responses.py`
over `usb1.pcapng` (full session) and `usb2.pcapng` (live tuning).

### Every unique (CMD, ADDR, SUB) signature observed

| CMD | ADDR | SUB | Count | Purpose (confirmed or inferred) |
|-----|------|-----|-------|---------------------------------|
| 0x04 | 0x00b0 | 0x80f0 | 3 | Read firmware string (response 0x006a, 102 B) |
| 0x04 | 0x00b0 | 0x9909 | 2 | Handshake init (response 0x002f, 43 B — firmware short form) |
| 0x04 | 0x00b0 | 0xa515 | **847** | Keepalive (response 0x000f, 11 B — **echoes main-volume float32!**) |
| 0x05 | 0x00b0 | 0x0004..0x0a04 | 3 ea. | Read channel block (11 channels; response 0x00f6, 242 B) |
| 0x05 | 0x00b7 | 0x1103 | 2 | Connection status probe (response: firmware string, dlen=0x2b) |
| 0x05 | 0xNNb7 | 0x0001 | 4 | DSP commit trigger, variant A (REG_HI=0x00) |
| 0x05 | 0xNNb7 | 0x0101 | 10 | DSP commit trigger, variant B (REG_HI=0x01) |
| 0x08 | 0x00b7 | 0x0206 | 1 | Handshake handoff (usb1, right after init) |
| 0x08 | 0x00b7 | 0x8206 | 1 | Session-mid variant (high bit set in SUB_HI) |
| 0x0a | 0x07b7 | 0x05 | 23 | HPF frequency write (CH7) — float32 Hz + slope byte + 0x00 type |
| 0x0a | 0x09b7 | 0x26 | 21 | GAIN write (CH9) — float32 constant + gain byte + 0x0a type |
| 0x1c | 0x00b7 | 0x0121 | 3 | Handshake / session-init (data payload: bit-doubling pattern 0x02 0x04 0x08 0x10 ...) |

### New protocol insight — keepalive echoes main-volume state

The CMD 0x04 SUB 0xa515 keepalive **response** carries a payload of the form
`15 00 <flags 2B> <float32 LE> <trailer byte>`. During usb1 capture the payload
was `15 00 01 02 00 00 c0 40 a8` — the embedded float is `0x40c00000` = 6.0 dB,
exactly the manual's upper main-volume limit (+6 dB). During usb2 capture the
same field was 0.0. This means:

- the keepalive doubles as a **main-volume state readback**
- the trailing byte (0xa8 / 0xa5) likely encodes the global-mute flag or
  secondary state — value changes between sessions

Writing main volume probably uses CMD 0x04 SUB 0xa515 with the float32 set in the
payload data slot — testable on live hardware.

### New protocol insight — commit trigger has two variants

CMD 0x05 addr=0xNNb7 sub=0x0001 vs sub=0x0101 differ in the high byte of the SUB
(0x00 vs 0x01). Both follow batches of WRITE_DSP (0x0a) writes; why two variants
is still unclear. Usb2 only emitted `0x0001` commits (on CH3/CH4 — channels that
weren't written in the capture, suggesting the commit is scoped to "the currently
selected channel in the UI" rather than the write target).

### New protocol insight — CMD 0x08 and CMD 0x1c payload pattern

Both `CMD 0x1c sub=0x0121` and `CMD 0x08 sub=0x0206/0x8206` carry a data field
containing the bit-doubling sequence `00 02 00 04 00 08 00 10 00 20 00 40 00 80 00 00`.
Hypothesis: this is a **capability bitmap** — the host telling the device (or
asking) which parameter groups are supported/active. The high-bit variant
(`0x8206`) may be the "acknowledge / apply" counterpart of the "probe" variant
(`0x0206`).

### Confirmed: response status codes

| Status (LE) | Size | Returned for |
|-------------|------|--------------|
| 0x000f | 11 B | keepalive / mid-session writes |
| 0x002f | 43 B | handshake init (short firmware) |
| 0x006a | 102 B | firmware-string query |
| 0x008d | 137 B | master-channel (CH0) readback |
| 0x00f6 | 242 B | full-channel readback (CMD 0x05 SUB 0xNN04) |

---

## Priority punch-list for the next capture session

Sorted by value of unlocking each feature (highest first):

1. **LPF freq** — toggle CH7 LPF in the app while capturing. Expect `CMD 0x0a addr=0x07b7 sub=??` with a new SUB byte near 0x05.
2. **Mute CH1** — single toggle; very small delta. Expect `CMD 0x0a` or `CMD 0x02` family.
3. **Main volume slide** — expect `CMD 0x04 sub=0xa515` with a float in the data payload.
4. **Input source switch** (BT ↔ Optical) — expect a new CMD or a `CMD 0x04` sub we haven't seen.
5. **Phase 0°↔180° on CH1** — single bit toggle.
6. **EQ band 15 gain** (1 kHz) — sweep from 0 to +6 dB; will reveal EQ write SUB + addressing of bands.
7. **Preset save M2** — reveals preset-save command(s) and size.
8. **Routing crosspoint** — change a single crosspoint % value to reveal matrix write format.
9. **Bridge CH7+CH8** — single toggle.
10. **Speaker type** (change CH1 from FF to HF, etc.) — test speaker-type hypothesis above.
11. **Delay** — step 1.0 ms on one channel.
12. **EQ Pass** toggle.
13. **Factory reset** — probably CMD 0x04 with a specific SUB.
14. **Noise gate threshold** — calibration flow.

For every item, run `uv run octaproctl decode-pcap` on the capture and diff
against a baseline to identify the new commands.
