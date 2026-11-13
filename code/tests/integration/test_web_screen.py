"""The HTML approval page: served by the real server, used through plain HTTP form posts."""

import http.client
import re
import threading
from urllib.parse import urlencode

import pytest

from app import config
from app.runner import pending_runs, start_run
from app.ui.web import figure_text, make_server, render_detail

QUESTION = "What was West's net revenue in September 2026?"


@pytest.fixture
def server():
    srv = make_server(0)  # any free port
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def get(port: int, path: str = "/") -> tuple[int, str]:
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    con.request("GET", path)
    r = con.getresponse()
    return r.status, r.read().decode("utf-8")


def post(port: int, form: dict, origin: str | None = None, path: str = "/decide") -> tuple[int, dict, str]:
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if origin:
        headers["Origin"] = origin
    con.request("POST", path, urlencode(form), headers)
    r = con.getresponse()
    return r.status, dict(r.getheaders()), r.read().decode("utf-8")


def queue_one(case_id: str) -> str:
    return start_run({"case_id": case_id, "input": {"question": QUESTION}}, False)["trace_id"]


def test_empty_queue_says_how_to_start(server):
    status, page = get(server)
    assert status == 200
    assert "Nothing is waiting for your sign-off." in page
    assert "Ask a question" in page
    assert "<script" not in page  # the page uses no JavaScript


def test_question_asked_on_the_page_opens_for_sign_off(server):
    status, headers, _ = post(server, {"question": QUESTION}, path="/ask")
    assert status == 303
    waiting = pending_runs()
    assert [r["question"] for r in waiting] == [QUESTION]
    assert headers["Location"] == f"/?run={waiting[0]['run_id']}"
    _, page = get(server, headers["Location"])
    assert "\u20b96,015,889.56" in page


def test_question_the_data_cannot_answer_shows_why(server):
    status, _, page = post(
        server, {"question": "What was marketing spend for East in July 2026?"}, path="/ask"
    )
    assert status == 200
    assert "Not answered:" in page
    assert "marketing" in page
    assert pending_runs() == []


def test_empty_question_is_refused(server):
    status, _, page = post(server, {"question": "   "}, path="/ask")
    assert status == 400
    assert "Type a question" in page


def test_waiting_answer_is_shown_with_its_figures(server):
    queue_one("WEB-01")
    _, page = get(server)
    assert "West&#x27;s net revenue in September 2026?" in page
    visible_text = re.sub(r"<[^>]+>", " ", page)
    assert "WEB-01" not in visible_text  # internal ids are not shown to the controller
    assert "West net revenue, September 2026" in page
    assert "\u20b96,015,889.56" in page
    assert "Verified" in page


def test_approve_files_the_answer(server):
    run_id = queue_one("WEB-02")
    status, headers, _ = post(server, {"run_id": run_id, "action": "approve", "by": "Asha (controller)"})
    assert status == 303
    assert headers["Location"].startswith("/?done=approved")
    assert pending_runs() == []
    report = (config.REPORT_STORE_DIR / "WEB-02.md").read_text(encoding="utf-8")
    assert "approved by Asha (controller)" in report
    _, page = get(server, headers["Location"])
    assert "Approved and filed in the leadership report." in page


def test_reject_files_nothing(server):
    run_id = queue_one("WEB-03")
    status, _, _ = post(server, {"run_id": run_id, "action": "reject"})
    assert status == 303
    assert not (config.REPORT_STORE_DIR / "WEB-03.md").exists()


def test_change_needs_a_note_and_then_waits_again(server):
    run_id = queue_one("WEB-04")
    status, _, page = post(server, {"run_id": run_id, "action": "change", "note": "  "})
    assert status == 400
    assert "Write what should change" in page
    status, headers, _ = post(server, {"run_id": run_id, "action": "change", "note": "Lead with the total."})
    assert status == 303
    assert f"run={run_id}" in headers["Location"]
    assert [r["run_id"] for r in pending_runs()] == [run_id]


def test_post_from_another_site_is_refused(server):
    run_id = queue_one("WEB-05")
    status, _, _ = post(server, {"run_id": run_id, "action": "approve"}, origin="https://evil.example")
    assert status == 403
    status, _, _ = post(server, {"question": QUESTION}, origin="https://evil.example", path="/ask")
    assert status == 403
    assert [r["run_id"] for r in pending_runs()] == [run_id]


def test_unknown_run_is_explained(server):
    status, _, page = post(server, {"run_id": "no-such-run", "action": "approve"})
    assert status == 404
    assert "already signed off" in page


def test_answer_leads_with_its_first_sentence():
    run = {
        "run_id": "R1",
        "case_id": "X",
        "question": "q",
        "result": {"decision": "answered", "answer": "South margin, Aug 2026: 34.67%. It fell. Tables win."},
    }
    page = render_detail(run, "Finance controller")
    assert '<p class="lead">South margin, Aug 2026: 34.67%.</p>' in page
    assert '<p class="answer">It fell. Tables win.</p>' in page


def test_text_from_documents_is_escaped():
    run = {
        "run_id": "R1",
        "case_id": "X",
        "question": "<b>q</b>",
        "result": {"decision": "answered", "answer": 'Note says "<script>alert(1)</script>"', "figures": {}},
    }
    page = render_detail(run, "Finance controller")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page


@pytest.mark.parametrize(
    ("label", "value", "text"),
    [
        ("South gross margin %, August 2026", 34.6712, "34.67%"),
        ("South gross margin % change, August 2026 to September 2026", -14.42, "-14.42 pp"),
        ("South gross margin % change from returns, August 2026 to September 2026", -0.001, "+0.00 pp"),
        ("Central net revenue minus target, July 2026", -277134.74, "-\u20b9277,134.74"),
    ],
)
def test_figures_are_formatted_like_the_answer(label, value, text):
    assert figure_text(label, value) == text
