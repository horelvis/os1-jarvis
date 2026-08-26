"""Following the file the wrapper writes.

No gateway, no assistant, no strip: a file is appended to and the
follower is expected to notice, which is the whole of its job.
"""

import threading
import time

from Hermes.plugins.samantha_code.live import END, START, follow, summarise


def _collect(path, stop, out):
    for item in follow(path, stop.is_set):
        out.append(item)


def test_it_notices_lines_appended_after_it_started(tmp_path):
    log = tmp_path / "live.log"
    log.write_text("vieja\n")
    stop, out = threading.Event(), []
    thread = threading.Thread(target=_collect, args=(log, stop, out), daemon=True)
    thread.start()
    time.sleep(0.2)
    with log.open("a") as fh:
        fh.write("nueva\n")
        fh.flush()
    time.sleep(0.4)
    stop.set()
    thread.join(timeout=2)

    kinds = [k for k, _ in out]
    texts = [t for _, t in out]
    assert "line" in kinds
    assert "nueva" in texts
    # What was written before anybody was watching belongs to a previous
    # run; replaying it would show old work as if it were happening now.
    assert "vieja" not in texts


def test_the_markers_are_recognised(tmp_path):
    log = tmp_path / "live.log"
    log.write_text("")
    stop, out = threading.Event(), []
    thread = threading.Thread(target=_collect, args=(log, stop, out), daemon=True)
    thread.start()
    time.sleep(0.2)
    with log.open("a") as fh:
        fh.write(f"{START} 12:00:00\nhaciendo algo\n{END} 0\n")
        fh.flush()
    time.sleep(0.4)
    stop.set()
    thread.join(timeout=2)

    assert [k for k, _ in out] == ["start", "line", "end"]


def test_a_missing_file_is_waited_for_not_an_error(tmp_path):
    log = tmp_path / "not-yet.log"
    stop, out = threading.Event(), []
    thread = threading.Thread(target=_collect, args=(log, stop, out), daemon=True)
    thread.start()
    time.sleep(0.2)
    log.write_text("")
    with log.open("a") as fh:
        fh.write("por fin\n")
        fh.flush()
    time.sleep(0.4)
    stop.set()
    thread.join(timeout=2)

    assert ("line", "por fin") in out


def test_plain_text_passes_through():
    assert summarise("225 passed in 6.49s") == "225 passed in 6.49s"


def test_a_tool_call_becomes_one_short_line():
    event = (
        '{"type":"assistant","message":{"content":[{"type":"tool_use",'
        '"name":"Bash","input":{"command":"pytest -q"}}]}}'
    )
    assert summarise(event) == "· Bash: pytest -q"


def test_what_the_assistant_says_is_kept():
    event = '{"type":"assistant","message":{"content":[{"type":"text","text":"Ya lo veo"}]}}'
    assert summarise(event) == "Ya lo veo"


def test_noise_becomes_nothing():
    assert summarise('{"type":"system","subtype":"thinking_tokens"}') == ""
