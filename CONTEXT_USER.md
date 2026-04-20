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
| **SOLO** | on/off | Isolate channel |
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
 
## Input Sources
 
| Source | Priority |
|--------|----------|
| Bluetooth (APTX-HD) | High (auto-switch) |
| USB drive (U disk) | High (auto-switch) |
| Optical (TOSLINK) | Normal |
| High-level (speaker) | Normal |
| Low-level (RCA) | Normal |
| USB audio (PC/Mac) | Normal |
 
---
 
## Channel Speaker Types (manual enum)
 
| Code | Meaning |
|------|---------|
| HF | High frequency (tweeter) |
| MF | Mid frequency |
| LF | Low frequency (woofer) |
| MHF | Medium-high frequency |
| MLF | Medium-low frequency |
| FF | Full frequency |
 
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
| **LPF freq** (change sub LPF 80→100 Hz) | Find LPF write address | Expected near 0x07b7 + offset |
| **HPF slope** (try 12, 24, 48 dB/oct) | Confirm slope_code values per slope | Currently only 0x05 seen (36dB) |
| **Filter algorithm** (Bessel vs Butter) | Find algorithm byte | Embedded in same command? |
| **EQ gain** (one band, known dB) | Find EQ write address | Different addr range |
| **EQ freq** (move band center) | Confirm EQ freq addr vs HPF addr | |
| **EQ Q** | Find Q encoding | Q range 0.4–20 |
| **MUTE** channel on/off | Find mute flag/command | |
| **Phase** 0°→180° | Find phase command | |
| **Delay** (e.g. set 1.5 ms) | Find delay addr + encoding | Range 0–20ms |
| **Routing** (change one crosspoint) | Find routing matrix command | |
| **Preset save** (M1 save button) | Find write sequence | 6 slots total |
| **Preset load** (select M2) | Find read/apply sequence | |
| **Bridge** CH7+CH8 toggle | Find bridge command | |
| **Input source** switch | Find source select command | |
| **Main volume** change | Find master vol command | +6 to -60 dB |
| **EQ Pass** toggle | Find EQ bypass command | |
| **Noise gate** threshold | Find noise gate cmd | Factory set, low priority |
 










