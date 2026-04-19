# FINDINGS_WIRESHARK.md — USB Traffic Analysis

## Captures

| File | Packets | Content |
|------|---------|---------|
| usb1.pcapng | 2736 | Full enumeration + initial readback of all channels |
| usb2.pcapng | 566 | Live parameter changes (HPF freq + channel gain) |

Tool: USBPcap + Wireshark on Windows.
Parser: custom Python (no tshark available).

---

## Device on Bus

| Field | Value |
|-------|-------|
| USB address | dev=7 (usb1), dev=8 (usb2) |
| Bus | 2 |
| Speed | Full Speed (12 Mb/s) |
| VID/PID confirmed | 0x8888 / 0x1234 |
| Product string | "Car DSP AMP" |
| Manufacturer | "AIGER" |
| Firmware string | `A239-A-DP603-U5.6-250110-DSP1452-BMP885B` |
| DSP chip | ADAU1452 |
| MCU | BMP885B |

Firmware read in handshake via `cmd=0x04, reg=0x80f0`.

---

## Transport Layer

Transfer type is **CONTROL**, not Interrupt:
- `bmRequestType=0x21`, `bRequest=0x09` (HID SET_REPORT) — OUT
- `bmRequestType=0xa1`, `bRequest=0x01` (HID GET_REPORT) — IN
- `wValue=0x0002`, `wIndex=0x0004`, `wLength=0x0100` (256 bytes)

Each OUT: 8-byte SETUP + 256-byte payload = 264 bytes on wire.

---

## Packet Structure (confirmed)

```
OUT payload (256 bytes):
  [0]     0xe0          magic byte 0
  [1]     0xa2          magic byte 1
  [2]     CMD           command type
  [3]     0x00          always zero
  [4:6]   ADDR          uint16 LE — DSP parameter RAM base address
  [6]     SUB           sub-register / parameter type
  [7]     (REG_HI or DATA start)
  [8]     CSUM          checksum
  [9+]    DATA

IN response (256 bytes):
  [0:2]   STATUS        0x02 0x00 = OK, 0xee 0xbb = not connected
  [2:4]   0xe0 0xa2     magic echo
  [4:6]   DATA_LEN      uint16 LE
  [6:8]   ADDR          echo
  [8+]    DATA
```

---

## Checksum Formula (verified on 8 packets)

```
csum = (sum(pkt[4:13]) - 0x20) & 0xFF
```

Covers: addr_lo + addr_hi + sub + data_bytes[0..4].
Constant `0x20` applies to both HPF and GAIN command types.

---

## Confirmed Commands

### CMD 0x04 — WRITE_PARAM (known registers)

| Register | IN response | Purpose |
|----------|-------------|---------|
| reg=0x9909 | — | Unknown init (first cmd after connect) |
| reg=0x80f0 | firmware string in bytes[8:] | Read firmware |
| reg=0xa515 | short OK | Keepalive (sent repeatedly every ~500ms) |

### CMD 0x05 — READ_BLOCK (read channel state)

Format: `e0 a2 05 00 b0 00 04 CH CS 00...`
Checksum: `CS = 0x94 + CH`

| CH  | CS   | IN data |
|-----|------|---------|
| 0x00 | 0x94 | master block (different format, 0x8d response) |
| 0x01 | 0x95 | CH1 — 256 bytes of channel state |
| 0x02 | 0x96 | CH2 |
| ... | ... | ... |
| 0x0a | 0x9e | CH10 |

Response start: `f6 00 e0 a2 f2 00 b0 CH ...` for channels 1–10.
Master (CH0): `8d 00 e0 a2 89 00 b0 00 ...`

### CMD 0x0a — WRITE_DSP (confirmed parameters)

#### HPF Frequency — addr=0x07b7, sub=0x05

Observed: user dragged HPF slider on sub channels from 20.1 to 22.0 Hz.

```
e0 a2 0a 00  b7 07  05  [float32 LE freq]  [slope_code]  00  [CSUM]  00 10
```

| freq | float bytes | CSUM |
|------|-------------|------|
| 20.1 Hz | cd cc a0 41 | 0x22 |
| 20.2 Hz | 9a 99 a1 41 | 0xbd |
| 20.3 Hz | 67 66 a2 41 | 0x58 |
| 22.0 Hz | 04 00 b0 41 | 0x9d |

`slope_code = 0x05` — observed for 36 dB/oct filter (6th order).

#### Channel GAIN — addr=0x09b7, sub=0x26

Observed: user dragged gain from +0.1 to +10.0 dB and back.

```
e0 a2 0a 00  b7 09  26  00 40 9c 46  [gain_byte]  0a  [CSUM]  00 10
```

float32 `00 40 9c 46` = 20000.0 Hz (fixed reference, always the same).

| gain | gain_byte | CSUM |
|------|-----------|------|
| +0.1 dB | 0x79 | 0x6b |
| +0.2 dB | 0x7a | 0x6c |
| +0.9 dB | 0x81 | 0x73 |
| +10.0 dB | 0xdc | 0xce |

Gain encoding: `gain_dB = (byte - 0x78) / 10.0`

---

## Address Space Observations

`addr=0x07b7` → CH7 HPF frequency  
`addr=0x09b7` → CH8 GAIN  
Difference: `0x09b7 - 0x07b7 = 0x0200 = 512`

This stride of **0x200 = 512** is the per-channel parameter block size in ADAU1452 RAM.

Extrapolation (unverified):

| CH | Base addr | HPF freq | HPF slope | LPF freq | GAIN | ... |
|----|-----------|----------|-----------|----------|------|-----|
| 7 | 0x07b7 | 0x07b7+0x00 | 0x07b7+?? | 0x07b7+?? | 0x07b7+?? | |
| 8 | 0x09b7 | 0x09b7+0x00 | ... | ... | ... | |
| 9 | 0x0bb7 | 0x0bb7+0x00 | ... | | | |

(base = 0x07b7, stride = 0x0200 per channel)

---

## Handshake Sequence (usb1, packets 107–162)

```
#107 OUT: e0 a2 05 00 b7 00 03 11 ab 00...  (check connection)
#110 IN:  02 00 ee bb 00...                  (0xbbee = not connected)

#111 OUT: e0 a2 04 00 b0 00 09 99 ab 00...  (init param 0x9909)
(no response or empty)

#115 OUT: e0 a2 04 00 b0 00 f0 80 ab 00...  (read firmware)
#118 IN:  6a 00 e0 a2 66 00 b0 00 f0        (f0=sub echo)
          "A239-A-DP603-U5.6-250110-DSP1452-BMP885B"

#119 OUT: READ_BLOCK CH1  (e0 a2 05 00 b0 00 04 01 95...)
#122 IN:  f6 00 e0 a2 f2 00 b0 01 [256 bytes CH1 data]

#123 OUT: READ_BLOCK CH2
#126 IN:  f6 00 e0 a2 f2 00 b0 02 [256 bytes CH2 data]
...
#155 OUT: READ_BLOCK CH10
#158 IN:  f6 00 e0 a2 f2 00 b0 0a [256 bytes CH10 data]

#159 OUT: READ_BLOCK CH0 (master)
#162 IN:  8d 00 e0 a2 89 00 b0 00 [256 bytes master data]

(then keepalive every ~500ms)
#163+ OUT: e0 a2 04 00 b0 00 15 a5 94 00...  (keepalive reg=0xa515)
```

---

## STILL UNKNOWN from Wireshark

### Commands not yet captured

- [ ] **LPF frequency write** — should be near addr=0x07b7+offset or separate
- [ ] **EQ band freq, gain, Q write** — different addr range expected
- [ ] **MUTE** — likely a flag byte, addr unknown
- [ ] **SOLO** — addr unknown
- [ ] **Phase invert** — addr unknown
- [ ] **Delay / time alignment** — float in ms or samples, addr unknown
- [ ] **Routing matrix write** — multi-byte write, addr unknown
- [ ] **Preset save (M1..Mx)** — likely a separate command sequence
- [ ] **Preset load** — same
- [ ] **Bridge mode** — addr unknown
- [ ] **Input sensitivity** — addr unknown
- [ ] **CMD 0x08 / CMD 0x1c** — seen in handshake, content unclear

### Ambiguous

- `addr=0x09b7, sub=0x26` GAIN: what does fixed float `20000.0` mean?
  Could be a LPF reference frequency embedded in the same command.
- `slope_code=0x05` for 36dB/oct: need to capture other slopes (12, 24, 48 dB/oct)
  to confirm mapping.
- Last bytes `00 10` in 0x0a packets — meaning unknown (flags? padding?).
- CH0 "master" block format differs from CH1-10 — not yet decoded.
