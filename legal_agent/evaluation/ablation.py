"""Ablation — the same questions asked BARE (model answers from memory) vs
GATED (full five-gate pipeline), per local model. Calls a real model, so it
is not deterministic.

Conditions
    bare   the golden question is sent straight to the model, which is asked to
           cite the statutes it believes apply — no retrieval, no rules. Every
           citation is then checked against the corpus. This measures how many
           memory-cited statutes are UNVERIFIABLE (the user would have to trust
           them blindly).
    gated  the full pipeline (retrieval-first prompt -> honesty tier ->
           verifier -> sections -> premise check). Citations the model
           over-reaches on are FLAGGED to the user.

Closed-world caveat (stated wherever numbers are shown): "unverifiable" means
NOT TRACEABLE to the corpus — the system's actual promise — not "fabricated in
the real world".

The 未回溯 column is NOT comparable across rows: bare verifies with conn= and
an empty window (baseline = the whole corpus); gated inherits run_stage3's
corpus_conn= call (baseline = the retrieved window, so an existing but
unretrieved article lands there and is correctly not flagged). Only
`flagged` is measured identically in both.

Reasoning models (deepseek-r1, qwen3) emit <think>…</think>; it is stripped
before verification so citations inside chain-of-thought don't count.

Run:  python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json \
          --models llama3.1:latest qwen3:latest --out evals/ablation_raw.json
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from legal_agent.anti_hallucination.verifier import VerificationResult, verify_answer
from legal_agent.evaluation import corpus_connection
from legal_agent.evaluation.golden_set import load_golden_set

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

BARE_PROMPT = (
    "你是協助理解台灣法律的助理。請針對以下問題,說明可行的法律途徑,"
    "並引用你認為適用的具體法條(標明法規名稱與條號):\n\n{question}"
)


def strip_think(text: str) -> str:
    """Remove <think>…</think> chain-of-thought blocks (reasoning models)."""
    return _THINK_RE.sub("", text or "").strip()


@dataclass(frozen=True)
class CitationStats:
    total: int = 0
    missing: int = 0          # exists == False (corpus 查無)
    mismatch: int = 0         # exists but content_match == False
    out_of_force: int = 0     # exists but in_force == False
    flagged: int = 0          # any failure -> surfaced to the user

    @staticmethod
    def from_verifications(vs: list[VerificationResult]) -> CitationStats:
        return CitationStats(
            total=len(vs),
            missing=sum(1 for v in vs if not v.exists),
            mismatch=sum(1 for v in vs if v.exists and not v.content_match),
            out_of_force=sum(1 for v in vs if v.exists and not v.in_force),
            flagged=sum(1 for v in vs if v.flagged),
        )

    def __add__(self, other: CitationStats) -> CitationStats:
        return CitationStats(
            self.total + other.total,
            self.missing + other.missing,
            self.mismatch + other.mismatch,
            self.out_of_force + other.out_of_force,
            self.flagged + other.flagged,
        )


@dataclass(frozen=True)
class CaseRun:
    case_id: str
    model: str
    condition: str                    # "bare" | "gated"
    answer: str
    stats: CitationStats
    honesty_tier: str | None = None   # gated only
    flagged_count: int = 0


@dataclass
class AblationReport:
    runs: list[CaseRun] = field(default_factory=list)
    errors: int = 0     # case-runs that raised (model/server died); recorded, not counted

    def aggregate(self, model: str, condition: str) -> CitationStats:
        agg = CitationStats()
        for r in self.runs:
            if r.model == model and r.condition == condition and not r.answer.startswith("[ERROR]"):
                agg = agg + r.stats
        return agg

    def tier_distribution(self, model: str) -> dict[str, int]:
        dist: dict[str, int] = {}
        for r in self.runs:
            if r.model == model and r.condition == "gated" and r.honesty_tier:
                dist[r.honesty_tier] = dist.get(r.honesty_tier, 0) + 1
        return dist

    @property
    def models(self) -> list[str]:
        seen: list[str] = []
        for r in self.runs:
            if r.model not in seen:
                seen.append(r.model)
        return seen

    def render(self) -> str:
        lines = [
            "═══════ Ablation:bare(憑記憶引用) vs gated(五閘門) ═══════",
            "(closed-world:「回溯」= 追得到來源,不等於真實世界不存在;見模組 docstring)",
            "* 未回溯的比較基準兩列不同 —— bare 對「整個語料庫」,gated 對"
            "「這次的檢索視窗」。只有 flagged 兩列同義,可直接相比。",
            "",
            # 未回溯* differs in baseline per row; see module docstring.
            f"{'model':<20}{'cond.':<7}{'citations':<10}{'未回溯*':<10}"
            f"{'金額不符':<9}{'非現行':<8}{'flagged'}",
        ]
        for model in self.models:
            for condition in ("bare", "gated"):
                s = self.aggregate(model, condition)
                rate = f"{(s.flagged / s.total):.0%}" if s.total else "—"
                lines.append(
                    f"{model:<20}{condition:<7}{s.total:<10}{s.missing:<10}"
                    f"{s.mismatch:<9}{s.out_of_force:<8}{s.flagged}({rate})"
                )
            dist = self.tier_distribution(model)
            if dist:
                pretty = "、".join(f"{k}:{v}" for k, v in sorted(dist.items()))
                lines.append(f"{'':<20}gated 誠實分級分佈 -> {pretty}")
        lines.append("")
        if self.errors:
            lines.append(f"⚠ {self.errors} 個 case-run 因模型/伺服器錯誤未計入(見 raw JSON 的 [ERROR] 列)。")
        lines.append(
            "解讀:bare 的 flagged 率=使用者只能盲信的引用比例;"
            "gated 下每一筆引用都被查核,flagged 者附條文原文警示。"
        )
        return "\n".join(lines)

    def to_json(self, path: str | Path) -> None:
        payload = [asdict(r) for r in self.runs]
        Path(path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _run_bare(case: dict, llm: Callable[[str], str], conn) -> CaseRun:
    answer = strip_think(llm(BARE_PROMPT.format(question=case["question"])))
    vs = verify_answer(answer, [], as_of_date=case.get("as_of_date"), conn=conn)
    return CaseRun(
        case_id=case.get("id", ""), model="", condition="bare",
        answer=answer, stats=CitationStats.from_verifications(vs),
        flagged_count=sum(1 for v in vs if v.flagged),
    )


def _run_gated(case: dict, llm: Callable[[str], str], conn) -> CaseRun:
    from legal_agent.dialogue.flow import SessionState, Stage, advance_to_stage3

    state = SessionState(
        stage=Stage.READY_FOR_STAGE3,
        collected_facts=dict(case.get("facts", {})),
        user_text=case.get("question"),
    )
    result = advance_to_stage3(
        state, llm=lambda p: strip_think(llm(p)),
        as_of_date=case.get("as_of_date"), conn=conn,
    )
    return CaseRun(
        case_id=case.get("id", ""), model="", condition="gated",
        answer=result.answer,
        stats=CitationStats.from_verifications(result.verifications),
        honesty_tier=result.honesty_tier,
        flagged_count=result.flagged_count,
    )


def run_ablation(
    golden_path,
    models: list[str],
    llm_factory: Callable[[str], Callable[[str], str]] | None = None,
    conn=None,
    limit: int | None = None,
    on_progress: Callable[[str], None] | None = None,
    checkpoint_path: str | Path | None = None,
    conditions: tuple[str, ...] = ("bare", "gated"),
) -> AblationReport:
    """Run every golden case through both conditions for each model.

    llm_factory(model_name) -> str->str callable; defaults to the local Ollama
    backend (generous timeout — reasoning models think for minutes). Tests
    inject a fake factory (no network).

    Resilient by design: a case-run that raises (Ollama restart, VRAM swap,
    timeout) is retried once, then recorded as an "[ERROR] …" run and skipped
    in aggregates — one dead generation must not lose the batch. When
    `checkpoint_path` is set the report JSON is rewritten after every model.
    `conditions` runs one arm alone, when the other was measured elsewhere
    on the same cases and settings. With `checkpoint_path`, the JSON is also
    rewritten after every case, and a run pointed at an existing file resumes:
    case-runs already there (errors aside) are kept and not asked again — a
    CPU run of one model is hours, and a restarted container must not cost it.
    """
    if llm_factory is None:
        from legal_agent.dialogue.ollama_llm import ollama_llm

        llm_factory = lambda m: ollama_llm(model=m, timeout=600.0)  # noqa: E731


    cases = load_golden_set(golden_path)
    if limit is not None:
        cases = cases[:limit]

    report = AblationReport()
    done: set[tuple[str, str, str]] = set()
    if checkpoint_path is not None and Path(checkpoint_path).exists():
        for run in load_runs(checkpoint_path):
            if run.answer.startswith("[ERROR]"):
                continue
            report.runs.append(run)
            done.add((run.model, run.case_id, run.condition))
    with corpus_connection(conn) as conn:
        for model in models:
            llm = llm_factory(model)
            for i, case in enumerate(cases, 1):
                arms = ((_run_bare, "bare"), (_run_gated, "gated"))
                for runner, condition in (a for a in arms if a[1] in conditions):
                    if (model, case.get("id", ""), condition) in done:
                        continue
                    run = None
                    for attempt in (1, 2):
                        try:
                            run = runner(case, llm, conn)
                            break
                        except Exception as exc:
                            if attempt == 1:
                                time.sleep(10)   # let Ollama recover (model swap / restart)
                                continue
                            report.errors += 1
                            run = CaseRun(
                                case_id=case.get("id", ""), model="", condition=condition,
                                answer=f"[ERROR] {exc}", stats=CitationStats(),
                            )
                    report.runs.append(
                        CaseRun(
                            case_id=run.case_id or case.get("id", ""), model=model,
                            condition=condition, answer=run.answer, stats=run.stats,
                            honesty_tier=run.honesty_tier,
                            flagged_count=run.flagged_count,
                        )
                    )
                if on_progress:
                    on_progress(f"[{model}] {i}/{len(cases)} {case.get('id','')}")
                if checkpoint_path is not None:
                    report.to_json(checkpoint_path)
    return report


# ── What an untraceable bare citation IS, against the national law list ──
# 「Not traceable to the corpus」 mixes a real law the corpus does not hold with
# a law that does not exist. The 全國法規資料庫 open data (law.moj.gov.tw
# /api/Ch/Law/JSON and /api/Ch/Order/JSON, ~11,800 laws and regulations with
# their articles) separates them without anyone's judgement.
_MOJ_ARTICLE_RE = re.compile(r"第(\d+)(?:-(\d+))?條")
BUCKETS = ("corpus verified", "real law, outside corpus", "real law, no such article",
           "no such law")


def load_official(paths) -> dict[str, set[str]]:
    """law name -> its article numbers, in the corpus's 「第15-1條」 form."""
    laws: dict[str, set[str]] = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        for law in data.get("Laws", []):
            numbers = laws.setdefault(law["LawName"], set())
            for article in law.get("LawArticles") or []:
                m = _MOJ_ARTICLE_RE.match((article.get("ArticleNo") or "").replace(" ", ""))
                if m:
                    numbers.add(f"第{m.group(1)}條" if not m.group(2)
                                else f"第{m.group(1)}-{m.group(2)}條")
    return laws


def classify_bare(runs: list[CaseRun], golden_path, official: dict[str, set[str]],
                  conn=None) -> dict[str, dict[str, int]]:
    """model -> bucket -> count, over the bare arm's citations (re-verified)."""
    cases = {c.get("id", ""): c for c in load_golden_set(golden_path)}
    out: dict[str, dict[str, int]] = {}
    with corpus_connection(conn) as conn:
        for run in runs:
            if run.condition != "bare" or run.answer.startswith("[ERROR]"):
                continue
            counts = out.setdefault(run.model, dict.fromkeys(BUCKETS, 0))
            case = cases.get(run.case_id, {})
            for v in verify_answer(run.answer, [], as_of_date=case.get("as_of_date"), conn=conn):
                sid, ano = v.citation.statute_id, v.citation.article_no
                if not v.flagged:
                    counts["corpus verified"] += 1
                elif sid not in official:
                    counts["no such law"] += 1
                elif ano in official[sid]:
                    counts["real law, outside corpus"] += 1
                else:
                    counts["real law, no such article"] += 1
    return out


def load_runs(path) -> list[CaseRun]:
    return [CaseRun(**{**raw, "stats": CitationStats(**raw["stats"])})
            for raw in json.loads(Path(path).read_text(encoding="utf-8"))]


if __name__ == "__main__":  # python -m legal_agent.evaluation.ablation <golden.json>
    from legal_agent.evaluation import enable_utf8_stdout, print_corpus_fingerprint

    enable_utf8_stdout()
    import argparse

    from legal_agent import config

    parser = argparse.ArgumentParser(description="bare vs gated ablation (local models)")
    parser.add_argument("golden", help="golden-set JSON path")
    parser.add_argument("--models", nargs="+", default=[config.OLLAMA_MODEL])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None, help="write per-run JSON here")
    # 0.2 is what the published v2 run used; 0 makes a run repeatable
    # (AGENTS.md trap 3), which is what a delta between models needs.
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--conditions", nargs="+", choices=("bare", "gated"),
                        default=["bare", "gated"])
    parser.add_argument("--official", nargs="+", default=None,
                        help="全國法規資料庫 ChLaw.json/ChOrder.json:把 bare 的未回溯引用分成"
                             "「真實法規、語料外」與「不存在的法規/條號」")
    parser.add_argument("--from-json", default=None,
                        help="不呼叫模型,讀既有的 raw runs JSON(搭配 --official)")
    args = parser.parse_args()
    print_corpus_fingerprint()

    if args.from_json:
        rep = AblationReport(runs=load_runs(args.from_json))
        print(rep.render())
        if args.official:
            for model, counts in classify_bare(rep.runs, args.golden,
                                               load_official(args.official)).items():
                total = sum(counts.values())
                print(f"{model} bare {total} citations: " + ", ".join(
                    f"{k} {n} ({n / total:.0%})" for k, n in counts.items()))
        raise SystemExit(0)

    from legal_agent.dialogue.ollama_llm import ollama_llm

    rep = run_ablation(
        args.golden, models=args.models, limit=args.limit,
        llm_factory=lambda m: ollama_llm(model=m, timeout=1800.0, temperature=args.temperature),
        on_progress=lambda msg: print(msg, flush=True),
        checkpoint_path=args.out, conditions=tuple(args.conditions),
    )
    print(rep.render())
    if args.out:
        rep.to_json(args.out)
        print(f"raw runs -> {args.out}")
