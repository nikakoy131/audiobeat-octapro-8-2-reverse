from pathlib import Path

import pytest

# Root of the repository (contains dsp_m2.dat, pcapng files, etc.)
REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def dat_path():
    p = REPO_ROOT / "dsp_m2.dat"
    if not p.exists():
        pytest.skip("dsp_m2.dat not found in repo root")
    return p
