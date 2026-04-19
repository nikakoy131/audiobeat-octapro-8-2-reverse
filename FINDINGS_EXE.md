# FINDINGS_EXE.md — Static Analysis of Audiobeat OctaPro 8.2 V1.0.7_250801.exe

## File Info

| Property | Value |
|----------|-------|
| File | Audiobeat OctaPro 8.2 V1.0.7_250801.exe |
| Size | 22,785,536 bytes (22 MB) |
| Format | PE32, Intel 80386 |
| Compiler | GCC + MinGW (linker v2.24) |
| UI framework | Qt (statically linked, single binary) |
| Image Base | 0x00400000 |
| Entry point | 0x000014c0 |
| Sections | 12 (.text 14MB, .rdata 5MB, .qtmetad, .eh_fram, ...) |

---

## USB/HID Discovery

The app uses Windows `hid.dll` directly via import table. **Not** COM/serial.

### HID API imports (IAT addresses)

| Function | IAT VA | Thunk VA | Call sites |
|----------|--------|----------|------------|
| HidD_SetOutputReport | 0x02268d0c | 0x4b9410 | 2 |
| HidD_GetInputReport  | 0x02268cfc | 0x4b9418 | 2 |
| HidD_GetAttributes   | 0x02268cf4 | 0x4b9420 | 2 |
| HidD_GetHidGuid      | 0x02268cf8 | 0x4b9428 | 6 |
| HidD_GetPreparsedData| 0x02268d04 | 0x4b9430 | 2 |
| HidP_GetCaps         | 0x02268d10 | 0x4b9438 | 2 |
| HidD_FreePreparsedData| 0x02268cf0 | 0x4b9440 | 2 |
| HidD_GetPhysicalDescriptor | 0x02268d00 | 0x4b9448 | 1 |
| HidD_SetFeature      | 0x02268d08 | 0x4b9450 | 2 |

### Key IO call sites

| VA | Function | Role |
|----|----------|------|
| 0x408c34 | HidD_SetOutputReport | Main command send path |
| 0x44fd97 | HidD_SetOutputReport | Bulk/preset send path |
| 0x408fde | HidD_GetInputReport  | Main response read path |
| 0x44fde1 | HidD_GetInputReport  | Bulk/preset read path |
| 0x408863 | threadFuncSend entry | Send worker thread start |

### Device enumeration

Uses `SETUPAPI.dll`:
- `SetupDiGetClassDevsW` — enumerate HID class devices
- `SetupDiEnumDeviceInterfaces`
- `SetupDiGetDeviceInterfaceDetailW`
- `SetupDiDestroyDeviceInfoList`
- `CreateFileW` — open device handle
- `HidD_GetAttributes` — confirm VID=0x8888, PID=0x1234

**String found in .text:** `"find 8888 1234"` — literal debug log.

### Packet size

Both call sites use buffer size `0x101 = 257` bytes:
```asm
408c18: mov [esp+0x8], 0x101   ; ReportBufferLength
```
→ 1 byte Report ID (0x00) + 256 bytes payload.

---

## App Architecture (Qt class names from MOC strings)

### Communication layer

| Class | Role |
|-------|------|
| `CommunicationManager` | Top-level connection manager |
| `CommunicationExecutor` | Sends/receives SystemRequest objects |
| `CommunicationWHidWorker` | **USB HID transport** (Windows) |
| `CommunicationBleWorker` | Bluetooth transport |
| `CommunicationComWorker` | Serial/COM transport |
| `CommunicationTcpWorker` | TCP transport |
| `CommunicationWHidFactory` | Factory for HID worker |
| `CommunicationWorkerFactory` | Abstract factory |

### Device layer

| Class | Role |
|-------|------|
| `VirtualDeviceManager` | Device state & connection |
| `VirtualDeviceExecutor` | Abstract command executor |
| `VirtualDeviceSP601Executor` | **Concrete executor for SP601 DSP** |

→ DSP chip internal codename: **SP601**

### Known SP601 system commands (from strings)

| String | Meaning |
|--------|---------|
| `SP601_System_Connect_Status` | Handshake / connection check |
| `SP601_System_DSPEnable` | Enable/disable DSP processing |

### Request/response objects (from Qt signal strings)

- `SystemRequest*` — command object passed through queues
- `RequestData*` — response data object
- `on_sendPacket(void*)` — slot: send packet signal
- `on_recvMessage()` — slot: receive message signal

---

## UI Slots → DSP Parameters Mapping

All discovered via Qt MOC slot name strings in `.rdata`.

### EQ

| Slot | Parameter |
|------|-----------|
| `on_EQButtonClick` | EQ band on/off toggle |
| `on_LineEditHzChanged` | EQ band center frequency |
| `on_LineEditGainChanged` | EQ band gain (dB) |
| `on_LineEditQChanged` | EQ band Q factor |
| `on_freqTypeChanged` | EQ band filter type (peak/shelf/...) |
| `on_PEQPASSChanged` | EQ band pass/cut mode |
| `on_valuePEQPASSChanged` | EQ pass value change |
| `on_itemEQButtonActivate` | Activate EQ item |
| `on_itemSliderActivate` | Activate slider |

### Crossover (HPF / LPF)

| Slot | Parameter |
|------|-----------|
| `on_HPFSlopePushbuttonClick` | HPF slope (12/24/36/48 dB/oct) |
| `on_LPFSlopePushbuttonClick` | LPF slope |
| `on_HzChanged_1` | Filter frequency 1 |
| `on_HzChanged_2` | Filter frequency 2 |
| `on_PassChanged` | HPF/LPF pass mode |
| `on_passChanged` | (duplicate, different case) |

### Channel controls

| Slot | Parameter |
|------|-----------|
| `on_Ch1SwitchChanged` | Channel 1 on/off |
| `on_Ch3SwitchChanged` | Channel 3 on/off |
| `on_Ch5SwitchChanged` | Channel 5 on/off |
| `on_Ch7SwitchChanged` | Channel 7 on/off |
| `on_MuteSwitchChanged` | Channel mute |
| `on_PhaselSwitchChanged` | Phase invert |
| `on_bridgeChanged` | Bridge mode |
| `on_linkChanged` | Channel link |
| `on_linkWholeChanged` | Link all channels |
| `on_WriteAllChannelGain_Timer` | Timer: write all gains |

### Input sensitivity

| Slot | Parameter |
|------|-----------|
| `on_SenSivity` | Input sensitivity control |
| `on_SenSivity_Chose` | Sensitivity selection |
| `on_SenSivity_Chose_lab` | Sensitivity label selection |

### Presets / Scenes

| Slot | Count | Parameter |
|------|-------|-----------|
| `on_actionScene_1` .. `on_actionScene_16` | 16 | Scene/preset select |
| `on_SaveClick` / `on_SaveModeClick` | — | Save preset |
| `on_loadModeFile` | — | Load preset from file |
| `on_saveModeFile` | — | Save preset to file |

### Routing / Source

| Slot | Parameter |
|------|-----------|
| `on_routeSwitch` | Route switching |
| `on_soundSourceChanged` | Input source selection |
| `on_SwitchChanged_USB` | Switch to USB input |
| `on_SwitchChanged_Ble` | Switch to Bluetooth input |
| `on_SwitchChanged_DSP` | Switch DSP on/off |
| `on_SwitchChanged_High` | Switch to high-level input |

### System

| Slot | Parameter |
|------|-----------|
| `on_heartTimeOut` | Keepalive heartbeat timer |
| `on_reconnect` | Reconnect to device |
| `on_resetAll` | Full reset |
| `on_resetDefault` | Reset to defaults |
| `on_pushbuttonUpgradeClick` | Firmware upgrade |

---

## Thread Architecture

```
Main thread
  └─ CommunicationManager
       └─ CommunicationExecutor (thread)
            ├─ threadFuncSend  (VA 0x408863)  — producer loop
            │    sends packets from queue via HidD_SetOutputReport
            └─ threadFuncRecv  — consumer loop
                 reads responses via HidD_GetInputReport
```

Log strings:
- `"threadFuncSend begin threadId = "`
- `"threadFuncRecv begin , threadId = "`
- `"send queue is empty"`
- `"recv empty"` / `"recv len = "`
- `"request COMMUNICATION_ERROR_TIMEOUT"`

---

## Still Unknown from EXE

- [ ] Full packet format for each slot (would need Ghidra/IDA decompilation)
- [ ] `VirtualDeviceSP601Executor` method bodies — packet builder at ~0x402d70
- [ ] SP601Packet struct layout (object offset +0x814 referenced in builder)
- [ ] Meaning of `cmd 0x08` and `cmd 0x1c` (seen in handshake, strings only)
- [ ] How scenes 1–16 are encoded in packets
- [ ] Delay/time-alignment slot (not found by name — may be `on_SliderChanged`)
- [ ] Solo functionality (seen `on_soloValueChanged`)
