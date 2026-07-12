# Bluetooth LE control — reverse-engineering findings

Status: **SOLVED & LIVE-VERIFIED** (branch `feat/ble-discovery`, 2026-07-12). The
BLE control link carries the **identical `e0 a2 …` protocol** we already
reverse-engineered over USB — same commands, same checksum, same float encoding.
Only the *transport* differs (a vendor GATT serial bridge instead of USB HID).
Recovered from the WeChat mini-program's own JavaScript (see "How this was
obtained") and confirmed against the amp on 2026-07-12, **both directions**:

- **Read** — session-open + `READ_BLOCK` over AE10 returned a full channel block on
  AE02 that decodes with the unchanged USB `parse_channel_block` (CH1: gain −7.0 dB,
  delay 4.406 ms, HPF 4000 Hz, LPF 20600 Hz, speaker 0x06, all 31 EQ bands intact).
- **Write** — a self-reversing mute test (`scripts/ble_mute_test.py`): `build_mute`
  CH1 then unmute, each taking effect immediately; the read-back block round-tripped
  exactly. Bonus: the diff located the **per-channel mute flag at channel-block byte
  29** (0 = unmuted, 1 = muted; byte 239 is a trailing block checksum that tracks it).

## TL;DR — how to talk to the amp over BLE

1. Connect to the peripheral advertising **`AB OctaPro BLE`**.
2. Use vendor service **`0xAE00`**.
3. Enable notifications on **`0xAE02`** (responses arrive here).
4. **Write commands to `0xAE10`** as a normal **write-with-response**.
5. First write the **session-open** packet `e0 a2 05 00 b7 00 03 11 ab`
   (byte-identical to USB `build_session_open()`).
6. Then send DSP commands as the **same `e0 a2 …` packets as USB**, but as the
   **short packet only — NOT padded to 256 bytes**. The biggest command (a
   147-byte car-preset, CMD `0x90`) still fits in one write under the 185-byte MTU,
   so no fragmentation is needed for any command.
7. Read responses by concatenating `0xAE02` notifications until the framed length
   is reached (see "Response framing").

That's the whole thing. Every `octapro.protocol` packet builder works unchanged;
`BleTransport` (`src/octapro/transport/ble.py`) is just "write bytes to AE10,
read notifications from AE02" — see "`BleTransport` — shipped" below.

## Why the earlier black-box probes got silence

The blind probing in this branch's first pass failed for three concrete reasons,
all now explained by the applet source:

| What I did | What the applet does |
|---|---|
| wrote to **AE01/AE03** (write-without-response) | writes to **AE10** (write-with-response) |
| **padded to 256 bytes** (USB HID report size) | sends the **short packet**, unpadded |
| never sent the short packet to AE10 | AE10 + short + with-response is the combo |

The HID-over-GATT `0x1812` service (OS-reserved on macOS *and* Android — see below)
was a red herring; the applet never used it. Control was always the `0xAE00`
serial bridge.

## The framing is byte-identical to USB

The applet builds each command as a hex string and writes its raw bytes. Examples
straight from `app-service.js`, matched to our USB builders:

| Function | Applet hex (built) | USB equivalent |
|---|---|---|
| read channel | `e0a20500b00004` + `buwei(ch)` + crc | `build_read_channel` |
| session open | `e0a20500b7000311ab` | `build_session_open` |
| mute | `e0a20500b7` + ch + `01` + state + crc | `build_mute` |
| phase | `e0a20500b7` + ch + `02` + state + crc | `build_phase` |
| speaker type | `e0a20500b7` + ch + `30` + code + crc | `build_speaker_type` |
| channel gain | `e0a20800b7` + ch + `03` + f32 + crc | `build_channel_gain` |
| delay | `e0a20800b7` + ch + `04` + f32 + crc | `build_channel_delay` |
| HPF/LPF | `e0a20a00b7` + … + crc | `build_hpf` / `build_lpf` |
| EQ band | `e0a20a00b7` + … + crc | `build_eq_band` |
| EQ pass | `e0a20500b7` + ch + `07` + state + crc | `build_eq_pass` |
| EQ reset all | `e0a20500b70007ff9d` | `build_eq_reset(0xff)` |
| bridge | `e0a21c00b70028` + … + crc | `build_bridge` |

### Checksum (`getLowcrc`) — same formula as USB

```js
getLowcrc(t){ for(var e=0,a=0;a<t.length;a+=2) e+=parseInt("0x"+t.substr(a,2)); return (e%256) as 2 hex }
```

It sums the bytes of a reconstructed string that **begins with `e0`** followed by
the checksummed region. Because `0xe0 = 256 − 0x20`, `(0xe0 + Σbytes) mod 256 ≡
(Σbytes − 0x20) mod 256` — exactly the USB checksum `(sum(pkt[4:13]) − 0x20) &
0xFF`. Worked example, read CH1: `getLowcrc("e0b00401")` = (0xe0+0xb0+0x04+0x01)
mod 256 = 0x95 → full packet `e0 a2 05 00 b0 00 04 01 95`, identical to USB.

### Encodings

- `buwei(n)` → one byte as 2 hex digits (channel numbers are 1-based, as in USB).
- `float2str(x)` → little-endian float32 hex (`struct.pack("<f")`), used for gain,
  delay, HPF/LPF freq — same as USB.
- `str2Float` is the inverse, used when decoding responses.

## Response framing (for reads)

Notifications on `0xAE02` are concatenated until complete. From the applet's
`onBLECharacteristicValueChange`:

- **Expected length**: for an `e0 a2` response, total bytes =
  `u16_LE(bytes[2:4]) + 4` (the length field sits at bytes `[2:4]`, little-endian).
  For `01 fe` media responses the length field is at bytes `[6:8]`.
- **Response header is 2 bytes shorter than USB** (live-confirmed): the BLE frame is
  `[0:2]=e0a2  [2:4]=datalen LE  [4:6]=addr  [6:]=channel block` — no leading status
  word. So the channel block starts at byte **6** (USB has it at 8). A CH1 read gave
  `datalen=242` → 246 bytes total, and `parse_channel_block(resp[6:])` decoded it
  correctly with no other changes.
- **9-byte notifications are status/ACK frames** and are not appended to the data
  buffer.
- **Discarded ACK/refusal frames**: `eebb`, `ee55` (the same refusal ACK seen over
  USB before session-open), `be701d00`, `be7022…`.
- **Version banner**: responses beginning `e0a22a00` / `e0a22b00` carry the ASCII
  firmware string (e.g. `A888-A-DP603…` / `A161-A-DP603…`).

Note the response length field is at `[2:4]`, whereas the USB `InPacket` reads
`data_len` at `[4:6]`; the BLE response header packs slightly differently. Confirm
the exact channel-block offsets against a live read before relying on the USB
`parse_channel_block` for BLE responses (the request side is already proven).

## Bonus finds in the applet

- **CMD `0x90` — per-car-model EQ presets.** The app ships a table of factory
  tunings (`E0A29000B70005…`, ~147 bytes each) for specific cars — Audi A1/A4/Q3/Q5/
  Q7, Mercedes C/E/S/GLA, BMW, Porsche Cayenne/911, Buick, etc. CMD `0x90` @ addr
  `0x00b7` sub `0x0005`. Not seen in the USB captures. A future decode of this
  payload would give us the built-in car presets for free.
- **`01 fe …` media/U-disk namespace.** A separate 16-byte command family for the
  USB-disk music player (play `…430b…`, pause `…430c…`, track/status polling),
  sent to the same AE10 characteristic. Distinct from the `e0 a2` DSP namespace.
- **CMD `0x2a`/`0x2b`** responses = firmware version banner (ASCII).

## The HID service is OS-reserved everywhere (0x1812 was a red herring)

The peripheral advertises HID-over-GATT (`0x1812`) but no OS exposes it to apps:
macOS CoreBluetooth filters it, and Android (`nRF Connect`, native) shows only
Generic Access `0x1800` + the `0xAE00` service — Android reserves HOGP for the
system `BluetoothHidHost`. Since the WeChat applet runs on Android, it necessarily
uses `0xAE00`, which is exactly what the source confirms. The advertised HID
service is a leftover default profile of the BLE module.

Android GATT as seen in nRF Connect (2026-07-12):

```
Generic Access            0x1800   Device Name (0x2A00) = "AB OctaPro BLE"
Unknown Service           0xAE00   (primary)
  0xAE01  WRITE NO RESPONSE
  0xAE02  NOTIFY   (+CCCD)          <- responses (subscribe here)
  0xAE03  WRITE NO RESPONSE
  0xAE04  NOTIFY   (+CCCD)
  0xAE05  INDICATE (+CCCD)
  0xAE10  READ, WRITE               <- commands (write here, with response)
```

Advertisement: manufacturer data `5a 48 57 47` = ASCII `"ZHWG"`; connected MTU 185.
On macOS the peripheral id is a per-host UUID (e.g.
`E61D6AD7-98AB-D5C0-40DD-4C43D4E70AB2`), not a MAC — resolve by name.

## How this was obtained

The device's only controller is a **WeChat mini-program** (appid
`wxc3f96b3bc4135c0c`, OEM Guangzhou Nisson / Sennuopu). It cannot be pulled off
Android without root (WeChat private storage), so it was extracted from **desktop
WeChat on macOS**: opening the applet caches its package to
`~/Library/Containers/com.tencent.xinWeChat/Data/Documents/app_data/radium/users/<uid>/applet/packages/wxc3f96b3bc4135c0c/2/__APP__.wxapkg`.
The `.wxapkg` is encrypted (`V1MMWX` header); decrypted with the standard scheme
(`key = PBKDF2-HMAC-SHA1(appid, "saltiest", 1000, 32)`, `iv = "the iv: 16 bytes"`,
AES-256-CBC over the first 1024 bytes, remainder XOR `ord(appid[-2])`), then
unpacked — the whole protocol lives in `app-service.js`. (Extractor kept in the
scratchpad, not committed; the applet is third-party code.)

## Live verification log (2026-07-12, at the car)

Beyond the initial read/mute proof above, a longer live session further
confirmed both the master-volume link and per-channel mute across multiple
channels — all over BLE, all using the unchanged `octapro.protocol` builders.

### Master volume verification

Re-tested the RC-knob/CH0-register identity claim (PROTOCOL.md "Volume
terminology") directly, rather than relying on the earlier USB-side inference:

- **Watch** (`scripts/ble_watch_master_volume.py`): polled CH0 `[9:13]` every
  1.5s for 30s while the physical RC knob was turned. The decoded value moved
  in real time with the knob: `6.00 → 1.12 → −3.33 → −4.23 → −8.20 dB`. Direct
  live observation, not a static cross-check.
- **Write + panel confirm** (`scripts/ble_set_master_volume.py`): wrote CH0 to
  knob step 25 (target −3.33 dB, an exact anchor in
  `octapro.protocol.knob_vol.KNOB_CALIBRATION`) via `build_write_master_volume`
  (CMD `0x08` sub `0x0c`). Readback matched the target exactly
  (`e0 a2 08 00 b7 00 0c b8 1e 55 c0 8e` → −3.33 dB), and the user confirmed the
  **RC panel display itself updated to show 25** — the write doesn't just move
  the internal register, it drives the physical display. Repeated for knob step
  35 (target +6.00 dB, the top-of-range anchor): readback matched exactly.
- Conclusion: the link is **bidirectional** — knob→register (watched) and
  register→panel (written and confirmed) — closing the loop the original
  2026-07-05 USB-side finding left one-directional.

### Per-channel mute, multiple channels

`scripts/ble_mute_test.py`, each a self-reversing mute→hold→unmute with a live
audible check and a block-diff readback:

| Channel | Result | Note |
|---|---|---|
| CH1 | byte[29] 0→1→0, round-trip exact | first proof, see top of doc |
| CH4 | byte[29] 0→1→0, round-trip exact | |
| CH6 | byte[29] 0→1→0, round-trip exact, **5s hold** | user confirmed audible drop-out + return |
| CH3 | byte[29] 0→1→0, round-trip exact, 5s hold | user confirmed audible; **CH3 = rear speaker** |
| CH4 (again) | byte[29] 0→1→0, round-trip exact, 5s hold | user confirmed audible; **CH4 = rear speaker** |

Every test restored the exact original 240-byte block afterward (verified by
byte-for-byte diff, not just re-reading the mute flag).

### Full device snapshot

`scripts/ble_snapshot.py` — read-only dump of master + all 10 channels (gain,
delay, HPF/LPF, speaker type, mute, EQ deviations, routing) to
`research/device-snapshots/<timestamp>/{snapshot.json,summary.md}` (git-ignored
— personal install data, not RE data). Used to guess the physical layout from
crossover points + the routing L/R pattern; CH3/CH4 guessed as
midbass/rear-adjacent and **confirmed by the user as the rear speakers** via the
mute tests above. See the snapshot's `summary.md` for the full per-channel table
and the reasoning notes.

## `BleTransport` — shipped

- ~~One live confirmation~~ — **done** (2026-07-12, `scripts/ble_probe.py`): CH1
  read decoded to sane values (see status line).
- ~~Implement `BleTransport`~~ — **done**, same branch:
  `src/octapro/transport/ble.py` (plus the pure reassembly/normalization logic
  in `src/octapro/transport/ble_frame.py`, unit-tested offline in
  `tests/test_ble_frame.py`). It writes short packets to `AE10` (with
  response), reassembles `AE02` notifications per the formula above, and
  re-packs the result into the USB `InPacket` byte layout (prepending a
  synthetic 2-byte status word) so every existing protocol parser decodes it
  unchanged. `bleak` runs on its own asyncio event-loop thread so `transact()`
  keeps the same synchronous contract as `HidTransport`. Every CLI command now
  runs over either transport — `octaproctl ble scan` / `ble connect` discover
  and remember a device, `--transport ble` overrides per-invocation. See
  README.md "Transports". `scripts/ble_probe.py` / `scripts/ble_mute_test.py`
  remain the original research scripts this was distilled from.
- Note: the two live master-volume verification scripts referenced above
  (`ble_watch_master_volume.py`, `ble_set_master_volume.py`) were one-shot and
  not committed — their findings are recorded here and in PROTOCOL.md; use
  `octaproctl read master --transport ble` / `write master --transport ble` to
  reproduce them with the shipped CLI instead.
- Optionally decode the CMD `0x90` car-preset table and the `01 fe` media namespace.
