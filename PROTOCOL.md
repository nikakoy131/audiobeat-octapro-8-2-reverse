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
| OUT (host→device) | 0x21 | 0x09 SET_REPORT | 0x0002 | 0x0004 | 256 |
| IN  (device→host) | 0xa1 | 0x01 GET_REPORT | 0x0002 | 0x0004 | 256 |

SETUP (8 bytes) + 256-byte payload = 264 bytes per transaction.

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

| SUB  | TYPE_BYTE | Parameter    | PARAM_BYTE meaning  | float32 meaning |
|------|-----------|--------------|---------------------|-----------------|
| 0x05 | 0x00      | HPF frequency | slope code          | frequency Hz    |
| 0x26 | 0x0a      | Channel GAIN  | gain byte           | 20000.0 (ref)   |

Slope codes (byte after float32):
- `0x05` = 36 dB/oct (confirmed in CH7 captures)
- `0x03` = 12 dB/oct (seen in CH1, CH5 readback)

### HPF frequency example (CH7, 36 dB/oct):

```
e0 a2 0a 00 b7 07 05 cd cc a0 41 05 00 22 00 10  (HPF=20.1 Hz)
e0 a2 0a 00 b7 07 05 9a 99 a1 41 05 00 bd 00 10  (HPF=20.2 Hz)
e0 a2 0a 00 b7 07 05 04 00 b0 41 05 00 9d 00 10  (HPF=22.0 Hz)
```

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
1. Check status:
   OUT: e0 a2 05 00 b7 00 03 11 ab 00...
   IN:  02 00 ee bb 00...   (0xbbee = not connected)

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

## macOS Client (hidapi)

```python
import hid, struct

VID, PID = 0x8888, 0x1234

def open_device():
    dev = hid.device()
    dev.open(VID, PID)
    return dev

def send_ctrl(dev, payload: bytes):
    assert len(payload) == 256
    dev.write(bytes([0x00]) + payload)   # report ID 0

def recv_ctrl(dev) -> bytes:
    return bytes(dev.read(256, timeout_ms=500))

def checksum_0a(pkt: bytearray) -> int:
    """pkt must have addr[4:6], sub[6], data[7:12] filled"""
    return (sum(pkt[4:13]) - 0x20) & 0xFF

def make_cmd(cmd, addr, reg, csum=0xab):
    pkt = bytearray(256)
    pkt[0]=0xe0; pkt[1]=0xa2; pkt[2]=cmd; pkt[3]=0x00
    struct.pack_into('<H', pkt, 4, addr)
    struct.pack_into('<H', pkt, 6, reg)
    pkt[8] = csum
    return pkt

def read_channel(dev, ch: int) -> bytes:
    pkt = make_cmd(0x05, 0x00b0, (0x04 << 8) | ch, csum=0x94+ch)
    send_ctrl(dev, bytes(pkt))
    return recv_ctrl(dev)

def write_hpf(dev, addr: int, freq_hz: float, slope_code: int = 0x05):
    """Write HPF frequency. slope_code 0x05 observed for 36dB/oct."""
    pkt = bytearray(256)
    pkt[0]=0xe0; pkt[1]=0xa2; pkt[2]=0x0a; pkt[3]=0x00
    struct.pack_into('<H', pkt, 4, addr)
    pkt[6] = 0x05   # sub
    struct.pack_into('<f', pkt, 7, freq_hz)
    pkt[11] = slope_code
    pkt[12] = 0x00
    pkt[13] = checksum_0a(pkt)
    send_ctrl(dev, bytes(pkt))
    return recv_ctrl(dev)

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
    pkt[13] = checksum_0a(pkt)
    send_ctrl(dev, bytes(pkt))
    return recv_ctrl(dev)

def get_firmware(dev) -> str:
    pkt = make_cmd(0x04, 0x00b0, 0x80f0)
    send_ctrl(dev, bytes(pkt))
    r = recv_ctrl(dev)
    return r[9:50].decode('ascii', errors='replace').rstrip('\x00')

def keepalive(dev):
    pkt = make_cmd(0x04, 0x00b0, 0xa515, csum=0x94)
    send_ctrl(dev, bytes(pkt))

if __name__ == '__main__':
    dev = open_device()
    print(get_firmware(dev))
    for ch in range(11):
        d = read_channel(dev, ch)
        print(f'CH{ch}: {d[:16].hex()}')
    dev.close()
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
- Exact meaning of cmd 0x1c (addr=0x00b7, sub=0x0121 — handshake; payload is the same bit-doubling pattern)
- Main volume write — keepalive **response** already echoes its float32 value; write command probably reuses CMD 0x04 SUB 0xa515 with a float in the data slot
- Routing matrix byte layout (32 bytes, signed int8 per output, but exact input/output mapping unclear)
- Q byte encoding (0x0a default; first EQ band uses different value e.g. 0x2b, 0x15)

### Confirmed response status codes (from `scripts/pair_pcap_requests_responses.py`)

| Status (LE, bytes 0..1 of IN payload) | `dlen` | Returned for |
|---------------------------------------|--------|--------------|
| `0f 00` (0x000f) | 11 B  | keepalive (CMD 0x04 SUB 0xa515) — payload echoes main-volume float32 |
| `2f 00` (0x002f) | 43 B  | handshake init (CMD 0x04 SUB 0x9909) — short firmware string |
| `6a 00` (0x006a) | 102 B | firmware query (CMD 0x04 SUB 0x80f0) |
| `8d 00` (0x008d) | 137 B | master-channel read (CMD 0x05 SUB 0x0004) |
| `f6 00` (0x00f6) | 242 B | per-channel read (CMD 0x05 SUB 0xNN04) |

### CMD 0x05 commit trigger — two variants observed

After a WRITE_DSP batch, the UI sends `CMD 0x05 addr=0xNNb7` with SUB in two
forms: `0x0001` (REG_HI=0x00) and `0x0101` (REG_HI=0x01). Both clear the DSP
buffer, but why two flavors exist is unclear — usb2 sent `0x0001` on channels
that had **not** been written in the same capture, suggesting the address field
tracks the currently selected UI channel rather than the write target.

### Full unique command catalog from captures

See `FINDINGS_MANUAL_GAP.md` → "Pcap findings" for the table of all 55 unique
(CMD, ADDR, SUB) signatures seen across `usb1.pcapng` + `usb2.pcapng`.
