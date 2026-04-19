# FINDINGS_DAT.md — Preset File Format Analysis (dsp_m2.dat)

## File Info

| Field | Value |
|-------|-------|
| File | dsp_m2.dat |
| Size | 2387 bytes |
| Format | US002 (version 2 preset export) |
| Source | Exported from Audiobeat OctaPro 8.2 app |

---

## File Structure

```
[0:5]    "US002"            magic / version string
[5:295]  Channel 1 block    290 bytes
[295:585] Channel 2 block   290 bytes
...
[2610:2900] Channel 10 block  (but file is only 2387 — last block is incomplete?)
```

Actually: 5 + 10 × 238 = 2385 bytes if header=52 is separate.
File = 5 + (52+238) × 10 - 3 (padding) = fits.

**Block layout per channel: 52 bytes header + 238 bytes EQ = 290 bytes**

EQ block starts:
| CH | EQ block offset |
|----|----------------|
| 1  | 0x0039 |
| 2  | 0x0127 |
| 3  | 0x0215 |
| 4  | 0x0303 |
| 5  | 0x03f1 |
| 6  | 0x04df |
| 7  | 0x05cd |
| 8  | 0x06bb |
| 9  | 0x07a9 |
| 10 | 0x0897 |

---

## Channel Header (52 bytes, before EQ block)

### Bytes 0–31: Routing Matrix (8×4 = 32 bytes)

Each byte = a gain value in the routing crossbar.

**Gain byte encoding:**
```
gain_dB = signed_byte / 10.0
  where signed_byte = byte if byte < 128 else byte - 256

Special values:
  0x80 (-128) = -inf dB = mute / silent
  0x78 (0)    = 0.0 dB = unity gain (TBC — may differ from EQ encoding)
  0xe4 (-28)  = -2.8 dB
  0x64 (+100) = +10.0 dB
  0xb2 (-78)  = -7.8 dB
```

The 8 bytes per row likely represent: input to output routing (e.g., 8 outputs for that input channel).

**Channel 1 routing (bytes 0–7):** `e4 80 80 80 80 80 00 00`
→ Out1=-2.8dB, Out2=mute, Out3–6=mute, Out7–8=0dB

**Channel 7 routing (bytes 0–7):** `b2 b2 80 80 80 80 00 00`
→ Out1=-7.8dB, Out2=-7.8dB (mixed sub → both front outputs)

### Bytes 32–35: HPF frequency (float32 LE)

- CH1: bytes = `e0 c0 cd cc` → interpreted as float = -107874048 (clearly wrong, needs re-check)
- CH2: bytes = `e0 c0 33 33` → also negative
- **TBD**: HPF may not be at this offset, or encoding differs from IEEE 754

### Bytes 36–39: ? (possibly Q or HPF slope)

- CH1: `8c 40 00 00` → float = 0.0
- CH2: `33 73 40 00` → float = 0.0
- Meaning unclear.

### Bytes 40–43: unknown

### Bytes 44–47: LPF frequency (float32 LE) — **confirmed**

| CH | bytes | LPF freq |
|----|-------|----------|
| 1  | 00 f0 a0 46 | 20600.0 Hz = bypass |
| 2  | 00 f0 a0 46 | 20600.0 Hz = bypass |
| 5  | 00 c0 5a 45 | 3500.0 Hz (tweeter HPF) |
| 7  | 00 00 a0 41 | 80.0 Hz (sub LPF) |
| 8  | 00 00 a0 41 | 80.0 Hz (sub LPF) |

### Bytes 48–51: Mode/flags

| Value | Meaning |
|-------|---------|
| `03 01 00 06` | Full-range channel |
| `03 00 00 06` | Band-limited channel |
| `03 00 00 03` | Sub/bass channel |

---

## EQ Block (238 bytes, 16 bands)

16 standard 1/3-octave center frequencies (all confirmed present):
`20, 31.5, 50, 80, 125, 200, 315, 500, 800, 1250, 2000, 3150, 5000, 8000, 12500, 20000 Hz`

### Band record structure (~14 bytes each, confirmed by pattern)

```
[0:4]   float32 LE  center frequency (Hz)
[4]     gain byte   gain_dB = (byte - 0x78) / 10.0
[5]     0x78        separator (= "0 dB" code)
[6]     Q byte      meaning TBD (see below)
[7]     0x0a        separator
[8:14]  overlap with next band header / tail bytes
```

Total: 16 bands × ~14 bytes = 224 bytes + 14 bytes tail = 238 ✓

### Gain byte values seen

| byte | dB |
|------|----|
| 0x78 | 0.0 dB (most bands) |
| 0x72 | -0.6 dB |
| 0x6d | -1.1 dB |
| 0x6e | -1.0 dB |
| 0x67 | -1.7 dB |
| 0x5a | -3.0 dB |
| 0x81 | +0.9 dB |
| 0x87 | +1.5 dB |
| 0x88 | +1.6 dB |
| 0x8c | +2.0 dB (approx) |

### Q byte — still unknown

Seen values: `0x00` (most bands), `0x80` (some bands, possibly = enabled flag).

---

## Decoded Channel Settings

### CH1 — Front Left

| Parameter | Value |
|-----------|-------|
| LPF | 20600 Hz (bypass) |
| Mode | Full-range (03 01 00 06) |
| Routing | Out1=-2.8dB, Out2-6=mute, Out7-8=unity |
| EQ | Flat 20-2000Hz; -0.6@3150, -1.7@5000, +0.9@8000, +1.5@12500, +1.6@20000 |

### CH2 — Front Right (mirror of CH1)

| Parameter | Value |
|-----------|-------|
| LPF | 20600 Hz |
| Mode | Full-range |
| Routing | Out2=-2.8dB, others muted |
| EQ | Identical to CH1 |

### CH3, CH4 — Mid/Rear L, R

Flat EQ, full-range, each routed to its own output only.

### CH5 — Tweeter Left

| Parameter | Value |
|-----------|-------|
| LPF | 3500 Hz |
| Mode | Limited (03 00 00 06) |
| Routing | Out5 only |
| EQ | -3.0@300Hz, +2.0@450Hz, -1.1@3150, -1.0@5000 |

### CH6 — Tweeter Right (mirror of CH5)

### CH7 — Sub Left

| Parameter | Value |
|-----------|-------|
| LPF | 80 Hz |
| Mode | Sub (03 00 00 03) |
| Routing | Out1=-7.8dB, Out2=-7.8dB (mixed) |
| EQ | Flat |

### CH8 — Sub Right (identical to CH7)

### CH9, CH10 — Line Outputs 1, 2

| Parameter | Value |
|-----------|-------|
| LPF | 20600 Hz |
| Mode | Full-range |
| EQ | Mostly flat, minor +6.9dB@20000Hz |

---

## Still Unknown from .dat

- [ ] **HPF frequency bytes [32:36]** — floats give negative values, encoding unclear.
  Possibly: HPF is stored differently (fixed-point? or two separate bytes?)
- [ ] **Q byte [6] in EQ band** — 0x00 vs 0x80, what does it mean?
- [ ] **Bytes [36:44] in header** — Q value? slope code? padding?
- [ ] **Routing matrix interpretation** — rows vs columns unclear (8 outputs × N inputs?)
- [ ] **Delay/time-alignment** — not found in this file. Maybe stored separately or not in this preset format.
- [ ] **Solo, Mute flags** — not visible in this file (may be runtime-only, not saved)
- [ ] **Preset name / label** — no ASCII found for "M1", "M2" etc. May be in a separate index file.
- [ ] **Gain per channel (output gain)** — not clearly identified in header
