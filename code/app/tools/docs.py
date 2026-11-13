"""Company documents: managers' monthly notes and promotion briefs.

Documents are untrusted input (RS9). Every sentence that reads like an
instruction to an AI or system is removed before any agent sees the text,
and the removal is reported so the approver can see it. Numbers in notes are
claims to check against the tables (RS4), never facts.
"""

import re
from dataclasses import dataclass, field

from .. import config

_INSTRUCTION_PATTERNS = [
    r"\b(note|message|instruction)s?\s+(to|for)\s+(any\s+)?(ai|assistant|analyst|model|llm|system)",
    r"\bai\s+(analyst|assistant|model|system)s?\b",
    r"\bignore\b.*\b(previous|above|prior|instructions?|rules?)\b",
    r"\bdisregard\b",
    r"\b(system|developer)\s+prompt\b",
    r"\byou\s+(must|should)\s+(report|say|state|write|exclude|include)\b",
    r"\breport\b.+\bas\b.+\bin\s+all\s+(summaries|reports)\b",
    r"\bexclude\s+this\b",
]
_INSTRUCTION_RE = re.compile("|".join(_INSTRUCTION_PATTERNS), re.I)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Document:
    doc_id: str  # citation id, e.g. "commentary/2026-09_south.md"
    title: str
    text: str  # screened text, instruction-like sentences removed
    removed: list[str] = field(default_factory=list)


def looks_like_instruction(sentence: str) -> bool:
    return bool(_INSTRUCTION_RE.search(sentence))


def screen(text: str) -> tuple[str, list[str]]:
    """Split into sentences, drop the ones that read like instructions."""
    kept, removed = [], []
    for para in text.split("\n"):
        para_kept = []
        for sentence in _SENTENCE_RE.split(para.strip()):
            if not sentence:
                continue
            (removed if looks_like_instruction(sentence) else para_kept).append(sentence)
        if para_kept:
            kept.append(" ".join(para_kept))
    return "\n".join(kept), removed


def _load(doc_id: str) -> Document | None:
    path = config.DOCS_DIR / doc_id
    if not path.is_file():
        return None
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    title = lines[0].lstrip("# ").strip() if lines else doc_id
    body = [ln for ln in lines[1:] if "synthetic and fictional" not in ln.lower()]
    text, removed = screen("\n".join(body))
    return Document(doc_id, title, text, removed)


def commentary(month: str, region_name: str) -> Document | None:
    """The regional manager's note for one month ('YYYY-MM') and region."""
    return _load(f"commentary/{month}_{region_name.lower()}.md")


def promo_brief(promo_id: str) -> Document | None:
    return _load(f"promo_briefs/{promo_id}.md")


# ---- claims in notes that can be checked against the tables (RS4) ----

_REVENUE_CHANGE_RE = re.compile(r"net revenue was (up|down) about (\d+(?:\.\d+)?)%\s+on last month", re.I)
_TARGET_RE = re.compile(r"finished (ahead of|behind) target", re.I)
_COST_RE = re.compile(r"\b(raw material|input|factory|ingredient|production)\s+costs?\b", re.I)


def claims(doc: Document) -> list[dict]:
    """Checkable claims in a note: revenue change, target result, cost pressure."""
    found = []
    for m in _REVENUE_CHANGE_RE.finditer(doc.text):
        pct = float(m.group(2)) * (1 if m.group(1).lower() == "up" else -1)
        found.append({"type": "revenue_change_pct", "claimed": pct, "text": m.group(0)})
    for m in _TARGET_RE.finditer(doc.text):
        found.append({"type": "target", "claimed": m.group(1).lower() == "ahead of", "text": m.group(0)})
    m = _COST_RE.search(doc.text)
    if m:
        sentences = (s for line in doc.text.splitlines() for s in _SENTENCE_RE.split(line))
        # Quote the one sentence that makes the claim, never the note's header lines.
        sentence = next((s for s in sentences if m.group(0) in s), m.group(0))
        found.append({"type": "cost_pressure", "claimed": True, "text": sentence.strip()})
    return found
