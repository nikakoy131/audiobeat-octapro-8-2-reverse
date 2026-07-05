# USB Descriptors — Audiobeat OctaPro 8.2 (VID 0x8888 / PID 0x1234)

Read-only dump from the live device 2026-07-05 via standard `GET_DESCRIPTOR`
control requests (no device state changed). Raw bytes saved alongside this doc:

| File | Bytes | Contents |
|------|-------|----------|
| [`iface4_report_descriptor.bin`](iface4_report_descriptor.bin) | 35 | Interface 4 HID **report** descriptor |
| [`iface4_config_descriptor.bin`](iface4_config_descriptor.bin) | 250 | Full **configuration** descriptor (all interfaces) |

Why this matters: a virtual-amplifier shim (e.g. Linux `/dev/uhid`) must present
**exactly** this report descriptor and VID/PID so the vendor app enumerates the
fake device the same way it does the real one. See PROTOCOL.md and FINDINGS_EXE.md
for the "capture the Main-volume write" plan.

---

## Device

```
VID:PID   = 8888:1234
bcdUSB    = 0110  (USB 1.1, Full Speed)
class     = 00 / 00 / 00  (per-interface class — composite device)
```

## Configuration — composite, 5 interfaces

| Iface | Class | Subclass | Endpoints | Role |
|-------|-------|----------|-----------|------|
| 0 | 0x01 Audio | 0x01 AudioControl | 0 | Audio control |
| 1 | 0x01 Audio | 0x02 AudioStreaming | isoc OUT `0x05` | Audio out stream |
| 2 | 0x01 Audio | 0x02 AudioStreaming | isoc IN `0x84` | Audio in stream |
| 3 | 0x03 HID | 0x00 | interrupt IN `0x81` | Media-key remote — **the only HID interface macOS binds** |
| 4 | 0x03 HID | 0x00 | **none** | **DSP protocol** — no endpoints → macOS won't bind it; control-transfer only |

Full config descriptor (raw hex):

```
0902fa0005010080100904000000010100000a240100014f000201020c2402010101000203
0000000a2406020101010202000924030301030002000c24020401020002030000000a2406
0504010102020007240506010500092403070101000600090401000001020000090401010
1010200000724010101010100 0e2402010202100244ac0080bb00090505 09c800010000072
50101000000090402000001020000090402010101020000072401070101000e24020102021
00244ac0080bb00090584 09c8000100000725010100000009040300010300000009210102000
1222f0007058103400001090404000003000000092101020001222300
```
(line-wrapped for readability; canonical bytes are in the `.bin`)

---

## Interface 4 — HID Report Descriptor (35 bytes)

Raw: `0600ff0901a101150026ff007508960001090181029600010901910295010901b102c0`

Decoded:

| Bytes | Item | Meaning |
|-------|------|---------|
| `06 00 ff` | Usage Page | Vendor-Defined `0xFF00` |
| `09 01` | Usage | `0x01` |
| `a1 01` | Collection | Application |
| `15 00` | Logical Minimum | 0 |
| `26 ff 00` | Logical Maximum | 255 |
| `75 08` | Report Size | 8 bits |
| `96 00 01` | Report Count | **256** |
| `09 01` | Usage | `0x01` |
| `81 02` | **Input** | Data, Var, Abs → **256-byte Input report** (device→host, `GET_REPORT`) |
| `96 00 01` | Report Count | **256** |
| `09 01` | Usage | `0x01` |
| `91 02` | **Output** | Data, Var, Abs → **256-byte Output report** (host→device, `SET_REPORT`) |
| `95 01` | Report Count | 1 |
| `09 01` | Usage | `0x01` |
| `b1 02` | **Feature** | Data, Var, Abs → **1-byte Feature report** |
| `c0` | End Collection | |

### Takeaways for the shim

- **No report IDs** — reports are raw 256-byte buffers, matching our transport
  (OUT = `SET_REPORT` wValue `0x0200`, IN = `GET_REPORT` wValue `0x0100`).
- **256-byte Input and Output reports**, plus a **1-byte Feature report** — the
  vendor app also calls `HidD_SetFeature`/`HidD_GetFeature` (see FINDINGS_EXE.md),
  so a faithful shim must expose the feature report too, not just in/out.
- **Usage Page `0xFF00`, Usage `0x01`** — the app likely filters on these when
  enumerating; replicate them exactly.
