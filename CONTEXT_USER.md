# CONTEXT_USER.md — Known Device Functionality
 
Sources:
- Direct user experience with Audiobeat OctaPro 8.2
- Sennuopu HIFI-X12 manual (OEM base, identical hardware)
---
 
## Device Overview
 
- **10 output channels**: CH1–CH8 amplified + CH9–CH10 RCA line out
- **8 channels actively used** in current setup
- Amplifier: 75W×6 (AB) + 125W×2 (D class), 4Ω
---
 
## Per-Channel Parameters (all 10 channels)
 
| Parameter | Range / Options | Notes |
|-----------|----------------|-------|
| **GAIN (volume)** | 0 to -60 dB | Per-channel output level |
| **MUTE** | on/off | Silence individual channel |
| **SOLO** | on/off | Isolate channel — **no device command; app mutes all other channels** (SOLVED 2026-07-06) |
| **Phase** | 0° / 180° | Phase invert |
| **HPF** freq | 20 Hz – 20 kHz | High-pass cutoff |
| **HPF** slope | 6/12/18/24/30/36/42/48 dB/oct | 8 options |
| **HPF** algorithm | Link / Bessel / Butter | 3 filter types |
| **LPF** freq | 20 Hz – 20 kHz | Low-pass cutoff |
| **LPF** slope | 6/12/18/24/30/36/42/48 dB/oct | Same 8 options |
| **LPF** algorithm | Link / Bessel / Butter | |
| **EQ** | 31 bands | Freq + Gain + Q per band |
| **EQ** freq range | 20 Hz – 20 kHz | |
| **EQ** gain range | -12 dB to +12 dB | |
| **EQ** Q range | 0.4 – 20 | |
| **EQ Pass** | on/off | Bypass all EQ for A/B compare |
| **Delay** | 0–20 ms / 0–680 cm / 0–268 in | Time alignment |
| **Bridge** | CH7+CH8 only | Bridges to mono, controlled via CH7 |
 
---
 
## Main Volume
 
- Global output level: +6 to -60 dB
- Global mute button
---
 
## Routing Matrix (Cross-point mixer)
 
- Any input channel can be routed to any/all of 10 output channels
- Mixing ratio per crosspoint: 0–100%
- Used for: center channel summing, sub mixing, mono fold-down
- Example from manual: mix CH1+CH2 at 50:50 → center channel out
---
 
## Presets / Scenes
 
- **6 preset slots** saved internally (not 16 as initially assumed)
- Named by user (labels like M1, M2... likely UI display only)
- Save: stored to device memory
- Load: recalled from device
- Export/Import: .dat file format (confirmed: `US002` header)
---
 
## EQ Details
 
- **31 adjustable bands** (parametric)
- Default Q = **4.3**
- Default gain = **0 dB**
- Per-channel, independent
- **EQ Pass** button: bypasses all EQ (for comparison), does NOT clear values
- Reset options: "All" (all channels) or "Current" (active channel)
---
 
## Crossover / Frequency Divider
 
- HPF and LPF **per channel**, independent
- Slope options: **6/12/18/24/30/36/42/48 dB/oct** (8 slopes)
- Filter algorithms: **Linkwitz-Riley, Bessel, Butterworth**
- Frequency range: 20 Hz – 20 kHz
### User's setup (from dsp_m2.dat)
 
| Channel | Role | HPF | LPF | Slope |
|---------|------|-----|-----|-------|
| CH1, CH2 | Front full-range | — | 20600 Hz (bypass) | — |
| CH3, CH4 | Mid/Rear | — | 20600 Hz | — |
| CH5, CH6 | Tweeter | — | 3500 Hz | unknown |
| CH7, CH8 | Subwoofer | ~20 Hz | 80 Hz | **36 dB/oct** |
| CH9, CH10 | Line out | — | 20600 Hz | — |
 
**Key:** The HPF sweep observed in usb2.pcapng (20.1→22.0 Hz) was
sub channels CH7+CH8 HPF, adjusted simultaneously, at 36 dB/oct slope.
This maps to addr=0x07b7 (CH7) and addr=0x09b7 (CH8) in protocol.
 
---
 
## Input Sources — SELECT SOLVED 2026-07-06

The app has **two dropdowns**, one per priority tier (not one selector). Both
write via CMD 0x05 @ global addr `0x00b7`; see PROTOCOL.md "Input source select".

**High source** (high-priority auto-switch) — selector `0x0e`:

| Source | code |
|--------|------|
| Bluetooth (APTX-HD) | `0x00` |
| USB drive (U disk) | `0x01` |

**Low source** (normal priority) — selector `0x26`, byte[7] = keepalive read ID:

| Source | code |
|--------|------|
| High-level (speaker) | `0x00` |
| Low-level (RCA) | `0x01` |
| Optical (TOSLINK / opt) | `0x02` |
| USB audio (PC/Mac) | `0x03` |
 
---
 
## Channel Speaker Types (manual enum) — SOLVED 2026-07-06
 
CMD 0x05, selector byte[6]=`0x30`, code in byte[7] (menu order 1..6). See
PROTOCOL.md "Speaker type". HF(1)/LF(3)/FF(6) live-verified on CH3.
 
| Wire code | Code | Meaning |
|-----------|------|---------|
| `0x01` | HF | High frequency (tweeter) |
| `0x02` | MF | Mid frequency |
| `0x03` | LF | Low frequency (woofer) |
| `0x04` | MHF | Medium-high frequency |
| `0x05` | MLF | Medium-low frequency |
| `0x06` | FF | Full frequency |
 
---
 
## Wire Controller
 
- Physical knob: main volume (0–35 steps), clockwise=up
- Button press: play/pause
- Forward/back: track skip
- Menu navigation for U disk playback
---
 
## Gain Encoding (confirmed from traffic)
 
`gain_dB = (byte - 0x78) / 10.0`
 
| byte | dB |
|------|----|
| 0x80 (-128) | -inf (mute) |
| 0x78 (0) | 0.0 |
| 0x14 (-100) | -10.0 |
| 0x6e (-10) | -1.0 |
| 0xdc (+100) | +10.0 |
| 0xa4 (+44) | +4.4 |
 
Main volume range: +6 to -60 dB → bytes 0x84 to 0x28 (approx).
Channel volume range: 0 to -60 dB → bytes 0x78 to 0x14.
 
---
 
## Still to Capture (priority order)
 
| Parameter | Why | Hint |
|-----------|-----|------|
| ~~**LPF freq**~~ | ~~Find LPF write address~~ | **DONE 2026-07-06** — CMD 0x0a sub 0x06, float32 Hz |
| ~~**HPF slope**~~ | ~~Confirm slope codes~~ | **DONE** — byte[11], dB/oct=(code+1)*6 (0x00=6 … 0x07=48) |
| ~~**Filter algorithm** (Bessel vs Butter)~~ | ~~Find algorithm byte~~ | **DONE** — byte[12]: 0x00=LR, 0x01=Bessel, 0x02=Butterworth |
| ~~**EQ gain** (one band, known dB)~~ | ~~Find EQ write address~~ | **DONE 2026-07-06** — CMD 0x0a, sub=0x08+(band-1); gain byte[11]; see PROTOCOL.md "EQ band gain" |
| ~~**EQ freq** (move band center)~~ | ~~Confirm device response~~ | **DONE 2026-07-06** — float [7:11], settable (500→520 verified) |
| ~~**EQ Q**~~ | ~~Find Q encoding~~ | **DONE 2026-07-06** — byte[12] = round(Q×10); 0x0a=Q1.0, 0x1d=Q2.9 |
| ~~**MUTE** channel on/off~~ | ~~Find mute flag/command~~ | **DONE 2026-07-06** (master) — CMD 0x05 sub-byte 0x0d, byte[7]=1/0; see PROTOCOL.md "Mute write". Per-channel unverified |
| ~~**Phase** 0°→180°~~ | ~~Find phase command~~ | **DONE 2026-07-06** — CMD 0x05 selector 0x02; see PROTOCOL.md "Phase invert" |
| ~~**Delay** (e.g. set 1.5 ms)~~ | ~~Find delay addr + encoding~~ | **DONE 2026-07-06** — CMD 0x08 sub 0x04, float32 ms; see PROTOCOL.md "CMD 0x08 float-write family" |
| ~~**Routing** (change one crosspoint)~~ | ~~Find routing matrix command~~ | **DONE 2026-07-06** — CMD 0x20, one packet per output (all CH1-10); 14 inputs, value=0x80+pct; see PROTOCOL.md "Routing matrix write" |
| **Preset save** (M1 save button) | Find write sequence | 6 slots total |
| **Preset load** (select M2) | Find read/apply sequence | |
| ~~**Bridge** CH7+CH8 toggle~~ | ~~Find bridge command~~ | **DONE 2026-07-06** — CMD 0x1c sub 0x28, byte[19] bit 0x80; see PROTOCOL.md "Bridge CH7+CH8" |
| ~~**Input source** switch~~ | ~~Find source select command~~ | **DONE 2026-07-06** — CMD 0x05 @ 0x00b7, two registers: low=selector 0x26, high=selector 0x0e; see PROTOCOL.md "Input source select" |
| ~~**Main volume** change~~ | ~~Find master vol command~~ | **DONE 2026-07-05** — CMD 0x08 sub 0x0c, see PROTOCOL.md "Master volume write" |
| ~~**EQ Pass** toggle~~ | ~~Find EQ bypass command~~ | **DONE 2026-07-06** — CMD 0x05 selector 0x07 (channel-flag). EQ RST partial |
| **Noise gate** threshold | Find noise gate cmd | Factory set, low priority |
 










