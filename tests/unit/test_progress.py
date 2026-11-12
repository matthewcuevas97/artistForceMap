"""backend/progress.py — per-run progress channel (BUG-12)."""

import threading

from backend.progress import progress_sink, report


def test_report_without_sink_prints(capsys):
    report("hello")
    assert capsys.readouterr().out == "hello\n"


def test_sink_receives_non_blank_stripped_lines(capsys):
    got = []
    with progress_sink(got.append):
        report("\n=====\n  step 1  \n\n")
    assert got == ["=====", "step 1"]
    assert capsys.readouterr().out == ""


def test_sink_is_isolated_per_thread(capsys):
    mine, ready, done = [], threading.Event(), threading.Event()

    def other():
        ready.wait(2)
        report("someone else's progress")
        done.set()

    t = threading.Thread(target=other)
    t.start()
    with progress_sink(mine.append):
        report("mine")
        ready.set()
        done.wait(2)
    t.join()
    assert mine == ["mine"]
    assert "someone else's progress" in capsys.readouterr().out
