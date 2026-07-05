# Plan: Linux `uhid` virtual-amplifier shim (capture the Main-volume write)

Goal: get the vendor Windows app (`Audiobeat OctaPro 8.2 V1.0.7_250801.exe`,
under wine on Linux) to connect to a **fake** amplifier we control, so that
dragging the PC software's Main-volume fader sends its write packet to us
instead of a real device — no hardware required.

## Why this approach (context for a fresh session)

- The real device's DSP interface (interface 4) has **no endpoints** — all
  traffic is HID control transfers (`SET_REPORT`/`GET_REPORT`). This is why
  macOS never binds it as a HID device (see PROTOCOL.md "Transport").
- On **macOS**, faking a virtual HID device is blocked: `IOHIDUserDeviceCreate`
  requires the `com.apple.developer.hid.virtual.device` entitlement, enforced
  by the kernel even as root. Confirmed empirically 2026-07-05 (see session
  history / FINDINGS_EXE.md). A signed DriverKit extension would be needed —
  out of scope.
- On **Linux**, `/dev/uhid` provides the same capability in userspace with no
  entitlement wall — just root or a udev rule granting access to `/dev/uhid`.
  This is the reason to move the shim work to a Linux box.
- We already tried the real device's `WRITE_DSP` packet to CH0 as a guess at
  "master volume write" — it turned out to force-switch the input source
  instead (see PROTOCOL.md "Master volume write — UNSOLVED"). We are not
  guessing again; we want the app's actual packet, captured directly.

## What's already been captured (don't redo this)

All of this lives in the repo, on branch `fix/pyusb-transport-session-open`:

- **`docs/iface4_report_descriptor.bin`** (35 bytes) — the exact HID report
  descriptor of interface 4, dumped live via `GET_DESCRIPTOR`. Decoded in
  `docs/HID_DESCRIPTORS.md`: vendor-defined HID (Usage Page `0xFF00`, Usage
  `0x01`), **no report IDs**, 256-byte Input report, 256-byte Output report,
  1-byte Feature report.
- **`docs/iface4_config_descriptor.bin`** (250 bytes) — full composite config
  descriptor (all 5 interfaces), in case the shim needs to expose more than
  just interface 4 to satisfy the app's enumeration.
- **`usb1.pcapng`** — real device's full handshake + channel-readback
  sequence. This is the source of truth for what the shim should reply with.
- **`usb2.pcapng`** — live EQ/filter parameter change traffic.
- `scripts/pair_pcap_requests_responses.py` — already pairs OUT requests
  with IN responses from a pcap; reuse its parsing logic to build a
  request→response lookup table for the shim's replay responder.

## Shim design

1. **Create the virtual device** via `/dev/uhid`, feeding it:
   - VID `0x8888`, PID `0x1234`
   - The exact report descriptor from `docs/iface4_report_descriptor.bin`
   - A product string good enough for wine/the app to accept (exact string
     doesn't matter functionally, but keep it recognizable, e.g. "Car DSP AMP")

2. **Responder logic — replay, don't emulate the DSP:**
   - Build a lookup table from `usb1.pcapng`: key = OUT payload (or just
     `cmd, addr, sub`), value = the IN response that followed it live.
     `scripts/pair_pcap_requests_responses.py` already does most of this
     parsing — extend it to dump a `{request_hex: response_hex}` JSON table
     instead of just printing.
   - On every `UHID_OUTPUT` event (the app's `SET_REPORT`), look up the
     matching response and send it back via `UHID_INPUT2`/feature report
     as appropriate.
   - Must handle, at minimum: the session-open packet, the keepalive
     (`CMD 0x04 SUB 0xa515`), and READ_BLOCK for CH0 and CH1–10 (`CMD 0x05`).
     These are enough for the app to show "Connected" and populate its UI —
     which is the prerequisite for the Main fader to be interactive.
   - The **goal is not to fully emulate the DSP** — just to be convincing
     enough that the app connects and lets you drag the Main fader. Whatever
     packet it sends for that write is the answer we want; we don't need to
     respond to it correctly, just log it.

3. **Run the app under wine on Linux** and drag the Main fader.
   - Known risk (from prior web research, see FINDINGS_EXE.md): wine's HID
     enumeration via `setupapi`/registry is incomplete, and other users have
     hit apps that see the HID device but never "acknowledge" it. If the app
     stalls at connection despite the shim responding correctly, this is the
     most likely cause — don't sink hours re-debugging the shim's byte
     correctness before checking wine's HID enumeration completes at all.
   - `wine --debugmsg +hid,+setupapi` or similar wine debug channels are the
     first thing to check if connection stalls.

4. **Capture the result** — no pcap needed this time: the shim itself can
   log every `UHID_OUTPUT` payload with a timestamp. Drag the fader once,
   grep the log for a new/unmatched request (i.e. one not in the replay
   table, or one whose `cmd/addr/sub` doesn't match a known command), and
   that's the Main-volume write packet.

## Definition of done

- The exact OUT packet(s) sent when dragging the Main fader, in the same
  `cmd / addr / sub / payload` breakdown style as PROTOCOL.md's other
  commands.
- Decode it into `octapro/protocol/packet.py` as `build_write_master_volume`
  (or similar), following the pattern in CLAUDE.md → "Adding New Write
  Commands".
- Update PROTOCOL.md's "Master volume write — UNSOLVED" section with the
  real command, replacing the retraction with a confirmed write path.
- Add a CLI `write master --db <value> --commit` command, gated the same
  way as other writes (dry-run by default).

## Explicitly out of scope for this plan

- Fully correct DSP emulation (channel EQ, routing, etc.) — only enough
  fidelity to get the app connected and the Main fader interactive.
- macOS virtual-HID (confirmed blocked, see above) — this plan is Linux-only.
