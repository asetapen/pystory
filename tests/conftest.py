import pytest

import pystory.obsbot as obsbot


@pytest.fixture(autouse=True)
def no_real_obsbot_cli(monkeypatch):
    """main() now toggles OBSBOT tracking at start and exit, so any test that
    drives the real loop would otherwise run the real obsbot-cli against a
    real camera. Tests that start pystory in a SUBPROCESS are not covered by
    this and must pass --no-obsbot-tracking-on-run or a fake --obsbot-cli-path."""
    calls = []

    def fake_run_cli(config, script):
        calls.append(script)
        return False

    monkeypatch.setattr(obsbot, "_run_cli", fake_run_cli)
    return calls
