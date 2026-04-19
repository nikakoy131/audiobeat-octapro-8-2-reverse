# Audiobeat OctaPro 8.2 Protocol Reverse Engineering

This repository documents the ongoing efforts to reverse engineer the USB HID communication protocol for the **Audiobeat OctaPro 8.2** (and related SP601) Car DSP Amplifier.

## 🛠 Hardware Overview

* **Device**: Audiobeat OctaPro 8.2 / SP601 (OEM: Guangzhou Nisson / Sennuopu HIFI-X12)
* **DSP Chip**: Analog Devices **ADAU1452**
* **MCU**: BMP885B
* **USB Details**:
    * **VID**: `0x8888`
    * **PID**: `0x1234`
    * **Speed**: USB Full Speed (12 Mb/s)
* **Audio Channels**: 10 Total (8 amplified + 2 line outputs)

## 📡 Protocol Summary

The device uses **USB HID CONTROL** transfers to allow real-time parameter manipulation.

### Key Command Types
| CMD | Name | Description |
|:---:|:---|:---|
| `0x04` | `WRITE_PARAM` | Write to specific device registers (e.g., firmware, keepalive). |
| `0x05` | `READ_BLOCK` | Read the full parameter state of a specific channel. |
| `0x0a` | `WRITE_DSP` | Real-time write of DSP RAM parameters (using `float32`). |

### Packet Structure (OUT)
A standard 256-byte payload consists of:
`[Magic: 0xe0, 0xa2] [CMD] [0x00] [ADDR: uint16 LE] [REG/SUB: uint16 LE] [CSUM] [DATA...]`

## 📂 Documentation

* **`PROTOCOL.md`**: Comprehensive breakdown of the USB transport, packet structures, checksum formulas, and known command implementations.
* **`CONTEXT_USER.md`**: Documentation of known device functionalities (EQ, Filters, Routing) and the investigative roadmap.

## 🚀 Project Roadmap

- [x] Recover USB HID Handshake sequence.
- [x] Implement Channel Parameter Readback (`CMD 0x05`).
- [x] Implement HPF (High-Pass Filter) frequency/slope control.
- [x] Implement Channel Gain adjustment.
- [ ] Implement LPF (Low-Pass Filter) frequency control.
- [ ] Implement EQ Band (Gain/Q) manipulation.
- [ ] Implement Routing Matrix control.
- [ ] Implement Preset Loading/Saving (`.dat` format).

## 🛠 Tools Used
* **Wireshark**: USB packet capture and analysis.
* **Python (`hidapi`, `struct`)**: Protocol implementation and testing.
