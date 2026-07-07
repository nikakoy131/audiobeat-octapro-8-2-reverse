# PROTOCOL.md — Audiobeat OctaPro 8.2 / SP601 USB HID Protocol

Reverse engineered from:
- usb1.pcapng (2736 packets, enumeration + full readback)
- usb2.pcapng (566 packets, live EQ parameter changes)
- dsp_m2.dat  (preset export file, 2387 bytes)

---

## Device

| Field | Value |
|-------|-------|
| Brand | Audiobeat OctaPro 8.2 |
| OEM | Guangzhou Nisson / Sennuopu HIFI-X12 |
| USB VID | 0x8888 |
| USB PID | 0x1234 |
| USB Name | "Car DSP AMP" (mfr: "AIGER") |
| Speed | USB Full Speed (12 Mb/s) |
| DSP chip | ADAU1452 (Analog Devices) |
| MCU | BMP885B |
| Firmware | A239-A-DP603-U5.6-250110-DSP1452-BMP885B |
| Channels | 10 (8 amplified + 2 line out) |
| Amplifier | AB×6 + D×2 |

---

## USB Transport

Transfer type: **HID CONTROL** (not Interrupt!)

| Direction | bmRequestType | bRequest | wValue | wIndex | wLength |
|-----------|--------------|----------|--------|--------|---------|
| OUT (host→device) | 0x21 | 0x09 SET_REPORT | 0x0200 (Output, report ID 0) | 0x0004 | 256 |
| IN  (device→host) | 0xa1 | 0x01 GET_REPORT | 0x0100 (Input, report ID 0) | 0x0004 | 256 |

SETUP (8 bytes) + 256-byte payload = 264 bytes per transaction.

The protocol lives on **interface 4** (wIndex=4), a HID-class interface with
**no interrupt endpoints** — non-compliant per the HID spec, so OS HID stacks
do not bind to it (on macOS it does not exist as a HID device at all; hidapi
only sees interface 3, the media-key remote). Talk to it with **libusb**
(pyusb), claiming the unclaimed interface 4 and issuing the two control
transfers above per transaction. Verified live on macOS 2026-07-04, firmware
`A239-A-DP603-U5.6-250110-DSP1452-BMP885`.

Full interface map: 0 = audio control, 1/2 = audio streaming (USB Audio),
3 = HID consumer-control (volume/track/mute remote, 1-byte input report),
4 = HID DSP command channel (this protocol).

Interface 4's HID report descriptor (256-byte In + Out reports, 1-byte
Feature report, Usage Page `0xFF00`, no report IDs) and the full config
descriptor are dumped in [`docs/HID_DESCRIPTORS.md`](docs/HID_DESCRIPTORS.md)
— needed to build a virtual-device shim that the vendor app will enumerate.
Full shim design and rationale: [`docs/LINUX_UHID_SHIM_PLAN.md`](docs/LINUX_UHID_SHIM_PLAN.md).

---

## Packet Structure

### OUT (host → device): 256 bytes
```
[0]     0xe0          magic[0]
[1]     0xa2          magic[1]
[2]     CMD           command type
[3]     0x00          always 0
[4:6]   ADDR          target address, uint16 LE
[6:8]   REG/SUB       register or sub-address, uint16 LE
[8]     CSUM          checksum (see below)
[9:]    DATA          command payload
```

### IN (device → host): 256 bytes
```
[0]     STATUS_LO
[1]     STATUS_HI
[2:4]   0xe0 0xa2     magic echo
[4:6]   DATA_LEN      uint16 LE
[6:8]   ADDR          echo of request address
[8:]    DATA          response payload
```

---

## Checksum Formula

**Universal for all commands:**
```
csum = (sum(pkt[4:13]) - 0x20) & 0xFF
```
i.e. sum of: addr_lo + addr_hi + sub + data_bytes[0..4], minus 32, mod 256.

---

## Command Types

| CMD  | Name        | Description |
|------|-------------|-------------|
| 0x04 | WRITE_PARAM | Write single register parameter |
| 0x05 | READ_BLOCK  | Read full channel parameter block |
| 0x08 | ?           | Unknown (seen in handshake) |
| 0x0a | WRITE_DSP   | Write DSP RAM parameter (with float) |
| 0x1c | ?           | Unknown (seen in handshake) |

---

## CMD 0x05 — READ_BLOCK

Reads the full state of one channel (256 bytes).

```
OUT: e0 a2 05 00  b0 00  04 CH  CS  00...
                               ^
                               channel: 0x00=master, 0x01..0x0a=CH1..CH10
     csum = 0x94 + channel
```

Response: `f6 00 e0 a2 f2 00 b0 CH [256 bytes data]`

Checksum table:
| CH | csum |
|----|------|
| 0x00 | 0x94 |
| 0x01 | 0x95 |
| 0x0a | 0x9e |

---

## CMD 0x0a — WRITE_DSP (real-time parameter write)

Full 16-byte layout (verified by checksum analysis):

```
[0]     0xe0
[1]     0xa2
[2]     0x0a        CMD
[3]     0x00
[4:6]   ADDR        channel base address, uint16 LE  (CHn = 0x00b7 + n*0x0100)
[6]     SUB         parameter index within the channel block
[7:11]  float32 LE  parameter value
[11]    PARAM_BYTE  slope code (HPF) or gain byte (GAIN)
[12]    TYPE_BYTE   parameter qualifier: 0x00=HPF, 0x0a=GAIN
[13]    CSUM        checksum = (sum(pkt[4:13]) - 0x20) & 0xFF
[14]    0x00
[15]    0x10
```

**CSUM for 0x0a is at byte [13], NOT byte [8] like other commands.**

### Channel base address formula

`ADDR = 0x00b7 + channel_number × 0x0100`

| CH | ADDR   |   | CH | ADDR   |
|----|--------|---|----|--------|
|  1 | 0x01b7 |   |  6 | 0x06b7 |
|  2 | 0x02b7 |   |  7 | 0x07b7 |
|  3 | 0x03b7 |   |  8 | 0x08b7 |
|  4 | 0x04b7 |   |  9 | 0x09b7 |
|  5 | 0x05b7 |   | 10 | 0x0ab7 |

> **Correction from earlier docs:** The stride is **0x0100** (256) per channel,
> not 0x0200. The apparent 0x200 difference between 0x07b7 and 0x09b7 is because
> those examples happened to use CH7 and CH9 (two channels apart).

### Known parameter sub-addresses

| SUB  | byte[11]  | byte[12]  | Parameter | float32 meaning |
|------|-----------|-----------|-----------|-----------------|
| 0x05 | slope     | filter type | HPF | frequency Hz |
| 0x06 | slope     | filter type | LPF | frequency Hz |
| 0x08+band-1 | gain | Q byte | EQ band | center freq Hz |

Fully live-decoded 2026-07-06 — see "HPF/LPF crossover" and "EQ band" below.

**Slope code** (byte[11]) = `dB/oct = (code+1)*6`: `0x00`=6 … `0x05`=36 … `0x07`=48.
**Filter type** (byte[12]): `0x00`=Linkwitz-Riley, `0x01`=Bessel, `0x02`=Butterworth.

### HPF frequency example (CH7, older pcap — note the trailer)

```
e0 a2 0a 00 b7 07 05 cd cc a0 41 05 00 22 00 10  (HPF=20.1 Hz, LR, 36 dB/oct)
```
This older capture has `00 10` at [14:16]; the current app sends `00 00`
there. The trailer is outside the checksum ([13]) and ignored by the device.

Byte map for first packet:
```
e0 a2 0a 00 | b7 07 | 05 | cd cc a0 41 | 05 | 00 | 22 | 00 10
  magic       addr    sub   float=20.1   slp  typ  csum tail
```

### Channel GAIN example (CH9):

```
e0 a2 0a 00 b7 09 26 00 40 9c 46 79 0a 6b 00 10  (gain=+0.1 dB)
e0 a2 0a 00 b7 09 26 00 40 9c 46 dc 0a ce 00 10  (gain=+10.0 dB)
```

Gain byte encoding: `gain_dB = (byte - 0x78) / 10.0`

| byte | dB      |   | byte | dB     |
|------|---------|---|------|--------|
| 0x80 | -inf (mute) | | 0x78 | 0.0  |
| 0x6e | -1.0    |   | 0x88 | +1.6   |
| 0x5a | -3.0    |   | 0xdc | +10.0  |

---

## CMD 0x04 — WRITE_PARAM

```
e0 a2 04 00  b0 00  REG_LO REG_HI  CSUM  DATA...
```

| Register | Purpose |
|----------|---------|
| 0x80f0   | Read firmware string |
| 0xa515   | Keepalive (every ~500ms) |
| 0x9909   | Init param (unknown) |

---

## Handshake Sequence

```
1. Session open (MANDATORY — device refuses channel reads until sent):
   OUT: e0 a2 05 00 b7 00 03 11 ab 00...
   IN:  02 00 ee bb 00...
   Without this packet READ_BLOCK answers with a short refusal ACK
   `02 00 ee 55` instead of the channel block (verified on live device).

2. Init param:
   OUT: e0 a2 04 00 b0 00 09 99 ab 00...

3. Read firmware:
   OUT: e0 a2 04 00 b0 00 f0 80 ab 00...
   IN:  2f 00 e0 a2 2b 00 b0 00 09 "A239-A-DP603-U5.6-250110-DSP1452-BMP885B"

4. Read all channels:
   for ch in range(0x00, 0x0b):
       OUT: e0 a2 05 00 b0 00 04 CH (0x94+CH) 00...
       IN:  f6 00 e0 a2 f2 00 b0 CH [256 bytes]

5. Start keepalive loop (every ~500ms):
   OUT: e0 a2 04 00 b0 00 15 a5 94 00...
```

---

## Channel Data Block Layout

Used in both the **USB channel readback** (CMD 0x05 response) and the **.dat preset file**.

### USB channel readback (CMD 0x05 response data, 242 bytes after 8-byte IN header)

```
[0]      prefix byte (0x00)
[1:33]   routing matrix — 32 bytes (same as .dat [0:32])
[33:39]  unknown (6 bytes, typically zeros)
[39:43]  float32 LE  HPF frequency (Hz)
[43]     HPF slope code  (0x05=36dB/oct, 0x03=12dB/oct)
[44]     unknown (0x00)
[45:49]  float32 LE  LPF frequency (Hz)   20600.0 = bypass
[49]     LPF slope code  (0x03 observed)
[50:52]  unknown flags (2 bytes)
[52]     EQ section marker (0x06)
[53:239] EQ data — 31 bands × 6 bytes each
[239]    trailing byte (varies per channel)
[240:242] padding zeros
```

### .dat Preset File Format (US002)

```
Header: "US002" (5 bytes ASCII)
Body:   10 × 238 bytes  (one block per channel, stride confirmed)
```

> **Correction from earlier docs:** Block size is **238 bytes** (not 290), giving
> 5 + 10×238 = 2385 bytes (file is 2387 bytes with 2-byte terminator).

### .dat Channel Block (238 bytes)

```
[0:32]   Routing matrix — 32 bytes
         Each byte = signed int8 gain / 10.0 dB
           0x80 = -inf (mute)     0x78 = 0.0 dB
           0xe4 = -2.8 dB         0x64 = +10.0 dB
           0xb2 = -7.8 dB

[32:38]  unknown (6 bytes)
[38:42]  float32  HPF frequency (Hz)     [USB: cd[39:43]]
[42]     HPF slope code
[43]     unknown
[44:48]  float32  LPF frequency (Hz)   20600.0 = bypass  [USB: cd[45:49]]
[48]     LPF slope code
[49:52]  unknown flags

[52]     EQ section marker (0x06)
[52:238] EQ data — 31 bands × 6 bytes each  [USB: cd[53:239]]
```

### EQ Band structure (6 bytes × 31 bands)

31 bands, 1/3-octave from 20 Hz to 20 kHz:

```
[0:4]   float32 LE  center frequency (Hz)
[4]     gain byte: (byte - 0x78) / 10.0 dB  (same encoding as GAIN command)
[5]     Q byte  (0x0a = default Q; first band may differ)
```

Band center frequencies (confirmed from readback):

| # | Hz   | # | Hz   | # | Hz    | # | Hz    |
|---|------|---|------|---|-------|---|-------|
| 1 | 20   | 9 | 125  |17 | 800   |25 | 5000  |
| 2 | 25   |10 | 160  |18 | 1000  |26 | 6300  |
| 3 | 31.5 |11 | 200  |19 | 1250  |27 | 8000  |
| 4 | 40   |12 | 250  |20 | 1600  |28 | 10000 |
| 5 | 50   |13 | 315  |21 | 2000  |29 | 12500 |
| 6 | 63   |14 | 400  |22 | 2500  |30 | 16000 |
| 7 | 80   |15 | 500  |23 | 3150  |31 | 20000 |
| 8 | 100  |16 | 630  |24 | 4000  |   |       |

### Channel layout (from dsp_m2.dat)

| CH | Role      | LPF     | Routing |
|----|-----------|---------|---------|
| 1  | Front L   | 20600   | Out1 |
| 2  | Front R   | 20600   | Out2 |
| 3  | Mid/Rear L| 20600   | Out3 |
| 4  | Mid/Rear R| 20600   | Out4 |
| 5  | Tweeter L | 3500    | Out5 |
| 6  | Tweeter R | 3500    | Out6 |
| 7  | Sub L     | 80      | Out1+2 |
| 8  | Sub R     | 80      | Out1+2 |
| 9  | Line Out 1| 20600   | Out1 |
| 10 | Line Out 2| 20600   | Out2 |

---

## Reference Client (pyusb)

hidapi **cannot** be used: the DSP interface (4) has no interrupt endpoints,
so the OS HID stack never exposes it (see *USB Transport*). This pyusb client
is verified against a live device:

```python
import struct
import usb.core, usb.util

VID, PID, INTERFACE = 0x8888, 0x1234, 4

def open_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    assert dev, "device not connected"
    try:
        if dev.is_kernel_driver_active(INTERFACE):
            dev.detach_kernel_driver(INTERFACE)     # Linux
    except NotImplementedError:
        pass                                        # macOS: unclaimed anyway
    usb.util.claim_interface(dev, INTERFACE)
    transact(dev, make_cmd(0x05, 0x00b7, 0x1103))   # mandatory session open
    return dev

def transact(dev, payload: bytes) -> bytes:
    assert len(payload) == 256
    dev.ctrl_transfer(0x21, 0x09, 0x0200, INTERFACE, payload, timeout=1000)
    return bytes(dev.ctrl_transfer(0xA1, 0x01, 0x0100, INTERFACE, 256, timeout=1000))

def checksum(pkt) -> int:
    return (sum(pkt[4:13]) - 0x20) & 0xFF

def make_cmd(cmd, addr, sub, csum=None):
    pkt = bytearray(256)
    pkt[0]=0xe0; pkt[1]=0xa2; pkt[2]=cmd; pkt[3]=0x00
    struct.pack_into('<H', pkt, 4, addr)
    struct.pack_into('<H', pkt, 6, sub)
    pkt[8] = checksum(pkt) if csum is None else csum
    return bytes(pkt)

def read_channel(dev, ch: int) -> bytes:
    # wire bytes [6:8] = 04 CH  ->  LE u16 sub = (CH << 8) | 0x04
    return transact(dev, make_cmd(0x05, 0x00b0, (ch << 8) | 0x04, csum=0x94+ch))

def get_firmware(dev) -> str:
    r = transact(dev, make_cmd(0x04, 0x00b0, 0x80f0))
    s = r[10:80]                      # printable ASCII banner starts at [10]
    end = next((i for i, b in enumerate(s) if not 0x20 <= b <= 0x7e), len(s))
    return s[:end].decode()

def write_hpf(dev, addr: int, freq_hz: float, slope_code: int = 0x05):
    """Write HPF frequency. slope_code 0x05 observed for 36dB/oct."""
    pkt = bytearray(256)
    pkt[0]=0xe0; pkt[1]=0xa2; pkt[2]=0x0a; pkt[3]=0x00
    struct.pack_into('<H', pkt, 4, addr)
    pkt[6] = 0x05   # sub
    struct.pack_into('<f', pkt, 7, freq_hz)
    pkt[11] = slope_code
    pkt[12] = 0x00
    pkt[13] = checksum(pkt)
    return transact(dev, bytes(pkt))

def write_gain(dev, addr: int, gain_db: float):
    """gain_db in range -12.8..+12.7 (limited by byte encoding)"""
    gain_byte = max(0, min(255, int(round(gain_db * 10)) + 0x78))
    pkt = bytearray(256)
    pkt[0]=0xe0; pkt[1]=0xa2; pkt[2]=0x0a; pkt[3]=0x00
    struct.pack_into('<H', pkt, 4, addr)
    pkt[6] = 0x26   # sub
    struct.pack_into('<f', pkt, 7, 20000.0)   # fixed reference
    pkt[11] = gain_byte
    pkt[12] = 0x0a
    pkt[13] = checksum(pkt)
    return transact(dev, bytes(pkt))

def keepalive(dev):
    transact(dev, make_cmd(0x04, 0x00b0, 0xa515, csum=0x94))

if __name__ == '__main__':
    dev = open_device()
    print(get_firmware(dev))
    for ch in range(11):
        d = read_channel(dev, ch)
        print(f'CH{ch}: {d[:16].hex()}')
    usb.util.release_interface(dev, INTERFACE)
    usb.util.dispose_resources(dev)
```

---

## CMD 0x05 — DSP Channel Trigger (addr=0xNNb7, sub=0x01)

Distinct from the channel readback command. Sends to per-channel DSP base addresses:

```
OUT: e0 a2 05 00  NNb7  01 00  CS  data...
```

Returns `02 00 ee bb 00...` (status=0x0002, magic=eebb, no payload). Appears after
groups of WRITE_DSP (0x0a) commands, once per modified channel. Likely a
**"commit / notify DSP" trigger** — telling the MCU to apply buffered parameter
changes to that channel's DSP block. Requires further confirmation.

---

## IN Response Status Codes

| STATUS (LE) | magic  | Meaning / trigger command |
|-------------|--------|---------------------------|
| 0x0002      | `eebb` | Acknowledged, no data (CMD 0x08, 0x1c, CMD 0x05 DSP trigger) |
| 0x0002      | `ee55` | Refused — READ_BLOCK before session open, or malformed SUB bytes (live-verified) |
| 0x000f      | `e0a2` | Keepalive ack (CMD 0x04 reg=0xa515) |
| 0x002f      | `e0a2` | Short info response (CMD 0x04 reg=0x9909, dlen=43) |
| 0x006a      | `e0a2` | Firmware string response (CMD 0x04 reg=0x80f0, dlen=102) |
| 0x008d      | `e0a2` | Master channel (CH0) read (dlen=137) |
| 0x00f6      | `e0a2` | Full channel read (CMD 0x05 reg=0x04/CHn, dlen=242) |

Magic `eebb` (= 0xbbee LE) is returned for any command the device acknowledges
without returning a data payload. It does **not** mean "not connected" in all cases —
only the initial status check (`CMD 0x05 addr=0x00b7 sub=0x03`) uses it as a
disconnected-device indicator.

---

## Keepalive Echo Behaviour

After the first WRITE_DSP (0x0a) write, the keepalive payload `d[9:16]` echoes
the last written parameter's data bytes (same bytes as 0x0a `d[9:16]`). The echo
persists in every subsequent keepalive until the next write.

### Volume terminology

The device has **one master volume value (per input source)** with **two
controls** (RESOLVED 2026-07-05):
- **knob-vol** — the remote panel knob (0–35 steps), echoed in the keepalive.
  CLI: `read knob-vol`.
- **master** — the software "Main" fader (area C of the PC app) = **CH0**
  (addr `0x00b7`). CLI: `read master`.

Evidence that they are the same value:
1. Manual p.14 (Wire Controller): "the rotate button adjusts the **main
   volume (main volume 0-35)**" — the knob is explicitly the main volume.
2. Manual p.10 (Main volume adjustment): Main fader range **+6 ~ −60 dB** —
   exactly the live-calibrated knob endpoints.
3. Live: turning the knob moves the CH0 block float [9:13] byte-for-byte in
   step with the keepalive float.
4. The full 137-byte CH0 block from usb1.pcapng (vendor app running) differs
   from a live read only in the volume float and the [134] trailer byte —
   there is no second volume-like field anywhere in the readback.

Nuance: the register holds the *current source's* level — each input source
remembers its own knob-vol (see *Input source readback* below).

The installer-style "set once" output limits are the **per-channel** gain
faders (0…−40/OFF, stored in each channel block), not the Main fader.

### knob-vol readback (LIVE-CONFIRMED 2026-07-04)

The keepalive response (status `0x000f`, dlen 11) carries **knob-vol**
as float32 LE dB at bytes **[12:16]** of the raw IN packet:

```
0f 00 e0 a2 0b 00 b0 00 | 15 00 01 02 | VV VV VV VV | CK | 00...
  status    dlen  addr    reg echo      float32 dB    trailer csum
```

Verified by stepping the physical remote knob across its range:

| Knob | dB | raw |
|------|--------|-------------|
| 0 | −60.00 | `00 00 70 c2` |
| 5 | −33.17 | `14 ae 04 c2` |
| 15 | −14.19 | `3d 0a 63 c1` |
| 25 | −3.33 | `b8 1e 55 c0` |
| 30 | +1.12 | `29 5c 8f 3f` |
| 34 | +5.11 | `1f 85 a3 40` |
| 35 | +6.00 | `00 00 c0 40` |

Endpoints are exactly the manual's −60/+6 dB; the interior is an audio-taper
lookup curve (≈1 dB/step near max, ≈1.9 dB/step near min), not a formula.
The **same float** appears in the master block (CH0 read) at data bytes [9:13] —
knob and Main fader are two controls for this one register (see *Volume
terminology* above).

**Trailer checksum** at [16]: `(sum(resp[8:16]) − 0x70) & 0xFF` — fits all
live samples (n=4: `0xa8`, `0xda`, `0x2f`, `0x72`); treat as hypothesis.
Different constant from the OUT checksum's `− 0x20`.

CLI: `octaproctl read knob-vol`.

### Master (CH0) block layout — status 0x008d, dlen 137

| Offset | Type | Field |
|---|---|---|
| `[0:9]` | bytes | prefix `00 55 55 55 55 55 00 02 01` |
| `[9:13]` | float32 LE | **main volume dB** — the shared master register |
| `[13:27]` | — | unknown (zeros in both dumps) |
| `[27:31]` | float32 LE | **noise gate threshold dB** — `−88.0`; matches the factory "Noise gate threshold" dialog (manual p.9, "factory set, do not operate by yourself") |
| `[31:94]` | — | unknown — two `01 00 02 00 04 00 … 80 00` bit patterns |
| `[94]` | u8 | firmware string length (`0x27` = 39) |
| `[95:134]` | ASCII | firmware banner |
| `[134]` | u8 | varies between reads — checksum-like |
| `[135:137]` | — | zeros |

Cross-checked: live read 2026-07-05 vs usb1.pcapng frame 162 (vendor app on
Windows) — identical except the volume float and `[134]`.

CLI: `octaproctl read master`.

### Input source readback & per-source volume (LIVE-MAPPED 2026-07-05)

Keepalive response byte **[11]** is the current input source ID. Mapped by
cycling the remote panel's source menu (IDs follow the menu order):

| ID | Source | Stored knob-vol observed |
|----|--------|--------------------------|
| `0x00` | high level | 35 (+6.00 dB, max — likely pass-through default for head units) |
| `0x01` | low level | 29 (0.00 dB) |
| `0x02` | opt | 30 (+1.12 dB) |
| `0x03` | USB AUDIO | 18 (−10.00 dB) |

**Each source stores its own knob-vol level** — the keepalive float [12:16]
is the *current source's* volume and changes when the source switches.
(The panel's displayed knob step confirmed the taper table at two new
anchors: step 29 = 0.00 dB, step 18 = −10.00 dB.)

The PC-app source list also includes Bluetooth and U-disk (manual p.9); their
IDs are unmapped (not in this unit's panel menu; presumably `0x04`/`0x05`).

CLI: `octaproctl read knob-vol` shows the source name + ID.

### CMD 0x05 channel-flag family (mute, phase, …)

Live capture 2026-07-06 (uhid shim) revealed that several per-channel
boolean controls share one command shape:

```
e0 a2 05 00 b7 NN <selector> <state> <csum>
               (addr 0xNNb7 = channel_addr(ch); NN = channel number)
```

- **byte[6] = selector** picks the parameter
- **byte[7] = state** (1 = on, 0 = off)
- **byte[8] = checksum** — universal `(sum(pkt[4:13]) - 0x20) & 0xFF`

| selector (byte[6]) | control | verified |
|--------------------|---------|----------|
| `0x01` | per-channel mute | CH2/6/10 on, CH6 off |
| `0x02` | phase invert (1=180°, 0=0°) | CH6 on/off |
| `0x07` | EQ pass/bypass (1=bypass) | CH7 on/off |
| `0x0d` | **master** mute (ch0 only) | on/off |

Builders: `packet.build_channel_flag(ch, selector, on)`, with `build_mute`,
`build_phase`, `build_eq_pass` as named wrappers. More selectors likely
exist — capture them the same way. No commit packet follows any of these;
they apply immediately.

**EQ RST (reset) — SOLVED 2026-07-06.** The EQ "RST" button flattens a
channel's EQ. It shares selector `0x07` with EQ pass but is distinguished by
the address: RST uses the **fixed master address `0x00b7`** and puts the
**target channel in byte[7]**:

```
reset ch7: e0 a2 05 00 b7 00 07 07 a5
reset ch3: e0 a2 05 00 b7 00 07 03 a1
reset ALL: e0 a2 05 00 b7 00 07 ff 9d   (byte[7] = 0xff)
```

The device flattens the band gains itself (no 31-band write burst). Confirmed
on two channels (byte[7] = 0x07, 0x03) plus the **"reset all"** dialog option,
which is the same packet with **byte[7] = `0xff`** (all-channels sentinel;
`constants.EQ_RESET_ALL`) — live-captured 2026-07-06. Builder
`packet.build_eq_reset(ch)` (ch = 1..10 or `EQ_RESET_ALL`); CLI `write eq-reset
--channel N` or `write eq-reset --all`.

So selector `0x07` means two things by address: at `0xNNb7` → EQ pass toggle
(byte[7]=bool); at `0x00b7` → reset channel byte[7]'s EQ.

### Speaker type — SOLVED 2026-07-06 (CMD 0x05 selector 0x30, 1..6 enum)

Per-channel speaker type (HF/MF/LF/MHF/MLF/FF). Same opcode and addressing as
the channel-flag family, but with its **own selector byte[6]=`0x30`** and a
**1..6 enum in byte[7]** instead of a 0/1 bool:

```
e0 a2 05 00 b7 NN 30 <code> <csum>
```

| code (byte[7]) | type | verified |
|----------------|------|----------|
| `0x01` | HF (high freq)      | ✓ CH3 |
| `0x02` | MF (mid freq)       | interpolated |
| `0x03` | LF (low freq)       | ✓ CH3 |
| `0x04` | MHF (mid-high freq) | interpolated |
| `0x05` | MLF (mid-low freq)  | interpolated |
| `0x06` | FF (full freq)      | ✓ CH3 |

Codes follow the app's menu order; HF(1)/LF(3)/FF(6) captured byte-perfect on
CH3, the rest interpolated on that linear sequence. The app appends a fixed
5-byte trailer `a0 41 78 26 1f` at `[9:14]` that the checksum does **not**
cover (byte[8] = `(sum(pkt[4:8]) − 0x20)` — equivalently the universal checksum
with a zero trailer); it is stale app-buffer data the firmware ignores, so the
builder sends a clean zero trailer. Builder `packet.build_speaker_type(ch,
code)`; CLI `write speaker-type --channel N --type hf|mf|lf|mhf|mlf|ff`.

### Noise gate — SOLVED 2026-07-06 (get / set / on-off — FACTORY-LOCKED)

The noise-gate threshold lives in the app's Setting/Option dropdown, not the
main UI. The manual says **"do not operate by yourself (factory set)"**. Three
operations, all live-captured:

| op | packet | notes |
|----|--------|-------|
| **get** | `e0 a2 04 00 b0 00 12 a2 94` | CMD 0x04 WRITE_PARAM reg `0xa212` @ `0x00b0` (magic csum `0x94`). Triggers a floor re-measurement; the value returns on the read side (also CH0 block `[27:31]`, factory −88.0). |
| **set** | `e0 a2 08 00 b7 00 12 <f32 dB> <csum>` | CMD 0x08 **sub `0x12`** — the master-volume float-write family with a different sub-byte. Captured `-88.0` → `00 00 b0 c2`, csum `1b`. |
| **on/off** | `e0 a2 05 00 b7 00 29 <1|0> <csum>` | CMD 0x05 selector `0x29` @ `0x00b7`; byte[7]=1 on / 0 off. Captured off → `…29 00 c0`. |

Note: with the uhid shim (canned replies), "get" reads back the shim's canned
CH0 floor (−88.0), so "set" re-sends −88.0 regardless of the typed value — on
real hardware "get" measures the live floor. Builders `packet.
build_noise_gate_get()` / `build_noise_gate_set(db)` / `build_noise_gate_onoff
(on)`; CLI `write noise-gate get|set --db X|on|off` (warns it's factory-locked).

### Preset save / recall — SOLVED 2026-07-06 (CMD 0x08 sub 0x06, M1–M6)

The 6 preset slots (M1–M6) save/recall via **CMD 0x08, sub-byte `0x06`**, addr
`0x00b7` — the "0x06 sub-family" earlier notes left unidentified. **byte[7]
encodes both the operation and the slot:**

```
save   Ms:  e0 a2 08 00 b7 00 06 <0x80|s> 00 00 00 <csum> 80
recall Ms:  e0 a2 08 00 b7 00 06 <s>      00 00 00 <csum> 00
```

- **byte[7]** = `0x80 | slot` (save) or `slot` (recall) — the high bit is the
  save/recall discriminator. Verified saves M1/M2/M5/M6, recalls M3/M5.
- **byte[8:11]** are stale buffer bytes the device ignores (the app sends
  leftovers; the builder zeros them).
- **checksum** at byte[11] = `(sum(pkt[4:11]) − 0x20) & 0xFF`.
- **byte[12]** trailer = `0x80` (save) / `0x00` (recall).

On recall the app additionally emits a `0x1c` walking-bit refresh packet (the
same companion seen with bridge) and then re-reads every channel to repaint its
UI — but the **device applies the preset on this single 0x08 packet**. Builders
`packet.build_preset_save(slot)` / `build_preset_recall(slot)`; CLI `write
preset-save --slot N` / `write preset-recall --slot N`.

### Routing matrix write — SOLVED 2026-07-06 (CMD 0x20, per output row)

The crosspoint mixer is a new opcode **`0x20`**, **one packet per output
channel** (addr `0x0Nb7`), carrying that output's full **14-input** routing row.
The device exposes **14 inputs × 10 outputs**; the 14 inputs, in order, are:
`IN-1..IN-6, BT-L, BT-R, UDISK-L, UDISK-R, OPT-L, OPT-R, USB-L, USB-R`.

**Crosspoint value** = `0x80 + percent` (0..100): `0x80` = 0%/off, `0xe4` =
100%. **Checksum** at byte[35] = `(sum(pkt[4:35]) − 0x20) & 0xFF` (same `−0x20`
constant, wider span). The 14 crosspoints are **non-contiguous**:

| bytes | inputs |
|-------|--------|
| `[7:13]` | IN-1 … IN-6 |
| `[23:29]` | BT-L, BT-R, UDISK-L, UDISK-R, OPT-L, OPT-R |
| `[31:33]` | USB-L, USB-R |

The remaining bytes are **structural**, keyed to the output via
`m = ((n − 1) mod 8) + 1` (so CH9/CH10 wrap to behave like CH1/CH2):
- **segB** `[15:23]` = `[0x80]*6 + [0x00]*2` with a one-hot `0xe4` "self" marker
  at slot `m − 1`.
- an **odd/even (L/R) `0x64` flag** at `[29]`&`[33]` (odd `n`) or `[30]`&`[34]`
  (even `n`).
- default self-routing: output N receives input `IN-m` at 100%.

Fully mapped byte-map (CH1, every input a distinct %):
```
idx:  7  8  9 10 11 12|13 14|15 16 17 18 19 20 21 22|23 24 25 26 27 28|29 30|31 32|33 34|35
CH1:  8b 96 a1 ac b7 c2|00 00|e4 80 80 80 80 80 00 00|8a 94 9e a8 b2 bc|64 00|c6 d0|64 00|13
      IN1 2  3  4  5  6         (segB one-hot @ m)     BTl r  Ul r  Ol r        USl r
```

Verified byte-perfect on **all outputs 1–10**. Standard outputs (1–6, 9, 10) use
the segB one-hot + `0x64` template above. **CH7/CH8 (the sub pair) use a
DISTINCT fixed template** — same crosspoint positions and `0x80+pct` encoding,
but `segB [15:23] = b2 b2 80 80 80 80 00 00` (no one-hot `0xe4`) and both bytes
of each L/R flag pair (`[29,30]`, `[33,34]`) are `0x32` instead of one-hot
`0x64`. This is independent of bridge state (verified un-bridged); CH7 and CH8
are independent outputs that merely share this template. Example (CH7, IN-1=30%,
BT-L=70%, USB-R=80%, others 50%/0%):
```
e0 a2 20 00 b7 07 00 9e b2 80 80 80 80 00 00 b2 b2 80 80 80 80 00 00 c6 b2 b2 b2 b2 b2 32 32 b2 d0 32 32 dc
```

Because CMD 0x20 rewrites the whole row atomically and **cannot be read back**,
a single-crosspoint edit is not possible; you must specify all 14 levels.
Builder `packet.build_routing_row(output_ch, levels)`; CLI `write routing
--output N --levels "p1,…,p14"` (dry-run prints the row table + packet).

### Input source select — SOLVED 2026-07-06 (CMD 0x05, TWO registers)

The app exposes **two independent source dropdowns**, matching the device's two
priority tiers — not one "source" enum. Both are CMD 0x05 at the **global addr
`0x00b7`**, channel-flag shape (byte[6]=selector, byte[7]=code, byte[8]=checksum,
plus the same fixed `a0 41 78 26 1f` stale trailer the checksum ignores):

```
e0 a2 05 00 b7 00 <selector> <code> <csum>
```

**LOW source** (normal priority) — selector `0x26`. byte[7] is the same enum as
the keepalive-read source ID (`SOURCE_NAMES`):

| code | source | verified |
|------|--------|----------|
| `0x00` | high level | ✓ |
| `0x01` | low level  | ✓ |
| `0x02` | opt        | (read ID) |
| `0x03` | USB audio  | (read ID) |

**HIGH source** (high-priority auto-switch: BT / U-disk) — selector `0x0e`:

| code | source | verified |
|------|--------|----------|
| `0x00` | BT       | ✓ |
| `0x01` | USB disk | ✓ |

Live captures (byte-perfect): low `…26 00 bd` / `…26 01 be`, high `…0e 00 a5`
/ `…0e 01 a6`. Builders `packet.build_source_low(code)` /
`build_source_high(code)`; CLI `write source-low --to high-level|low-level|opt|
usb-audio` and `write source-high --to bt|usb-disk`. Note: when the shim (or a
real device that rejects the change) keeps echoing the old source in its
keepalive reply, the app's dropdown snaps back — the write packet is still sent.

### Solo — SOLVED 2026-07-06 (client-side macro, NOT a device command)

Solo has **no wire command of its own**. Live capture 2026-07-06 (uhid shim)
proved the vendor app implements it entirely on the host as *"mute every other
channel"*, reusing the per-channel mute above:

```
solo CH3 ON  → build_mute(ch, on)  for ch in 1..10, ch ≠ 3
solo CH3 OFF → build_mute(ch, off) for ch in 1..10, ch ≠ 3
```

Captured: pressing solo on CH3 sent nine `sub 0x0101` mutes (CH1,2,4,5,6,7,8,
9,10); releasing it sent nine `sub 0x0001` unmutes to the same set. The soloed
channel receives nothing. The app does **not** remember which channels were
already muted — solo-off blindly unmutes all others. CLI `write solo
--channel N --on/--off` reproduces the macro; helper `commands.write.
solo_packets(ch, on)` returns the `[(ch, packet), …]` list.

### Mute write — SOLVED 2026-07-06 (CMD 0x05; master and channel differ)

Mute toggle, live-captured 2026-07-06 via the uhid shim
(docs/LINUX_UHID_SHIM_PLAN.md) by toggling the app's mute buttons. Reuses
opcode `0x05`. **The master and per-channel forms use different sub-bytes**
— an asymmetry in the firmware, but both directly verified:

```
master  MUTE ON:   e0 a2 05 00 b7 00 0d 01 a5     byte[6]=0x0d
master  MUTE OFF:  e0 a2 05 00 b7 00 0d 00 a4
CH2     MUTE ON:   e0 a2 05 00 b7 02 01 01 9b     byte[6]=0x01
CH6     MUTE ON:   e0 a2 05 00 b7 06 01 01 9f
CH10    MUTE ON:   e0 a2 05 00 b7 0a 01 01 a3
CH6     MUTE OFF:  e0 a2 05 00 b7 06 01 00 9e
```

| Field | Bytes | Meaning |
|-------|-------|---------|
| magic | `e0 a2` | |
| CMD | `05` | same opcode as read/commit |
| — | `00` | |
| ADDR | `b7 NN` | LE `0xNNb7` = `channel_addr(ch)` (`00b7`=master, `0Nb7`=CH N) |
| sub-byte | `0d` / `01` | byte [6]: **0x0d for master, 0x01 for CH1–10** |
| state | `01`/`00` | byte [7]: 1 = mute, 0 = unmute |
| checksum | | byte [8]: `(sum(pkt[4:13]) - 0x20) & 0xFF` (universal formula) |

All samples byte-perfect including checksum (verified: master on/off,
CH2/6/10 mute, CH6 unmute). No commit packet follows; applies immediately.

**Note on the per-channel form:** byte[6]=0x01 makes the LE u16 sub read
`0x0101` (mute) / `0x0001` (unmute) — the exact signature earlier notes
guessed was a "DSP commit trigger" (see below). That guess was wrong; those
captures were mute toggles.

**Caveat:** the master captures had `5e c2 8f` trailing at bytes [9:12] —
stale buffer bleed (the vendor app reuses one HID buffer that still held the
last keepalive volume float), **not** part of the command. A clean packet
zero-fills the tail; the device ignores it.

CLI: `write mute --channel <n> --on|--off --commit` (master by default).
Builder: `packet.build_mute(ch, mute)`.

**Solo is not a distinct command.** Toggling a channel's Solo in the app
(tested on CH4, 2026-07-06) emits bytes **byte-identical to a per-channel
mute** of that channel (selector `0x01`) — and nothing on the other
channels. Solo is handled app-side; there is no separate protocol command to
add, and `write mute` already covers the wire traffic.

### Phase invert — SOLVED 2026-07-06 (CMD 0x05 selector 0x02)

A member of the channel-flag family above. Live-captured by toggling
channel 6's phase invert in the app:

```
180° (invert): e0 a2 05 00 b7 06 02 01 a0
  0° (normal): e0 a2 05 00 b7 06 02 00 9f
```

byte[6]=`0x02`, byte[7]=`01` (180°) / `00` (0°). Both byte-perfect incl.
checksum. Only channel 6 live-verified; other channels follow from the
shared `channel_addr` addressing.

CLI: `write phase --channel <n> --invert|--normal --commit`. Builder:
`packet.build_phase(ch, invert)`.

### Bridge CH7+CH8 — SOLVED 2026-07-06 (CMD 0x1c, not a channel flag)

Bridging is only available for the CH7+CH8 pair on this hardware. Unlike
mute/phase, it is **not** a channel-flag; it's **CMD 0x1c** with a fixed
23-byte "walking-bit" payload, live-captured by toggling the bridge:

```
bridged:   e0 a2 1c 00 b7 00 28 01 00 02 00 04 00 08 00 10 00 20 00 c0 00 80 00 00 01 00 02 00 04 00 08 4d
unbridged: e0 a2 1c 00 b7 00 28 01 00 02 00 04 00 08 00 10 00 20 00 40 00 80 00 00 01 00 02 00 04 00 08 cd
                                                             ↑byte[19]                                  ↑csum[31]
```

- addr `0x00b7`, byte[6]=`0x28`, byte[7]=`0x01`
- **only byte[19] changes**: bit `0x80` set = bridged (`0x40`→`0xc0`)
- checksum at byte[31] = `(sum(pkt[4:31]) - 0x20) & 0xFF` — spans a wider
  range than the short commands' `[4:13]`
- the app also emits a companion **sub-`0x21`** CMD 0x1c packet that is
  **constant** regardless of bridge state (a UI-sync, also seen at
  enumeration — see the reclassification note below); not part of the write

CLI: `write bridge --on|--off --commit`. Builder: `packet.build_bridge(on)`.

The rest of the payload is treated as a fixed template (it never varied
across captures). If a future capture shows it encoding other live state,
revisit `BRIDGE_PAYLOAD_TEMPLATE`.

### CMD 0x08 float-write family (volume, faders, delay) — SOLVED (not WRITE_DSP)

**CMD `0x08` is a general float32-parameter write** — a float at [7:11] with
the checksum at [11], no commit. The sub-byte at [6] + the address select
which parameter:

| Control | addr | sub [6] | value | verified |
|---------|------|---------|-------|----------|
| Master (Main) volume | `0x00b7` | `0x0c` | dB | 17 samples + blind −20.0 dB check |
| Channel N fader/gain | `0xNNb7` | `0x03` | dB | CH3 → −6.00 dB (2026-07-06) |
| Channel N delay | `0xNNb7` | `0x04` | ms | CH2 → 1.512 ms (2026-07-06) |

All are float32 at [7:11], checksum `(sum(pkt[4:11]) - 0x20) & 0xFF` at [11],
applied immediately. Distinct DSP parameters likely occupy further sub-bytes
on this same command — a fast thing to sweep.

> ⚠️ Neither uses `WRITE_DSP` (CMD `0x0a`). The old `write gain` built a
> `0x0a` sub `0x26` packet (inferred from pcaps, byte-encoded gain) that
> **never matched app fader traffic** — `write gain` now emits CMD `0x08`
> sub `0x03`. And **CH0 `WRITE_DSP` is still DANGEROUS**: it force-switches
> the input source, it is not a volume write (see the retraction below).

**Channel fader** (live CH3 → −6.0 dB): `e0 a2 08 00 b7 03 03 00 00 c0 c0 1d`
— `0000c0c0` = −6.00 dB, checksum `1d` = `(sum(pkt[4:11]) - 0x20) & 0xFF`.
Builder `packet.build_channel_gain(ch, db)`; CLI `write gain --channel N --db F`.

**Channel delay** (live CH2 → 1.512 ms): `e0 a2 08 00 b7 02 04 37 89 c1 3f 5d`
— `3789c13f` = 1.512 ms (plain milliseconds; the app's cm/inch modes convert
to ms before sending). Builder `packet.build_channel_delay(ch, ms)`; CLI
`write delay --channel N --ms F`.

**Master volume** — the previously-uncataloged **CMD `0x08` sub `0x0c`**:

**How it was found.** Probing the live device to guess this write was ruled
out after the 2026-07-04 misattribution below — instead we built a Linux
`/dev/uhid` virtual-amplifier shim (`scripts/uhid_shim.py`,
docs/LINUX_UHID_SHIM_PLAN.md) that impersonates the real device (VID/PID +
interface-4 report descriptor) and replays known request/response pairs
built from `usb1.pcapng`/`usb2.pcapng` (`scripts/build_replay_table.py` →
`docs/replay_table.json`). Running the vendor Windows app under `wine` and
dragging the Main fader against this fake device surfaced its actual write
packet directly — no guessing, no live-device risk.

**Wire format** (256-byte OUT payload):

```
[0:2]  e0 a2       magic
[2]    08          CMD — new, distinct from WRITE_DSP (0x0a)
[3]    00
[4:6]  b7 00       ADDR LE = channel_addr(0) = 0x00b7 (CH0/master)
[6]    0c          sub-byte (constant)
[7:11] <float32 LE> target volume in dB
[11]   <checksum>  (sum(payload[4:11]) - 0x20) & 0xFF — universal formula,
                    just at a new offset (right after the float, not [8]/[13])
[12:]  00 ...       zero padding; no [14:16] trailer like WRITE_DSP has
```

Verified byte-perfect across 17 live samples spanning −35.9…−0.98 dB
(6 from an exploratory drag, 11 from a live sweep), each independently
checksum-matched. A final blind check — asked the user to drag the fader to
"−20.0 dB" on the app's own UI without telling them the decode formula —
landed on **−20.02 dB**, confirming the float offset and sign convention.

Unlike `WRITE_DSP` (which stages a value and needs a `CMD 0x05` commit
trigger), **no separate commit packet was observed** after any of the 17
master-volume writes — this command applies immediately.

CLI: `write master --db <value> --commit`. Builder:
`packet.build_write_master_volume(volume_db)`.

Positive dB values (0…+6, the top of the Main range) are untested live —
expected to work symmetrically given plain IEEE-754 float encoding, but
unconfirmed.

#### CH0 `WRITE_DSP` misattribution (retracted 2026-07-05, kept for history)

The 2026-07-04 claim that `WRITE_DSP sub 0x26` to CH0 writes the master
volume is **wrong**. Live re-testing 2026-07-05 showed:

```
OUT: e0 a2 0a 00 b7 00 26 00 40 9c 46 3c 0a 25 00 10   (WRITE_DSP CH0 "GAIN")
IN:  02 00 ee bb ...                                    (ack)
```

The write's actual effect: it **force-switches the input source to
high level** (keepalive [11]: `0x02` → `0x00`, confirmed on the panel),
which *looks* like a volume jump because high level's stored knob-vol is
max (see per-source volume above). The payload is ignored:

| Variant tested | Result |
|---|---|
| byte `0x3c`, `0x3f`, `0x19`, `0x01` (from opt) | source → high level, every time |
| byte `0x02` (= opt ID, from high level) | no effect |
| float `2.0` instead of `20000.0` | no effect |

The 2026-07-04 "byte 0x3c → −4.23 dB master write" was misattributed: the
write switched the source, and −4.23 dB was the user's rescue knob-turn.
The "staging semantics" and "byte→dB scale" conclusions from that run are
retracted with it.

**Do not send `CMD 0x0a` writes to `addr 0x00b7` (CH0)** — use `write
master` instead. `write gain --channel 0` still builds the packet for
research but must not be committed against a live device.

---

### HPF / LPF crossover — SOLVED 2026-07-06 (CMD 0x0a, sub 0x05 / 0x06)

High- and low-pass filters are written with `WRITE_DSP` (CMD `0x0a`), same
shape, distinguished by sub-byte: **HPF = `0x05`, LPF = `0x06`**. One packet
carries frequency + slope + filter type. Live-captured on ch8:

```
HPF 22 Hz, 30 dB/oct, Bessel: e0 a2 0a 00 b7 08 05 00 00 b0 41 04 01 9a
LPF 85 Hz, 48 dB/oct, Bessel: e0 a2 0a 00 b7 08 06 00 00 aa 42 07 01 99
```

| Field | Bytes | Meaning |
|-------|-------|---------|
| sub | [6] | `0x05` HPF / `0x06` LPF |
| freq | [7:11] | float32 cutoff Hz |
| slope | [11] | `dB/oct = (code+1)*6`; `0x00`=6 … `0x07`=48 (8-value sweep verified) |
| type | [12] | `0x00`=Linkwitz-Riley, `0x01`=Bessel, `0x02`=Butterworth |
| csum | [13] | `(sum(pkt[4:13]) - 0x20) & 0xFF` |

`[14:16]` = `00 00` (the current app sends no trailer; an older pcap had
`00 10`, ignored by the device). **No commit** — applies immediately.

The slope encoding **corrects** the earlier guess (`0x03` was mislabelled
12 dB — it's 24 dB; dsp_m2.dat's "unknown `0x01`" is just 12 dB). The old
`TYPE_HPF=0x00` was actually the Linkwitz-Riley type code.

Builders: `packet.build_hpf(ch, freq, slope_db, filter_type)` /
`build_lpf(...)` (shared `build_crossover`); slope via
`constants.slope_db_to_byte`, type via `constants.filter_type_code`.
CLI: `write hpf` / `write lpf --channel N --freq Hz --slope-db D --type T`.

### EQ band (gain + freq + Q) — SOLVED 2026-07-06 (CMD 0x0a, sub = band slot)

The 31-band parametric EQ is written with `WRITE_DSP` (CMD `0x0a`). **One
packet sets a whole band atomically — center frequency, gain, and Q** — and
the **sub-byte at [6] selects which band**: `sub = 0x08 + (band-1)`, so band
1..31 → sub `0x08`..`0x26`. Live-captured:

```
ch1 band 18 (1 kHz) +6.0 dB:    e0 a2 0a 00 b7 01 19 00 00 7a 44 b4 0a 2d
ch1 band  8 (100 Hz) −5.0 dB:   e0 a2 0a 00 b7 01 0f 00 00 c8 42 46 0a 01
ch3 band 15 → 520 Hz, Q 2.9:    e0 a2 0a 00 b7 03 16 ec ff 01 44 78 1d 75
```

| Field | Bytes | Meaning |
|-------|-------|---------|
| CMD | `0a` | WRITE_DSP |
| ADDR | `b7 NN` | `channel_addr(ch)` |
| sub | `08+band-1` | band slot (`0x19`=band 18, `0x0f`=band 8, `0x16`=band 15) |
| freq | [7:11] | float32 center Hz — settable (500 → 520 verified) |
| gain | [11] | `db_to_byte(dB)` = `round(dB×10)+0x78` |
| Q | [12] | `q_to_byte(Q)` = `round(Q×10)` (`0x0a`=Q 1.0 default, `0x1d`=Q 2.9) |
| csum | [13] | `(sum(pkt[4:13]) - 0x20) & 0xFF` |

No `[14:16]` trailer (HPF's `00 10`), **no commit** — applies immediately.
All three parameters live-verified (gain on 2 bands, freq 500→520, Q 1.0→2.9).

Because the write is atomic, changing one parameter against the live device
means re-sending the band's current freq/gain/Q (read them from the channel
block, `parse_eq_block`). This also explains the old `sub 0x26` "GAIN" from
pcaps — that was EQ **band 31** (20 kHz), not a channel gain.

CLI: `write eq --channel N --band B [--db F] [--freq Hz] [--q Q]`. Builder:
`packet.build_eq_band(ch, band, gain_db=0, freq_hz=None, q=1.0)`; band→sub via
`constants.eq_band_sub(band)`; Q via `eq.q_to_byte` / `eq.byte_to_q`.

---

## Still Unknown

See `FINDINGS_MANUAL_GAP.md` for the full manual-vs-known gap and priority
capture plan. High-level outstanding items:

- LPF write command (expected: addr=0xNNb7, sub=?, TYPE_BYTE=?)
- EQ band gain/Q write addresses and TYPE_BYTE values
- MUTE, SOLO, phase invert, bridge commands
- Delay (time alignment) commands
- Preset save/load (M1..M6) commands — app has 16 scene slots, device manual says 6
- Routing matrix write commands
- Speaker-type write (candidate: application-level type enum 0x1a, count=6, payload 0x01..0x06 for HF/MF/LF/MHF/MLF/FF — see EXE static analysis)
- Exact meaning of cmd 0x08 (sub=0x0206 vs 0x8206 — two variants, both carry a bit-doubling data pattern)
- cmd 0x1c is **partly solved**: sub=0x28 is the CH7+CH8 bridge write (see *Bridge CH7+CH8*). sub=0x21 is a constant companion/UI-sync packet (also seen at enumeration, previously guessed to be "handshake") — its full purpose and whether the device requires it is still open
- Master volume write is solved (CMD 0x08 sub 0x0c, direct float32 dB — see *Master volume write*); positive dB range (0…+6) untested live. Note: CMD 0x04 SUB 0xa515 with a float in the data slot was tested live and is **ignored** by the device (keepalive data is inert)
- Routing matrix byte layout (32 bytes, signed int8 per output, but exact input/output mapping unclear)
- Q byte encoding (0x0a default; first EQ band uses different value e.g. 0x2b, 0x15)

### Confirmed response status codes (from `scripts/pair_pcap_requests_responses.py`)

| Status (LE, bytes 0..1 of IN payload) | `dlen` | Returned for |
|---------------------------------------|--------|--------------|
| `0f 00` (0x000f) | 11 B  | keepalive (CMD 0x04 SUB 0xa515) — payload echoes knob-vol float32 |
| `2f 00` (0x002f) | 43 B  | handshake init (CMD 0x04 SUB 0x9909) — short firmware string |
| `6a 00` (0x006a) | 102 B | firmware query (CMD 0x04 SUB 0x80f0) |
| `8d 00` (0x008d) | 137 B | master-channel read (CMD 0x05 SUB 0x0004) |
| `f6 00` (0x00f6) | 242 B | per-channel read (CMD 0x05 SUB 0xNN04) |

### CMD 0x05 sub 0x0101 / 0x0001 — RECLASSIFIED as per-channel mute (2026-07-06)

**Superseded.** These were previously believed to be a "DSP commit trigger"
in two flavors. Live capture 2026-07-06 (uhid shim, toggling the app's
per-channel mute buttons) showed they are **per-channel mute/unmute**:
`0x0101` = mute (byte[7]=0x01), `0x0001` = unmute (byte[7]=0x00), addr
`0xNNb7` selects the channel. See *Mute write* above.

This explains the old puzzle — usb2 sending `0x0001` on channels that had
**not** been written was the app unmuting them, unrelated to any DSP write.
It also means **WRITE_DSP (HPF/gain) may not need a separate commit at all**
(master volume, CMD 0x08, applies immediately with no commit). `build_dsp_commit`
still emits `sub 0x0001`, which is now known to be an *unmute* of that channel;
the HPF/gain write path should be re-examined against a live device to confirm
whether any commit is required — treat the current commit step as suspect.

### Full unique command catalog from captures

See `FINDINGS_MANUAL_GAP.md` → "Pcap findings" for the table of all 55 unique
(CMD, ADDR, SUB) signatures seen across `usb1.pcapng` + `usb2.pcapng`.
