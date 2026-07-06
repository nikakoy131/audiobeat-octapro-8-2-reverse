"""Guards on write commands that must never reach a live device."""

from octapro.commands.write import (
    run_write_bridge,
    run_write_delay,
    run_write_eq,
    run_write_eq_pass,
    run_write_gain,
    run_write_master,
    run_write_mute,
    run_write_phase,
)


class TestWriteGainChannel:
    """`write gain` is the per-channel output fader (CMD 0x08 sub 0x03),
    ch=1..10. ch=0 is rejected — the master fader is `write master`."""

    def test_ch0_rejected(self):
        # ch0 returns 1 immediately (dry-run or not) — directs to `write master`
        assert run_write_gain(channel=0, db=-3.0, commit=True) == 1
        assert run_write_gain(channel=0, db=-3.0, commit=False) == 1

    def test_channel_dry_run_no_device_needed(self):
        assert run_write_gain(channel=3, db=-6.0, commit=False) == 0


class TestWriteMasterDryRun:
    """`write master` (CMD 0x08) is the real master-volume write — dry-run
    must not require a device."""

    def test_dry_run_no_device_needed(self):
        assert run_write_master(db=-20.0, commit=False) == 0


class TestWriteMuteDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_mute(channel=0, mute=True, commit=False) == 0
        assert run_write_mute(channel=0, mute=False, commit=False) == 0


class TestWriteDelayDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_delay(channel=2, ms=1.512, commit=False) == 0


class TestWriteEqDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_eq(channel=1, band=18, db=6.0, q=1.0, freq=None, commit=False) == 0
        assert run_write_eq(channel=3, band=15, db=0.0, q=2.9, freq=520.0, commit=False) == 0


class TestWriteEqPassDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_eq_pass(channel=7, bypass=True, commit=False) == 0
        assert run_write_eq_pass(channel=7, bypass=False, commit=False) == 0


class TestWritePhaseDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_phase(channel=6, invert=True, commit=False) == 0
        assert run_write_phase(channel=6, invert=False, commit=False) == 0


class TestWriteBridgeDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_bridge(bridged=True, commit=False) == 0
        assert run_write_bridge(bridged=False, commit=False) == 0
