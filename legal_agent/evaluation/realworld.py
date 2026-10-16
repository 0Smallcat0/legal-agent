"""Retrieval and refusal, scored against disputes that already ENDED (spec §4.2).

Every other harness in this project grades the system against expectations this
project wrote. That is a closed loop: the same hand that built the retriever
decided which article should have surfaced. This one closes a different loop —
the cases come from government dispute-resolution case tables, and the article
each case turns on is the one the deciding body ITSELF cited in its 法令依據
column. Nobody here chose it.

Two numbers come out, and they answer the two halves of the real question a
person has before deciding whether to pay a lawyer:

  * hit@k  — did the article the authority actually applied reach the window
             the model may cite from?
  * refusal — when it did NOT, did the system say so, or answer anyway?

What this refuses to measure: whether the ANSWER's reasoning matches what
actually happened. `--answers` prints the model's 分析研判 beside the recorded
outcome for a human to compare, and never scores it — the same refusal
golden_set.py makes about legal correctness. A harness that auto-graded legal
reasoning would be the exact sin this project exists to avoid.

Label provenance is tracked and NOT pooled. Cases whose source table published
its own 法令依據 are `official`; cases where this project inferred the article
from a narrative outcome are `derived` and are reported separately, because a
number is only as external as its weakest label.

Run:  python -m legal_agent.evaluation.realworld [evals/realworld_v1.json]
      python -m legal_agent.evaluation.realworld --answers   # + LLM, human read
      python -m legal_agent.evaluation.realworld --direction # blind-coded direction, no model
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from legal_agent.config import PROJECT_ROOT
from legal_agent.evaluation import corpus_connection

DEFAULT_CASES = PROJECT_ROOT / "evals/realworld_v1.json"
# The answer-side coding for one recorded run: separate because it belongs to
# one model at one temperature, while the outcome side belongs to the case.
DEFAULT_CODING = PROJECT_ROOT / "evals/realworld_answer_coding_run1.json"


@dataclass
class CaseOutcome:
    id: str
    domain: str
    label_source: str
    expected: list[str]
    hit: list[str]
    window: list[str]
    tier: str
    real_outcome: str
    analysis: str | None = None

    @property
    def missed(self) -> list[str]:
        return [e for e in self.expected if e not in self.hit]

    @property
    def refused(self) -> bool:
        return self.tier == "insufficient"

    @property
    def silent_miss(self) -> bool:
        """Missed every governing article AND answered anyway — the shape that
        sends a person into a dispute believing they are covered."""
        return not self.hit and not self.refused


@dataclass
class OutcomeReport:
    cases: list[CaseOutcome]
    dense_fallbacks: int = 0
    sources: list[dict] = field(default_factory=list)

    def subset(self, label_source: str) -> list[CaseOutcome]:
        return [c for c in self.cases if c.label_source == label_source]

    @staticmethod
    def _rate(cases: list[CaseOutcome]) -> tuple[int, int]:
        return (
            sum(len(c.hit) for c in cases),
            sum(len(c.expected) for c in cases),
        )

    def render(self) -> str:
        lines = ["═══════ 真實已結案爭議:檢索與拒答(輸入只有當事人最初陳述) ═══════"]
        for label in ("official", "derived"):
            group = self.subset(label)
            if not group:
                continue
            head = {
                "official": "外部標註(案例表自帶「法令依據」欄)",
                "derived": "本專案反推的標註(僅供參考,不計入 headline)",
            }[label]
            lines.append(f"\n── {head} ── {len(group)} 案")
            for c in group:
                flag = "拒答" if c.refused else ("靜默漏接" if c.silent_miss else "    ")
                lines.append(
                    f"\n【{c.id}】{len(c.hit)}/{len(c.expected)} tier={c.tier} {flag}"
                )
                for ref in c.expected:
                    lines.append(f"   {'HIT ' if ref in c.hit else 'MISS'} {ref}")
                if c.analysis is not None:
                    lines.append(f"   [模型分析] {c.analysis.strip()[:200]}")
                    lines.append(f"   [真實結局] {c.real_outcome[:200]}")
            hit, total = self._rate(group)
            refused = sum(1 for c in group if c.refused)
            silent = sum(1 for c in group if c.silent_miss)
            pct = f"{hit / total:.0%}" if total else "n/a"
            lines.append(
                f"\n   hit@k {hit}/{total}({pct})"
                f" · 拒答 {refused}/{len(group)}"
                f" · 靜默漏接 {silent}/{len(group)}"
            )
        lines.append("")
        lines.append(
            "hit@k 量的是「權責機關實際引用的條文有沒有進入模型可引用的窗口」。"
            "靜默漏接 = 一條都沒命中卻照樣作答,是這裡最該看的數字。"
        )
        lines.append(
            "本 harness 不自動評分法律推論是否正確 —— --answers 只把分析與真實結局"
            "並排印出來給人讀,與 golden_set 對法律正確性的拒絕相同。"
        )
        if self.dense_fallbacks:
            lines.append(
                f"⚠ 這個數字不是混合檢索的:{self.dense_fallbacks}/{len(self.cases)} "
                "個查詢的 dense 半邊失敗並退回純 BM25(Ollama 未載入 bge-m3?)。"
            )
        else:
            lines.append("dense 全程參與(0 次退回),此數可與已發布數字相比。")
        for src in self.sources:
            lines.append(f"來源[{src.get('label_source')}] {src.get('title')} — {src.get('url')}")
        return "\n".join(lines)


def load_document(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ref(entry: dict) -> str:
    return f"{entry['statute_id']}{entry['article_no']}"


class BadLabelError(ValueError):
    """A governing article does not exist in the corpus under that name."""


# ── direction: does the answer point the same way the case actually ended? ───
# hit@k says the right article reached the window, not which way the answer
# then argued; the verification axes certify a cited article is real, never
# that it points your way (RESULTS.md has the measured runs). This counts
# direction WITHOUT auto-grading legal reasoning: neither coding pass may see
# the other side:
#
#   1. the outcome fields are coded from the case record, never from an answer;
#   2. the answer fields are coded from the generated text alone, by someone who
#      has not read the outcome — hence `evals/realworld_answers_run*.json`,
#      which deliberately carries no `real_outcome`;
#   3. the comparison is arithmetic.
#
# Nobody is asked whether they AGREE with an answer; both sides use the same
# closed vocabulary and the counting is deterministic.
#
# 「asker」 is whoever wrote `initial_text`; 「other_party」 is whoever they are up
# against. 「unclear」 is a real answer and must stay available — forcing a coder
# to pick a side when the text does not commit is how a coding scheme starts
# manufacturing the number it was built to measure.
#
# `favours`     — which side the text says the law backs, read as written. An
#                 answer that opens 「對方的說法站不住腳」 is coded `asker` even
#                 where the reasoning under it wanders, because a reader takes
#                 the conclusion.
# `money_to_asker` — does the asker end up BETTER OFF in money. Being relieved
#                 of a charge counts as `yes`; it is the same pocket. Written
#                 down here because a rule applied differently on the two sides
#                 would produce a disagreement that is purely the coder's.
FAVOURS_VALUES = frozenset({"asker", "other_party", "split", "unclear"})
MONEY_VALUES = frozenset({"yes", "no", "partial", "not_at_issue", "unclear"})
DIRECTION_FIELDS = (("favours", FAVOURS_VALUES), ("money_to_asker", MONEY_VALUES))


@dataclass(frozen=True)
class DirectionCoding:
    favours: str
    money_to_asker: str
    coded_from: str = ""        # the span the coder rested on, so it is checkable

    @classmethod
    def from_dict(cls, raw: dict) -> DirectionCoding:
        return cls(
            favours=raw["favours"],
            money_to_asker=raw["money_to_asker"],
            coded_from=raw.get("coded_from", ""),
        )


@dataclass(frozen=True)
class DirectionMatch:
    id: str
    label_source: str
    outcome: DirectionCoding
    answer: DirectionCoding

    @property
    def committed(self) -> bool:
        """Both sides named a side. 「unclear」 on either side is not a
        disagreement and must not be counted as one."""
        return "unclear" not in (self.outcome.favours, self.answer.favours)

    @property
    def agrees(self) -> bool:
        return self.committed and self.outcome.favours == self.answer.favours

    @property
    def opposed(self) -> bool:
        """The shape that sends a person into a dispute pointed the wrong way:
        one side says the asker, the other says the party opposite them.
        「split」 against either is a partial mismatch, not an inversion."""
        return {self.outcome.favours, self.answer.favours} == {"asker", "other_party"}


def check_direction_labels(document: dict, coding: dict) -> None:
    """Every coded value must be inside its vocabulary, or abort the whole run.

    Same rule and same reason as `check_labels`: a value outside the closed set
    is a ruler nobody calibrated, and it renders as a confident count rather
    than as an error. A case coded on one side only is the same failure — the
    comparison would silently drop it and the denominator would move without
    anyone deciding that it should.
    """
    bad: list[str] = []
    coded_ids = set(coding)
    known_ids = {case["id"] for case in document["cases"]}
    for unknown in sorted(coded_ids - known_ids):
        bad.append(f"{unknown}:答案編碼指向不存在的案件 id")
    for case in document["cases"]:
        sides = {
            "結局": case.get("outcome_direction"),
            "答案": coding.get(case["id"]),
        }
        present = [name for name, value in sides.items() if value]
        if len(present) == 1:
            bad.append(f"{case['id']}:只編了{present[0]}一邊,比對會靜默少算")
        for name, value in sides.items():
            if not value:
                continue
            for field_name, allowed in DIRECTION_FIELDS:
                got = value.get(field_name)
                if got not in allowed:
                    bad.append(
                        f"{case['id']}.{name}.{field_name}={got!r}"
                        f"(允許:{'/'.join(sorted(allowed))})"
                    )
    if bad:
        raise BadLabelError(
            "方向編碼的值域不合法,計數會是假的,先修編碼:\n  " + "\n  ".join(bad)
        )


def load_direction_coding(path) -> dict:
    """The answer-side coding for ONE run. Empty when the file is absent."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("coding", {})


def compare_directions(document: dict, coding: dict) -> list[DirectionMatch]:
    """Pair the two blind codings. Value domains are gated first."""
    check_direction_labels(document, coding)
    matches = []
    for case in document["cases"]:
        outcome, answer = case.get("outcome_direction"), coding.get(case["id"])
        if not outcome or not answer:
            continue
        matches.append(DirectionMatch(
            id=case["id"],
            label_source=case.get("label_source", "derived"),
            outcome=DirectionCoding.from_dict(outcome),
            answer=DirectionCoding.from_dict(answer),
        ))
    return matches


def render_directions(matches: list[DirectionMatch], run: dict | None = None) -> str:
    """Counts, pooled by `label_source` — a number is only as external as its
    weakest label, and that rule does not stop applying at the outcome field."""
    lines = ["═══════ 推論方向 vs 已記錄結局(兩邊皆盲編碼,比對為程式) ═══════"]
    if run:
        lines.append(
            f"answers: model={run.get('model')} temperature={run.get('temperature')}"
        )
    if not matches:
        lines.append("尚未編碼:結局欄或答案編碼缺一,方向數字不存在。")
        return "\n".join(lines)
    for label in ("official", "derived"):
        group = [m for m in matches if m.label_source == label]
        if not group:
            continue
        head = {
            "official": "外部標註(案例表自帶「法令依據」欄)",
            "derived": "本專案反推的標註(僅供參考,不計入 headline)",
        }[label]
        lines.append(f"\n── {head} ── {len(group)} 案")
        for m in group:
            mark = "同向" if m.agrees else ("相反" if m.opposed else "不一致")
            if not m.committed:
                mark = "未表態"
            lines.append(
                f"  {mark}  {m.id[:32]:32s} 結局={m.outcome.favours:12s}"
                f" 答案={m.answer.favours:12s}"
                f" 錢給提問者 結局={m.outcome.money_to_asker}/答案={m.answer.money_to_asker}"
            )
        committed = [m for m in group if m.committed]
        agree = sum(1 for m in committed if m.agrees)
        opposed = sum(1 for m in group if m.opposed)
        lines.append(
            f"\n   同向 {agree}/{len(committed)} · 相反 {opposed}/{len(group)}"
            f" · 至少一邊未表態 {len(group) - len(committed)}/{len(group)}"
        )
    lines += [
        "",
        "相反 = 結局說一方、答案說另一方。這是最該看的數字:一個把人指向反方向的"
        "答案,四個查核軸全綠也攔不住,因為它們認證的是被引用的條文為真,不是這條"
        "管你的事。",
        "兩邊編碼都是盲的:結局欄從案件記錄編、不看答案;答案欄只讀生成文字、不看"
        "結局。沒有人被問過「同不同意」,比對是確定性的。",
    ]
    return "\n".join(lines)


def check_labels(document: dict, conn) -> None:
    """Every governing article must exist in the corpus, or the whole run is a
    bad ruler: a label the corpus can never match scores 0 no matter how good
    retrieval is, and the harness would report a confident wrong miss
    (RESULTS.md records the 「中華民國民法」 mislabel that once did).
    """
    rows = {
        f"{sid}{ano}"
        for sid, ano in conn.execute("SELECT statute_id, article_no FROM statutes")
    }
    unknown = sorted({
        _ref(entry)
        for case in document["cases"]
        for entry in case["governing_statutes"]
        if _ref(entry) not in rows
    })
    if unknown:
        raise BadLabelError(
            "這些標註的條文不存在於 corpus,分數會是假的 miss,先修標註或補語料:"
            + "、".join(unknown)
        )


def run_realworld(path=DEFAULT_CASES, conn=None, k: int | None = None,
                  llm=None) -> OutcomeReport:
    """Retrieve for every case, grade the honesty tier, and score hit@k against
    the article the deciding authority cited. `llm` is optional and only feeds
    the side-by-side print — it never affects a score."""
    from legal_agent.anti_hallucination.honesty import grade_honesty, lexicon_hit
    from legal_agent.retrieval.retriever import (
        DEFAULT_K,
        dense_fallback_count,
        reset_dense_fallbacks,
        retrieve_scored,
    )

    reset_dense_fallbacks()
    document = load_document(path)
    with corpus_connection(conn) as conn:
        check_labels(document, conn)
        results = []
        for case in document["cases"]:
            query = case["initial_text"]
            scored = retrieve_scored(query, k=k or DEFAULT_K, conn=conn)
            retrieved = [s for s, _ in scored]
            scores = [sc for _, sc in scored]
            window = [f"{s.statute_id}{s.article_no}" for s in retrieved]
            tier = grade_honesty(
                retrieved, scores, lexicon_hit=lexicon_hit(retrieved, query), query=query,
            )
            expected = [_ref(e) for e in case["governing_statutes"]]
            analysis = None
            if llm is not None:
                from legal_agent.dialogue.stage3 import run_stage3

                stage3 = run_stage3({"problem": query}, llm=llm, conn=conn,
                                    user_text=query)
                analysis = stage3.analysis_section or stage3.answer
            results.append(CaseOutcome(
                id=case["id"],
                domain=case.get("domain", ""),
                label_source=case.get("label_source", "derived"),
                expected=expected,
                hit=[e for e in expected if e in window],
                window=window,
                tier=tier,
                real_outcome=case["real_outcome"],
                analysis=analysis,
            ))
    return OutcomeReport(
        results,
        dense_fallbacks=dense_fallback_count(),
        sources=document.get("sources", []),
    )


if __name__ == "__main__":   # python -m legal_agent.evaluation.realworld [path]
    import sys as _sys

    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    print_corpus_fingerprint()
    flags = {"--answers", "--direction"}
    argv = [a for a in _sys.argv[1:] if a not in flags]
    want_answers = "--answers" in _sys.argv[1:]
    want_direction = "--direction" in _sys.argv[1:]
    target = argv[0] if argv else DEFAULT_CASES
    if want_direction:
        # Deterministic, no model: both codings are already on disk.
        _doc = load_document(target)
        _coding_file = Path(DEFAULT_CODING)
        _raw = (
            json.loads(_coding_file.read_text(encoding="utf-8"))
            if _coding_file.exists() else {}
        )
        print(render_directions(
            compare_directions(_doc, _raw.get("coding", {})), run=_raw.get("run"),
        ))
        raise SystemExit(0)
    runtime_llm = None
    if want_answers:
        from legal_agent.run import build_runtime_llm

        runtime_llm = build_runtime_llm()
    print(run_realworld(target, llm=runtime_llm).render())
