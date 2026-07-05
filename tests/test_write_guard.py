"""Guards on write commands that must never reach a live device."""

from octapro.commands.write import run_write_gain


class TestMasterGainCommitBlocked:
    """Live-tested 2026-07-05: CH0 WRITE_DSP force-switches the input source
    to high level instead of writing volume — commit must be refused."""

    def test_ch0_commit_refused_without_device(self):
        # returns 1 before any transport is opened — no device needed
        assert run_write_gain(channel=0, db=-3.0, commit=True) == 1

    def test_ch0_dry_run_still_allowed(self):
        assert run_write_gain(channel=0, db=-3.0, commit=False) == 0
