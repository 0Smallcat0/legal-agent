"""qualifier_audit.py -- standing audit of the citation-NAME resolver's
Tier-3-style qualifier gate (D1; not a one-shot script -- wire it into CI
and re-run it after every change to `_resolve_id` or its prefix-rejection
logic, per CONTRIBUTING.md's checklist).

WHAT THIS MEASURES
-------------------
`_resolve_id` (legal_agent/anti_hallucination/verifier.py) turns a raw
citation prefix such as 「依民法」 or 「德國民法」 into a corpus statute_id.
Accepting ANY name_run that merely *ends with* a known id is also how
「德國民法」/「舊民法」/「臺北市噪音管制法」 get laundered into real statutes --
so a gate that rejects suffix-only matches on suspicious prefixes exists to
close that hole. But real generated prose routinely cites a statute through
an everyday prefix that no exact-match/alias path covers（「因為公寓大廈管理
條例」,「他可以向警察機關主張噪音管制法」）-- those citations can ONLY resolve
through the very suffix test the gate exists to police. Tightening the gate
can therefore trade one failure mode for its opposite.

This script does not grade the resolver against a number frozen in a task
document -- a hardcoded 1,552 / 67 / 43 target was checked against the four
files it was said to come from and did not reproduce (rescan on any given
day is authoritative, and is what gets written to RESULTS.md). It instead
measures itself, every run, against two independently-labelled pools with
their own, unambiguous ground truth:

  1. NATURAL sources -- every string leaf in evals/*.json, every
     journal/*.txt transcript, and every row of statutes.content. None of
     this text was written to attack the gate: it is either a real model
     answer from a real evaluation run, a hand-authored expected-statutes
     fixture, or the corpus's own verbatim legal text. Any citation here
     that endswith-matches a real corpus id but the LIVE resolver REJECTS
     is therefore, by construction, a FALSE reject.
  2. ADVERSARIAL probes -- five hand-built name-laundering strings, the
     exact ones this project's mutation/blindspot suites use as the
     headline catch (德國民法/舊民法/中國民法/臺北市噪音管制法/
     美國中華民國刑法). Ground truth here is the opposite: the live
     resolver MUST reject every one of them.

A citation counts as a "candidate" for this audit when its name_run is NOT
itself an exact corpus id, but DOES end with one -- i.e. it is exactly the
shape the pre-gate, naive `endswith` rule alone would have resolved. That
definition is behavioural, not structural: it never assumes how many tiers
the live `_resolve_id` has or what they are called, so this script keeps
working (and keeps meaning the same thing) whichever way that function
happens to be implemented on the day it runs -- including today, before
any Tier-3 gate has landed, when it correctly reports 0 rejections because
there is nothing yet to reject.

PASS CONDITION (what CI checks -- see the qualifier_audit review fix):
    false_rejects == 0
    assert_nonzero_scan(total_citations, ...)   # 0 scanned = script/regex broken
The 5-adversarial-probes-rejected count is reported and folds into the
process exit code too, but it is EXPECTED to read 0/5 until the name-
qualifier gate itself ships in verifier.py -- a 0/5 run today is this
script doing its job, not a bug in it.

Run:  python -m legal_agent.evaluation.qualifier_audit
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from legal_agent.anti_hallucination.verifier import _CITATION_RE, _resolve_id
from legal_agent.config import DB_PATH, PROJECT_ROOT
from legal_agent.evaluation import assert_nonzero_scan

EVALS_DIR = PROJECT_ROOT / "evals"
JOURNAL_DIR = PROJECT_ROOT / "journal"

# Five hand-built name-laundering probes: the exact shapes this project's
# blindspot/mutation suites use as the headline "did the gate catch a fake
# law" case. They do not occur naturally in evals/ or journal/ (nobody
# generating a real answer writes 「德國民法」), so they are exercised here on
# their own, with a hardcoded ground truth: MUST be rejected.
_LAUNDERING_PROBES: tuple[tuple[str, str], ...] = (
    ("德國民法", "依德國民法第1條規定,應負損害賠償責任。"),
    ("舊民法", "依舊民法第1條規定,應負損害賠償責任。"),
    ("中國民法", "依中國民法第1條規定,應負損害賠償責任。"),
    ("臺北市噪音管制法", "依臺北市噪音管制法第1條規定,不得製造噪音。"),
    ("美國中華民國刑法", "依美國中華民國刑法第1條規定,應處刑罰。"),
)




@dataclass(frozen=True)
class Candidate:
    """One occurrence the live gate rejected (or, for a probe, wrongly
    accepted) -- printed with context so a human can check the label."""

    source: str
    name_run: str
    context: str
    naive_candidates: tuple[str, ...]
    live_resolved: str


@dataclass
class AuditReport:
    sources_scanned: int = 0
    total_citations: int = 0
    exact_match: int = 0
    endswith_only: int = 0
    no_shape_match: int = 0
    run_counts: dict[str, int] = field(default_factory=dict)
    false_rejects: list[Candidate] = field(default_factory=list)
    true_rejects: list[Candidate] = field(default_factory=list)
    laundering_missed: list[Candidate] = field(default_factory=list)

    @property
    def distinct_endswith_runs(self) -> int:
        return len(self.run_counts)

    @property
    def rejected_total(self) -> int:
        return len(self.false_rejects) + len(self.true_rejects)

    @property
    def ok(self) -> bool:
        """The two hard pass conditions this script enforces (its exit
        code): no natural citation wrongly blocked, no laundering probe
        wrongly let through. (`assert_nonzero_scan` is a third, but it
        raises before this is ever constructed, so it is not repeated
        here.)"""
        return not self.false_rejects and not self.laundering_missed


def _classify(name_run: str, known_ids: set[str]) -> tuple[list[str], bool, str, bool]:
    """(naive suffix candidates, exact-id hit, live resolution, accepted).

    Purely behavioural: never assumes how `_resolve_id` is staged
    internally (one tier or three), only compares its OUTPUT against
    known_ids.
    """
    naive = [kid for kid in known_ids if name_run.endswith(kid)]
    exact = name_run in known_ids
    live = _resolve_id(name_run, known_ids)
    accepted = live in known_ids
    return naive, exact, live, accepted


def _iter_json_strings(obj, path: str = ""):
    """Yield (breadcrumb, string) for every non-empty string leaf in a
    loaded JSON value -- evals/*.json mixes lists-of-dicts and
    dicts-of-dicts, and the breadcrumb is what lets a rejected-candidate
    line be traced back to one record without re-opening the file.

    A dict carrying `"expect_flag": true` is a DELIBERATELY adversarial
    fixture case -- this project's own vocabulary (mutation.py's
    MutationOutcome and evals/blindspots_v1.json's "miss" cases both use
    the same field). blindspots_v1.json's prefix_foreign_de case's
    `answer`, for instance, is literally 「依德國民法第793條規定…」, planted
    so the verifier is EXPECTED to reject it. Scanning that text as if it
    were natural, ground-truth-legitimate prose would corrupt the
    false_rejects signal the moment a qualifier gate correctly starts
    rejecting it -- so such a case is skipped ENTIRELY (not just its
    `answer` field, in case the adversarial shape is echoed in a
    `description`/`note` field too). A case with `expect_flag: false`
    (blindspots_v1.json's "control" cases, every case in
    blindspots_positive_control_v1.json) is exactly the natural,
    should-always-resolve text this scan wants, and is walked as normal.
    """
    if isinstance(obj, dict) and obj.get("expect_flag") is True:
        return
    if isinstance(obj, str):
        if obj:
            yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_json_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_json_strings(v, f"{path}[{i}]")


def _context(text: str, start: int, end: int, radius: int = 24) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return f"{text[lo:start]}『{text[start:end]}』{text[end:hi]}".replace("\n", " ")


def _scan_sources() -> list[tuple[str, str]]:
    """(source_label, text) for every eval-json string leaf and every
    journal transcript. Corpus content is added separately by
    `_corpus_sources` (it needs the DB connection this function does not
    take)."""
    for directory in (EVALS_DIR, JOURNAL_DIR):
        if not directory.is_dir():
            raise SystemExit(f"[qualifier_audit] {directory} not found — run from a repo checkout")
    sources: list[tuple[str, str]] = []
    for path in sorted(EVALS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            print(f"[qualifier_audit] 略過 {path}(無法解析為 JSON):{exc}")
            continue
        for breadcrumb, s in _iter_json_strings(data):
            sources.append((f"evals/{path.name}:{breadcrumb}", s))
    for path in sorted(JOURNAL_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        sources.append((f"journal/{path.name}", text))
    return sources


def _corpus_sources(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every statute row's own verbatim content -- corpus-internal
    cross-references (公寓大廈管理條例's own text citing 民法, a 辦法 citing
    its 本法) are exactly the natural, non-adversarial shape this gate must
    not break, same as the eval/journal text."""
    rows = conn.execute("SELECT statute_id, article_no, content FROM statutes").fetchall()
    return [(f"corpus:{sid}{ano}", content or "") for sid, ano, content in rows]


def run_audit(conn: sqlite3.Connection) -> AuditReport:
    known_ids = {row[0] for row in conn.execute("SELECT DISTINCT statute_id FROM statutes")}
    report = AuditReport()
    sources = _scan_sources() + _corpus_sources(conn)
    report.sources_scanned = len(sources)

    for label, text in sources:
        for m in _CITATION_RE.finditer(text):
            report.total_citations += 1
            name_run = m.group("name")
            naive, exact, live, accepted = _classify(name_run, known_ids)
            if exact:
                report.exact_match += 1
                continue
            if not naive:
                report.no_shape_match += 1
                continue
            report.endswith_only += 1
            report.run_counts[name_run] = report.run_counts.get(name_run, 0) + 1
            if not accepted:
                report.false_rejects.append(Candidate(
                    source=label, name_run=name_run,
                    context=_context(text, m.start(), m.end()),
                    naive_candidates=tuple(sorted(naive)), live_resolved=live,
                ))

    for label, sentence in _LAUNDERING_PROBES:
        m = next(_CITATION_RE.finditer(sentence), None)
        if m is None:
            raise RuntimeError(
                f"洗白探針句本身抽不出引用,探針句壞掉:{label!r} -> {sentence!r}"
            )
        name_run = m.group("name")
        naive, exact, live, accepted = _classify(name_run, known_ids)
        if not naive and not exact:
            # The probe is built as <fake prefix> + <real corpus base name>,
            # so it should ALWAYS land in the endswith-only pool. If it does
            # not, the corpus no longer has the base name this probe assumes
            # -- a probe-integrity failure, not a "true reject".
            raise RuntimeError(
                f"洗白探針 {label!r} 的基底法規名已不在 corpus 中,探針需要更新:"
                f"name_run={name_run!r}"
            )
        candidate = Candidate(
            source=f"probe:{label}", name_run=name_run,
            context=_context(sentence, m.start(), m.end()),
            naive_candidates=tuple(sorted(naive)), live_resolved=live,
        )
        if accepted:
            report.laundering_missed.append(candidate)
        else:
            report.true_rejects.append(candidate)

    return report


def _mark(ok: bool) -> str:
    return "✓" if ok else "✗"


def render(report: AuditReport) -> str:
    lines = [
        "═══════ qualifier_audit(引用名稱限定詞閘門的常設稽核) ═══════",
        f"掃描來源數:{report.sources_scanned}"
        "(evals/*.json 全部 + journal/*.txt 全部 + corpus.statutes 全部條文列)",
        f"total_citations(全部條-style引用出現次數):{report.total_citations}",
        f"  exact_match(整串即corpus id):{report.exact_match}",
        f"  endswith_only(唯有 suffix 測試救得回來):{report.endswith_only}"
        f"({report.distinct_endswith_runs} 種相異 name_run)",
        f"  no_shape_match(不像任何 corpus 法規名,含回指/散文殘句):{report.no_shape_match}",
        "",
        f"rejected(被拒絕總數):{report.rejected_total}",
        f"  false_rejects(來自自然語料,期望=0):{len(report.false_rejects)}",
        f"  true_rejects(來自 5 個洗白探針,期望=5):{len(report.true_rejects)}/5",
        f"  laundering_missed(洗白探針被誤判合法,期望=0):{len(report.laundering_missed)}/5",
    ]
    if report.run_counts:
        lines.append("")
        lines.append("endswith_only 的相異 name_run 分佈(依出現次數遞減):")
        for name_run, n in sorted(report.run_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {name_run} × {n}")
    if report.false_rejects:
        lines.append("")
        lines.append("⚠ false_rejects 明細(合法引用被誤擋 —— 人工核對真/假拒絕從這裡開始):")
        for c in report.false_rejects:
            lines.append(
                f"  - [{c.source}] name_run={c.name_run!r} "
                f"naive候選={c.naive_candidates} live解析={c.live_resolved!r}"
            )
            lines.append(f"      前後文:{c.context}")
    if report.laundering_missed:
        lines.append("")
        lines.append("⚠ laundering_missed 明細(探針被判定合法,洗白成功):")
        for c in report.laundering_missed:
            lines.append(
                f"  - [{c.source}] name_run={c.name_run!r} "
                f"naive候選={c.naive_candidates} live解析={c.live_resolved!r}"
            )
            lines.append(f"      前後文:{c.context}")
    if report.true_rejects:
        lines.append("")
        lines.append("true_rejects 明細(探針正確被擋):")
        for c in report.true_rejects:
            lines.append(
                f"  - [{c.source}] name_run={c.name_run!r} -> {c.live_resolved!r}(不在 corpus)"
            )
    lines.append("")
    lines.append(
        f"通過條件:false_rejects == 0 {_mark(not report.false_rejects)}"
        f"｜5 個洗白探針全部正確拒絕 {_mark(not report.laundering_missed)}"
    )
    return "\n".join(lines)


if __name__ == "__main__":  # python -m legal_agent.evaluation.qualifier_audit
    from legal_agent.data.database import connect
    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()

    _conn = connect(DB_PATH)
    try:
        _report = run_audit(_conn)
    finally:
        _conn.close()

    assert_nonzero_scan(_report.total_citations, "qualifier_audit total_citations")
    print(render(_report))

    raise SystemExit(0 if _report.ok else 1)
