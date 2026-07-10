"""Ablation — the same questions asked BARE (model answers from memory) vs
GATED (full five-gate pipeline), per local model. Produces the project's
headline numbers (SPEC §2.1: "when it errs, the user knows").

Conditions
    bare   the golden question is sent straight to the model, which is asked to
           cite the statutes it believes apply — no retrieval, no rules. Every
           citation is then checked against the corpus. This measures how many
           memory-cited statutes are UNVERIFIABLE (the user would have to trust
           them blindly).
    gated  the full pipeline (retrieval-first prompt -> honesty tier ->
           verifier -> sections -> premise check). Citations the model
           over-reaches on are FLAGGED to the user.

Closed-world caveat (stated wherever numbers are shown): the corpus is the
11-entry hand-verified noise corpus, so "unverifiable" means NOT TRACEABLE to
the corpus — the system's actual promise — not "fabricated in the real world".

Reasoning models (deepseek-r1, qwen3) emit <think>…</think>; it is stripped
before verification so citations inside chain-of-thought don't count.

Run:  python -m legal_agent.evaluation.ablation evals/golden_noise_v1.json \
          --models llama3.1:latest qwen3:latest --out evals/ablation_raw.json
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from legal_agent.anti_hallucination.verifier import VerificationResult, verify_answer
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
    def from_verifications(vs: list[VerificationResult]) -> "CitationStats":
        return CitationStats(
            total=len(vs),
            missing=sum(1 for v in vs if not v.exists),
            mismatch=sum(1 for v in vs if v.exists and not v.content_match),
            out_of_force=sum(1 for v in vs if v.exists and not v.in_force),
            flagged=sum(1 for v in vs if v.flagged),
        )

    def __add__(self, other: "CitationStats") -> "CitationStats":
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
            "(unverifiable = 引用無法回溯到 corpus;closed-world,見模組 docstring)",
            "",
            f"{'model':<20}{'cond.':<7}{'citations':<10}{'corpus查無':<10}"
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
) -> AblationReport:
    """Run every golden case through both conditions for each model.

    llm_factory(model_name) -> str->str callable; defaults to the local Ollama
    backend (generous timeout — reasoning models think for minutes). Tests
    inject a fake factory (no network).

    Resilient by design: a case-run that raises (Ollama restart, VRAM swap,
    timeout) is retried once, then recorded as an "[ERROR] …" run and skipped
    in aggregates — one dead generation must not lose the batch. When
    `checkpoint_path` is set the report JSON is rewritten after every model.
    """
    if llm_factory is None:
        from legal_agent.dialogue.ollama_llm import ollama_llm

        llm_factory = lambda m: ollama_llm(model=m, timeout=600.0)  # noqa: E731

    own = None
    if conn is None:
        from legal_agent.config import DB_PATH
        from legal_agent.data.database import connect

        own = connect(DB_PATH)
        conn = own

    cases = load_golden_set(golden_path)
    if limit is not None:
        cases = cases[:limit]

    report = AblationReport()
    try:
        for model in models:
            llm = llm_factory(model)
            for i, case in enumerate(cases, 1):
                for runner, condition in ((_run_bare, "bare"), (_run_gated, "gated")):
                    run = None
                    for attempt in (1, 2):
                        try:
                            run = runner(case, llm, conn)
                            break
                        except Exception as exc:  # noqa: BLE001 — record & continue; see docstring
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
    finally:
        if own is not None:
            own.close()
    return report


if __name__ == "__main__":  # python -m legal_agent.evaluation.ablation <golden.json>
    import argparse

    from legal_agent import config

    parser = argparse.ArgumentParser(description="bare vs gated ablation (local models)")
    parser.add_argument("golden", help="golden-set JSON path")
    parser.add_argument("--models", nargs="+", default=[config.OLLAMA_MODEL])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None, help="write per-run JSON here")
    args = parser.parse_args()

    rep = run_ablation(
        args.golden, models=args.models, limit=args.limit,
        on_progress=lambda msg: print(msg, flush=True),
        checkpoint_path=args.out,
    )
    print(rep.render())
    if args.out:
        rep.to_json(args.out)
        print(f"raw runs -> {args.out}")
