"""Approval screen: one HTML page where the finance controller signs off each answer.

Run from code/:  python -m app.ui.web        then open http://127.0.0.1:8000

Plain HTML and CSS, no JavaScript and no extra package: Python's standard
library serves the page, and the buttons are ordinary HTML forms that call the
same functions as `python -m app approve`:

    GET  /                       the queue; /?run=<run_id> opens one answer
    POST /ask                    question: starts a run, which waits here for sign-off
    POST /decide                 run_id, action (approve | reject | change), note, by

Approve files the answer in mock_system/, reject files nothing, and change sends
the note to the writer, after which the revised answer waits here again.
Every value shown is HTML-escaped: answers can quote managers' notes, which are
untrusted text (RS9). The server listens on 127.0.0.1 only and refuses form
posts from any other site.
"""

import argparse
import html
import re
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, quote, urlparse

from app import config
from app.runner import RunNotFound, pending_runs, resume_run, start_run

PAGE = Template((Path(__file__).with_name("page.html")).read_text(encoding="utf-8"))
DEFAULT_APPROVER = "Finance controller"
MAX_BODY_BYTES = 16 * 1024
MAX_QUESTION_CHARS = 500
DONE = {
    "approved": "Approved and filed in the leadership report.",
    "rejected": "Rejected. Nothing was filed.",
    "pending": "Sent back with your note. The revised answer is below, waiting for your sign-off.",
}
# The answer's first sentence is its headline: split it off at the first sentence end.
_FIRST_SENTENCE = re.compile(r"^(.+?[.!?])\s+(?=[A-Z])", re.S)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def figure_text(label: str, value: float) -> str:
    """Formats a figure the way the answer does (RS8), from its label."""
    if abs(value) < 0.005:
        value = 0.0  # never show "-0.00"
    if "% change" in label:
        return f"{value:+.2f} pp"
    if "%" in label:
        return f"{value:.2f}%"
    if "units" in label:
        return f"{value:,.0f} units"
    sign = "-" if value < 0 else ""
    return f"{sign}\u20b9{abs(value):,.2f}"


def filed_count() -> int:
    store = config.REPORT_STORE_DIR
    return len(list(store.glob("*.md"))) if store.is_dir() else 0


def render_flash(done: str, error: str, notice: str = "") -> str:
    if error:
        return f'<p class="flash warn" role="alert">{esc(error)}</p>'
    if notice:
        return f'<p class="flash info" role="status">{esc(notice)}</p>'
    if done in DONE:
        return f'<p class="flash" role="status">{esc(DONE[done])}</p>'
    return ""


def render_ask(question: str = "") -> str:
    return (
        '<form class="ask" method="post" action="/ask"><label for="question"><b>Ask a question</b>'
        "Sales and margin, any region, channel, category, brand or customer, April 2025 to September 2026."
        "</label>"
        f'<textarea id="question" name="question" required maxlength="{MAX_QUESTION_CHARS}" '
        'placeholder="For example: Which region had the lowest gross margin in Q1 FY27?">'
        f"{esc(question)}</textarea>"
        '<button class="approve">Get answer</button><small>Takes up to a minute.</small></form>'
    )


def render_queue(runs: list[dict], current: str) -> str:
    items = []
    for r in runs:
        here = ' aria-current="page"' if r["run_id"] == current else ""
        items.append(f'<li><a href="/?run={quote(r["run_id"])}"{here}>{esc(r["question"])}</a></li>')
    return (
        '<nav class="queue" aria-label="Answers waiting"><h2>Waiting for your sign-off</h2>'
        f"<ol>{''.join(items)}</ol></nav>"
    )


def render_empty() -> str:
    return (
        '<section class="empty"><h2>Nothing is waiting for your sign-off.</h2>'
        "<p>Ask a question on the left. The answer opens here, ready for you to approve, reject "
        "or send back with a note.</p></section>"
    )


def render_detail(run: dict, approver: str) -> str:
    result = run["result"]
    verification = result.get("verification", {})
    passed = verification.get("status") == "passed"
    checked = verification.get("checked", 0)
    amount = result.get("amount")
    citations = result.get("citations", [])

    stamp = (
        f'<div class="stamp" role="img" aria-label="Verified">Verified<small>{checked} checks</small></div>'
        if passed
        else '<div class="stamp failed" role="img" aria-label="Not verified">'
        "Review<small>see issues</small></div>"
    )
    if amount is not None:
        first = f"<div><dt>Amount</dt><dd>{esc(figure_text('', amount))}</dd></div>"
    else:
        first = f"<div><dt>Figures</dt><dd>{len(result.get('figures') or {})}</dd></div>"
    facts = (
        '<dl class="facts">'
        f"{first}"
        f"<div><dt>Independent checks</dt><dd>{checked} passed</dd></div>"
        f"<div><dt>Sources used</dt><dd>{len(citations)}</dd></div>"
        "</dl>"
    )
    text = result.get("answer", "")
    m = _FIRST_SENTENCE.match(text)
    lead, rest = (m.group(1), text[m.end() :]) if m else (text, "")
    answer = f'<p class="lead">{esc(lead)}</p>' + (f'<p class="answer">{esc(rest)}</p>' if rest else "")

    figures = ""
    if result.get("figures"):
        rows = "".join(
            f'<tr><td>{esc(k)}</td><td class="num{" neg" if v < 0 else ""}">'
            f"{esc(figure_text(k, v))}</td></tr>"
            for k, v in result["figures"].items()
        )
        figures = (
            '<h3>Figures in this answer</h3><table><thead><tr><th scope="col">Figure</th>'
            f'<th scope="col" class="num">Value</th></tr></thead><tbody>{rows}</tbody></table>'
        )
    issues = ""
    if verification.get("issues"):
        issues = (
            '<p class="flash warn">Check before approving: ' + esc("; ".join(verification["issues"])) + "</p>"
        )

    rid = esc(run["run_id"])
    signoff = (
        '<section class="signoff" aria-labelledby="signoff-title"><h3 id="signoff-title">Your sign-off</h3>'
        "<p>Approve to file this answer in the leadership report. Reject to file nothing. "
        "Or request a change, and the revised answer comes back here for your sign-off.</p>"
        '<form method="post" action="/decide">'
        f'<input type="hidden" name="run_id" value="{rid}">'
        f'<div class="approver"><label for="by">Approved by</label>'
        f'<input type="text" id="by" name="by" value="{esc(approver)}" required maxlength="80"></div>'
        '<div class="row"><button class="approve" name="action" value="approve">Approve and file</button>'
        '<button class="reject" name="action" value="reject">Reject</button></div></form>'
        '<form method="post" action="/decide" class="change">'
        f'<input type="hidden" name="run_id" value="{rid}">'
        f'<input type="hidden" name="by" value="{esc(approver)}">'
        '<input type="hidden" name="action" value="change">'
        '<div class="row"><div><label for="note">What should change in the answer?</label>'
        '<textarea id="note" name="note" required maxlength="1000" '
        'placeholder="For example: lead with the gap to target."></textarea></div>'
        "<button>Request change</button></div></form></section>"
    )
    return (
        f'<article class="sheet"><div class="sheet-head"><h2>{esc(run["question"])}</h2>{stamp}</div>'
        f"{facts}{issues}{answer}{figures}{signoff}</article>"
    )


def render_page(
    selected: str = "", done: str = "", error: str = "", notice: str = "", question: str = ""
) -> str:
    runs = pending_runs()
    approver = DEFAULT_APPROVER
    flash = render_flash(done, error, notice)
    if not runs:
        queue, detail = render_ask(question), render_empty()
    else:
        run = next((r for r in runs if r["run_id"] == selected), runs[0])
        queue = f'<div class="side">{render_ask(question)}{render_queue(runs, run["run_id"])}</div>'
        detail = render_detail(run, approver)
    return PAGE.substitute(
        waiting=len(runs),
        filed=filed_count(),
        flash=flash,
        queue=queue,
        detail=detail,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "ApprovalDesk"

    def _send(self, status: HTTPStatus, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; script-src 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _same_site(self) -> bool:
        """Refuse form posts made from another site (the page only runs on this machine)."""
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        local = host.split(":")[0] in ("127.0.0.1", "localhost")
        return local and (origin is None or urlparse(origin).netloc == host)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path != "/":
            self._send(
                HTTPStatus.NOT_FOUND, "<h1>Not found</h1><p><a href='/'>Back to the approval desk</a></p>"
            )
            return
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self._send(HTTPStatus.OK, render_page(q.get("run", ""), q.get("done", "")))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/ask", "/decide"):
            self._send(HTTPStatus.NOT_FOUND, "<h1>Not found</h1>")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "<h1>Too large</h1>")
            return
        # Read the form before any refusal: closing with unread data resets the connection on Windows.
        body = self.rfile.read(length).decode("utf-8")
        if not self._same_site():
            self._send(
                HTTPStatus.FORBIDDEN,
                "<h1>Refused</h1><p>Questions and sign-offs only come from this page.</p>",
            )
            return
        form = {k: v[0].strip() for k, v in parse_qs(body).items()}
        if path == "/ask":
            self._ask(form.get("question", ""))
            return
        run_id, action, note = form.get("run_id", ""), form.get("action", ""), form.get("note", "")
        by = form.get("by") or DEFAULT_APPROVER
        if action not in ("approve", "reject", "change") or (action == "change" and not note):
            msg = (
                "Write what should change before requesting a change."
                if action == "change"
                else "Choose approve, reject or request change."
            )
            self._send(HTTPStatus.BAD_REQUEST, render_page(run_id, error=msg))
            return
        try:
            result = resume_run(run_id, action, note, by=by)
        except RunNotFound:
            self._send(HTTPStatus.NOT_FOUND, render_page(error="This answer was already signed off."))
            return
        status = result["approval"]["status"]
        target = f"/?done={quote(status)}"
        if status == "pending":
            target += f"&run={quote(run_id)}"
        self._redirect(target)

    def _ask(self, question: str) -> None:
        """Runs the question through the agents. Answers wait for sign-off; refusals are shown at once."""
        if not question or len(question) > MAX_QUESTION_CHARS:
            msg = f"Type a question of up to {MAX_QUESTION_CHARS} characters."
            self._send(HTTPStatus.BAD_REQUEST, render_page(error=msg, question=question[:MAX_QUESTION_CHARS]))
            return
        case_id = "ASK-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        result = start_run({"case_id": case_id, "input": {"question": question}}, auto_approve=False)
        if result.get("approval", {}).get("status") == "pending":
            self._redirect(f"/?run={quote(result['trace_id'])}")
            return
        notice = f"Not answered: {result.get('answer', '')}"
        self._send(HTTPStatus.OK, render_page(notice=notice, question=question))

    def log_message(self, format: str, *args) -> None:  # keep the terminal quiet
        pass


def make_server(port: int = 8000) -> HTTPServer:
    return HTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.ui.web", description="Approval screen")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = make_server(args.port)
    print(f"Approval desk: http://127.0.0.1:{args.port}   (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
