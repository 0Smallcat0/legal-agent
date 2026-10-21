"""qualifier_audit.py -- standing audit of the citation-NAME resolver's
qualifier gate. Re-run after every change to `_resolve_id` or its
prefix-rejection logic.

`_resolve_id` (anti_hallucination/verifier.py) turns a citation prefix such
as 「依民法」 into a corpus statute_id. Accepting any name_run that merely
ENDS WITH a known id launders 「德國民法」/「臺北市噪音管制法」 into real
statutes; but real prose also cites through everyday prefixes
（「因為公寓大廈管理條例」）that only that suffix test resolves. Tightening the
gate can trade one failure for its opposite, so this measures both, every
run, against two pools with unambiguous ground truth (no frozen target):

  1. NATURAL sources -- every string leaf in evals/*.json (minus
     expect_flag=true fixtures), every journal/*.txt, every statutes.content
     row. None was written to attack the gate, so a citation that
     endswith-matches a corpus id but the live resolver REJECTS is a FALSE
     reject.
  2. ADVERSARIAL probes -- five hand-built laundering strings (德國民法/
     舊民法/中國民法/臺北市噪音管制法/美國中華民國刑法), which MUST be rejected.

A "candidate" is a name_run that is not itself a corpus id but ends with one
-- defined by behaviour, not by how `_resolve_id` is staged internally.

Exit 0 only if: total_citations > 0 (assert_nonzero_scan; 0 = regex/script
broken), false_rejects == 0, and all 5 probes are rejected (5/5).

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

# Name-laundering probes (shared shapes with blindspots/mutation). They do not
# occur naturally in evals/ or journal/, so they are planted: MUST be rejected.
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
        """No natural citation wrongly blocked, no laundering probe let
        through. (__main__ also calls `assert_nonzero_scan` before using
        this.)"""
        return not self.false_rejects and not self.laundering_missed


def _classify(name_run: str, known_ids: set[str]) -> tuple[list[str], bool, str, bool]:
    """(naive suffix candidates, exact-id hit, live resolution, accepted).
    Compares only `_resolve_id`'s OUTPUT against known_ids."""
    naive = [kid for kid in known_ids if name_run.endswith(kid)]
    exact = name_run in known_ids
    live = _resolve_id(name_run, known_ids)
    accepted = live in known_ids
    return naive, exact, live, accepted


def _iter_json_strings(obj, path: str = ""):
    """Yield (breadcrumb, string) for every non-empty string leaf in a
    loaded JSON value; the breadcrumb traces a hit back to one record.

    A dict with `"expect_flag": true` is a deliberately adversarial fixture
    (e.g. blindspots_v1.json's 「依德國民法第793條…」) and is skipped ENTIRELY
    -- every field, in case a description echoes it -- or a correct
    rejection would count as a false reject. `expect_flag: false` cases are
    natural text and are walked.
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
    journal transcript. Corpus rows come from `_corpus_sources`."""
    for directory in (EVALS_DIR, JOURNAL_DIR):
        if not directory.is_dir():
            raise SystemExit(f"[qualifier_audit] {directory} not found — run from a repo checkout")
    sources: list[tuple[str, str]] = []
    for path in sorted(EVALS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SystemExit(f"[qualifier_audit] {path} 無法解析為 JSON:{exc}") from exc
        for breadcrumb, s in _iter_json_strings(data):
            sources.append((f"evals/{path.name}:{breadcrumb}", s))
    for path in sorted(JOURNAL_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="replace")
        sources.append((f"journal/{path.name}", text))
    # Corpus rows alone supply citations, so assert_nonzero_scan cannot see an
    # input directory that came back empty.
    for prefix in ("evals/", "journal/"):
        if not any(label.startswith(prefix) for label, _ in sources):
            raise SystemExit(f"[qualifier_audit] {prefix} 沒有可掃描的內容 — 不是完整的 repo checkout")
    return sources


def _corpus_sources(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Every statute row's verbatim content -- its cross-references are
    natural citations the gate must not break."""
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
            # <fake prefix> + <real base name> must land in the endswith pool;
            # if not, the corpus lost the base name -- a broken probe, not a
            # true reject.
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
