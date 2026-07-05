"""Guards on write commands that must never reach a live device."""

from octapro.commands.write import (
    run_write_bridge,
    run_write_gain,
    run_write_master,
    run_write_mute,
    run_write_phase,
)


class TestMasterGainCommitBlocked:
    """Live-tested 2026-07-05: CH0 WRITE_DSP force-switches the input source
    to high level instead of writing volume — commit must be refused."""

    def test_ch0_commit_refused_without_device(self):
        # returns 1 before any transport is opened — no device needed
        assert run_write_gain(channel=0, db=-3.0, commit=True) == 1

    def test_ch0_dry_run_still_allowed(self):
        assert run_write_gain(channel=0, db=-3.0, commit=False) == 0


class TestWriteMasterDryRun:
    """`write master` (CMD 0x08) is the real master-volume write — dry-run
    must not require a device."""

    def test_dry_run_no_device_needed(self):
        assert run_write_master(db=-20.0, commit=False) == 0


class TestWriteMuteDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_mute(channel=0, mute=True, commit=False) == 0
        assert run_write_mute(channel=0, mute=False, commit=False) == 0


class TestWritePhaseDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_phase(channel=6, invert=True, commit=False) == 0
        assert run_write_phase(channel=6, invert=False, commit=False) == 0


class TestWriteBridgeDryRun:
    def test_dry_run_no_device_needed(self):
        assert run_write_bridge(bridged=True, commit=False) == 0
        assert run_write_bridge(bridged=False, commit=False) == 0
