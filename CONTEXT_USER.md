# CONTEXT_USER.md — Known Device Functionality (from user)

This file documents what the user knows about the device's features from direct use.
Used to guide protocol reverse engineering — map UI elements to captured packets.

---

## Device Overview

- **10 output channels** (8 amplified + 2 line outputs)
- **8 channels actively used** in current setup
- Channels shown individually in the app UI

---

## Per-Channel Parameters

Each of the 10 channels has:

| Parameter | Type | Notes |
|-----------|------|-------|
| **GAIN** | dB slider | Output level per channel |
| **MUTE** | toggle | Silence channel |
| **SOLO** | toggle | Isolate channel |
| **HPF** (High-Pass Filter) | freq + slope | Cuts frequencies below threshold |
| **LPF** (Low-Pass Filter) | freq + slope | Cuts frequencies above threshold |
| **EQ** | 16-band parametric | Per-band: freq, gain, Q |
| **Delay** | ms / samples | Time alignment per channel |

---

## EQ

- **16 bands** per channel (1/3-octave: 20, 31.5, 50 ... 20000 Hz)
- Each band: center frequency, gain (dB), Q factor
- Type per band: peak, high-shelf, low-shelf (likely)

---

## Routing

- Input channels can be routed to output channels
- Routing matrix: N inputs → M outputs with gain per crosspoint
- Used for summing (e.g., sub channels mixed to front outputs)

---

## Presets

- Named presets: **M1, M2, ...** (exact count unknown)
- Save and load from device
- Possibly also importable from .dat file

---

## Filters — Confirmed Details

| Channel | HPF | LPF | Slope |
|---------|-----|-----|-------|
| Sub (CH7, CH8) | ~20 Hz (adjustable) | 80 Hz | **36 dB/oct** |
| Tweeter (CH5, CH6) | — | 3500 Hz | unknown |
| Front (CH1, CH2) | — | 20600 Hz (bypass) | — |

> **Key insight:** The HPF sweep observed in usb2.pcapng (20.1→22.0 Hz)
> was the HPF for the **sub channels (7+8 simultaneously)** at **36 dB/oct slope**.
> This maps to addr=0x07b7 (CH7) and addr=0x09b7 (CH8) in the protocol.

---

## Input

- High-level input (speaker-level) from head unit
- Possibly low-level RCA as well
- Input sensitivity adjustment per channel

---

## Still to Capture

To complete protocol mapping, need Wireshark captures while adjusting:

| Parameter | Why important |
|-----------|--------------|
| **LPF frequency** (e.g. sub LPF 80→100 Hz) | Find LPF write address |
| **HPF slope change** (12→24→36→48 dB/oct) | Confirm slope_code values |
| **EQ gain** on a specific band | Find EQ write address |
| **EQ frequency** (move a band center) | Confirm EQ freq address |
| **EQ Q factor** | Find Q encoding |
| **MUTE** on/off | Find mute command |
| **SOLO** on/off | Find solo command |
| **Delay** change | Find delay address + encoding |
| **Input gain/sensitivity** | Find sensitivity address |
| **Routing** — change a crosspoint | Find routing command |
| **Preset save** (press M1 save) | Find preset write sequence |
| **Preset load** (select M2) | Find preset read sequence |
| **Phase invert** | Find phase command |
| **Bridge mode** | Find bridge command |
