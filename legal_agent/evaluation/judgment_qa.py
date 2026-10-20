"""Judgment citation acceptance set: does the page cite the judgments it should?

`judgment_relevance` grades the 案由 of the FIRST judgment shown, for the 168
real sessions. This harness grades every judgment shown (up to three), against
a list of judgments each question SHOULD cite, written into the question file:

  evals/judgment_qa_v1.json   {"meta": {...}, "questions": [{id, family,
                                question, expected_statutes,
                                expected_judgments: [{jid, cite}, ...]}]}

Where the expected judgments come from, so nobody has to trust a hand pick:
`expected_for` — every shipped judgment that serves the question's family
(`judgment_coverage.serves_family`: its 案由 names the family) AND cites at
least one of the question's expected articles. That list is FROZEN into the
file once (`--freeze`, which only fills questions that have none) and is never
regenerated to make a case pass (CONTRIBUTING rule 3).

Four numbers, per question then pooled:
  * 引用正確率  shown judgments that are on the expected list / all shown;
  * 命中率      questions with ≥1 expected judgment among those shown;
  * 答非所問率  questions whose page shows judgments, none of the question's
                family — the reader is pointed at a different kind of dispute;
  * 無判決      questions whose page shows none.

Two answer shapes, as in `judgment_relevance`:
  * focus  — the answer cites the right law (expected articles that reached
             the window): this layer measured on its own;
  * window — the answer cites nothing verifiable, so stage3 falls back to the
             whole retrieval window: the worst case the product can show.

Every miss gets one cause (`Case.cause`) so the next fix can be aimed at the
commonest: 語料無應引判決 / 檢索漏條文 / 被擠出前三 / 引錯家族.

Run:  python -m legal_agent.evaluation.judgment_qa [FILE] [--freeze]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from legal_agent.config import PROJECT_ROOT
from legal_agent.evaluation import corpus_connection
from legal_agent.evaluation.judgment_coverage import serves_family
from legal_agent.evaluation.judgment_relevance import case_type_family

DEFAULT_FILE = PROJECT_ROOT / "evals" / "judgment_qa_v1.json"
MODES = ("focus", "window")


def expected_for(conn, family: str, statutes: list[str]) -> list[dict]:
    """SHIPPED judgments a question about `family` citing `statutes` should cite.
    Shipped only: a machine that has also harvested judgments derives the same
    list as a fresh clone."""
    from legal_agent.data.bootstrap import shipped_judgment_ids
    from legal_agent.data.judgment_text import citation

    wanted = set(statutes)
    shipped = set(shipped_judgment_ids())
    out = []
    for jid, case_type, cited, full_text in conn.execute(
            "SELECT jid, case_type, cited_articles, full_text FROM judgments ORDER BY jid"):
        if jid not in shipped:
            continue
        try:
            cited_list = json.loads(cited or "[]")
        except ValueError:
            continue
        refs = {f"{c.get('statute_id')}{c.get('article_no')}" for c in cited_list}
        if serves_family(case_type, cited_list) == family and refs & wanted:
            out.append({"jid": jid, "cite": citation(full_text)})
    return out


@dataclass
class Case:
    id: str
    family: str
    expected: set[str]
    shown: list[tuple[str, str | None]] = field(default_factory=list)   # (jid, 案由)
    in_window: bool = False         # ≥1 expected article reached the retrieval window
    available: int | None = None    # expected judgments the table holds (None = all)

    @property
    def correct(self) -> int:
        return sum(1 for jid, _ct in self.shown if jid in self.expected)

    @property
    def hit(self) -> bool:
        return self.correct > 0

    @property
    def off_topic(self) -> bool:
        return bool(self.shown) and all(
            case_type_family(ct) != self.family for _jid, ct in self.shown)

    @property
    def cause(self) -> str | None:
        """Why this question did not get an expected judgment (None when it did)."""
        if self.hit:
            return None
        if not self.expected or self.available == 0:
            return "語料無應引判決"
        if not self.in_window:
            return "檢索漏條文"
        if self.off_topic:
            return "引錯家族"
        return "被擠出前三"


@dataclass
class QAReport:
    mode: str
    cases: list[Case] = field(default_factory=list)
    dense_fallbacks: int = 0

    @property
    def shown(self) -> int:
        return sum(len(c.shown) for c in self.cases)

    @property
    def correct(self) -> int:
        return sum(c.correct for c in self.cases)

    @property
    def precision(self) -> float:
        return self.correct / self.shown if self.shown else 0.0

    @property
    def hits(self) -> int:
        return sum(c.hit for c in self.cases)

    @property
    def off_topic(self) -> int:
        return sum(c.off_topic for c in self.cases)

    @property
    def empty(self) -> int:
        return sum(1 for c in self.cases if not c.shown)

    def causes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.cases:
            if c.cause:
                out[c.cause] = out.get(c.cause, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def summary(self) -> str:
        n = len(self.cases)
        return (f"[{self.mode}] 引用正確率 {self.correct}/{self.shown}({self.precision:.1%})"
                f"  命中 {self.hits}/{n}  答非所問 {self.off_topic}/{n}  無判決 {self.empty}/{n}")

    def render(self) -> str:
        lines = [f"═══════ 判決引用驗收集({self.mode}) ═══════"]
        for c in self.cases:
            mark = "OK  " if c.hit else ("OFF " if c.off_topic else "MISS")
            shown = "、".join(f"{ct}{'✓' if jid in c.expected else ''}"
                             for jid, ct in c.shown) or "(無判決)"
            lines.append(f"{mark} {c.id:26s} {c.family:6s} 應引 {len(c.expected):2d}  {shown}")
        by_family: dict[str, list[Case]] = {}
        for c in self.cases:
            by_family.setdefault(c.family, []).append(c)
        lines += ["", f"{'家族':8s} {'題數':>3s} {'命中':>3s} {'正確/顯示':>8s} {'答非所問':>4s}"]
        for fam, cs in sorted(by_family.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"{fam:8s} {len(cs):5d} {sum(c.hit for c in cs):5d} "
                         f"{sum(c.correct for c in cs):5d}/{sum(len(c.shown) for c in cs):<4d}"
                         f" {sum(c.off_topic for c in cs):6d}")
        lines += ["", self.summary(),
                  "未命中原因:" + (",".join(f"{k} {v}" for k, v in self.causes().items()) or "(無)")]
        if self.dense_fallbacks:
            lines.append(f"⚠ {self.dense_fallbacks}/{len(self.cases)} 個查詢的 dense 半邊退回純 BM25,"
                         "不可與 dense 下的數字相比。")
        return "\n".join(lines)


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def freeze(path, conn=None) -> int:
    """Write `expected_judgments` into every question that has none. Returns how
    many questions were filled. Never touches a question that already has a list."""
    data = load(path)
    filled = 0
    with corpus_connection(conn) as conn:
        for q in data["questions"]:
            if "expected_judgments" in q:
                continue
            q["expected_judgments"] = expected_for(conn, q["family"], q["expected_statutes"])
            filled += 1
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return filled


def run_judgment_qa(path=DEFAULT_FILE, mode: str = "focus", conn=None,
                    k: int | None = None) -> QAReport:
    from legal_agent.retrieval.judgments import related_judgments
    from legal_agent.retrieval.retriever import (
        DEFAULT_K,
        dense_fallback_count,
        reset_dense_fallbacks,
        retrieve,
    )

    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    reset_dense_fallbacks()
    report = QAReport(mode)
    with corpus_connection(conn) as conn:
        present = {r[0] for r in conn.execute("SELECT jid FROM judgments")}
        for q in load(path)["questions"]:
            expected = set(q["expected_statutes"])
            found = retrieve(q["question"], k=DEFAULT_K if k is None else k, conn=conn)
            window = {(s.statute_id, s.article_no) for s in found
                      if f"{s.statute_id}{s.article_no}" in expected}
            focus = (window or None) if mode == "focus" else None
            refs = related_judgments(found, conn=conn, focus=focus)
            should = {e["jid"] for e in q.get("expected_judgments", [])}
            report.cases.append(Case(
                id=q["id"], family=q["family"], expected=should,
                shown=[(r.jid, r.case_type) for r in refs],
                in_window=bool(window), available=len(should & present),
            ))
    report.dense_fallbacks = dense_fallback_count()
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    parser = argparse.ArgumentParser(prog="python -m legal_agent.evaluation.judgment_qa")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_FILE))
    parser.add_argument("--freeze", action="store_true",
                        help="替還沒有 expected_judgments 的題目從語料推出應引判決並寫回")
    parser.add_argument("--mode", choices=(*MODES, "both"), default="both")
    args = parser.parse_args(argv)

    enable_utf8_stdout()
    print_corpus_fingerprint()
    if args.freeze:
        print(f"寫入 {freeze(args.path)} 題的應引判決")
        return 0
    reports = [run_judgment_qa(args.path, m) for m in (MODES if args.mode == "both" else (args.mode,))]
    for r in reports:
        print(r.render(), end="\n\n")
    for r in reports:
        print(r.summary())
    return 0


if __name__ == "__main__":   # python -m legal_agent.evaluation.judgment_qa
    raise SystemExit(main())
