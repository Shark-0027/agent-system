import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from code.workbench.csv_agent import sandbox


def _slow(delay=0.05):
    time.sleep(delay)
    return 42


def _boom():
    raise ValueError("bad")


def _never():
    while True:
        time.sleep(0.05)


def test_run_isolated_success():
    assert sandbox.run_isolated(_slow, (0.01,), timeout=5).get("result") == 42


def test_run_isolated_error():
    out = sandbox.run_isolated(_boom, (), timeout=5)
    assert out["success"] is False
    assert "bad" in out["error"]


def test_run_isolated_timeout():
    t0 = time.time()
    out = sandbox.run_isolated(_never, (), timeout=0.3)
    assert out["success"] is False
    assert time.time() - t0 < 2.0