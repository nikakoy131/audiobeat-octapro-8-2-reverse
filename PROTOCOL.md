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

```
e0 a2 0a 00  ADDR_LO ADDR_HI  SUB  DATA[5]  CSUM  ?? ?? ??
```

DATA[5] = float32 LE (4 bytes) + 1 extra byte.

### Known parameter addresses

| ADDR   | SUB  | Parameter | Data encoding |
|--------|------|-----------|---------------|
| 0x07b7 | 0x05 | HPF frequency (CH7+CH8 sub) | float32 Hz + slope byte |
| 0x09b7 | 0x26 | Channel GAIN | float32 ref + gain byte |

**Address spacing:** 0x09b7 - 0x07b7 = 0x200 = 512. This is the ADAU1452 parameter RAM stride between channel blocks.

### HPF frequency example (sub channels 7+8, 36 dB/oct):

```python
struct.pack('<f', 20.1) + bytes([0x05])  # slope code 0x05 = 36dB/oct?
```

```
e0 a2 0a 00 b7 07 05 cd cc a0 41 05 00 22 00 10  (HPF=20.1 Hz)
e0 a2 0a 00 b7 07 05 9a 99 a1 41 05 00 bd 00 10  (HPF=20.2 Hz)
e0 a2 0a 00 b7 07 05 04 00 b0 41 05 00 9d 00 10  (HPF=22.0 Hz)
```

### Channel GAIN example:

```
e0 a2 0a 00 b7 09 26 00 40 9c 46 79 0a 6b 00 10  (gain=+0.1 dB)
e0 a2 0a 00 b7 09 26 00 40 9c 46 dc 0a ce 00 10  (gain=+10.0 dB)
```

Gain byte encoding: `gain_dB = (byte - 0x78) / 10.0`

| byte | dB |
|------|----|
| 0x80 | -inf (mute) |
| 0x78 | 0.0 |
| 0x6e | -1.0 |
| 0x5a | -3.0 |
| 0x88 | +1.6 |
| 0xdc | +10.0 |

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

## .dat Preset File Format (US002)

```
Header: "US002" (5 bytes ASCII)
Body:   10 × 290 bytes  (one block per channel)
        = 52 bytes channel header
        + 238 bytes EQ data (16 bands)
```

### Channel Header (52 bytes)

```
[0:32]   Routing matrix — 8 × 4 bytes
         Each byte = gain:  signed_value / 10.0 dB
           0x80 = -inf (mute)     0x78 = 0.0 dB
           0xe4 = -2.8 dB         0x64 = +10.0 dB
           0xb2 = -7.8 dB

[32:36]  float32  HPF frequency (Hz)
[36:40]  float32  ? (Q or slope)
[40:44]  ?
[44:48]  float32  LPF frequency (Hz)   20600.0 = bypass
[48:52]  flags    03 01 00 06 = fullrange
                  03 00 00 06 = limited
                  03 00 00 03 = sub
```

### EQ Block (238 bytes) — 16 bands

Each band ~14 bytes:
```
[0:4]   float32  center frequency (Hz)
[4]     gain byte: (byte - 0x78) / 10.0 dB
[5]     0x78  separator
[6]     Q byte (TBD)
[7]     0x0a  separator
[8:14]  tail / overlap
```

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

## Still Unknown

- Exact parameter RAM layout for all 10 channels (need more captures with different params)
- LPF write command address (expected near 0x07b7/0x09b7)
- EQ band gain/Q write addresses
- MUTE, SOLO, phase invert, bridge commands
- Delay (time alignment) commands
- Preset save (M1..Mx) commands
- Routing matrix write commands
- Meaning of cmd 0x08 and 0x1c in handshake
- What extra bytes [14:16] encode (seen as `00 10` always in 0x0a)
