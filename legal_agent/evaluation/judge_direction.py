"""Can an LLM judge catch an answer that points the WRONG WAY? Measured, not shipped.

`realworld --direction` found 5 of 24 answers arguing opposite to how the case
actually ended, with `flagged_count` 0 on every one: the four axes certify that
a cited article is real, never that it points your way. The obvious proposal is
an LLM-as-a-Judge pass over 分析研判. This file measures whether one would have
caught those five before anyone proposes wiring it in. It changes no runtime
path and grades nothing in production — no model grades legal reasoning in
the pipeline; this only produces the number someone would need before deciding
otherwise. `--lexical` scores a no-model control against the same labels.

What each judge sees: the person's opening description and the generated answer,
both taken from `evals/realworld_answers_run1.json`, which deliberately carries
no outcome. It never sees `real_outcome` or `outcome_direction` — a judge
deployed in front of a user would not have them either. Its verdict is then
counted against the blind direction coding that `realworld --direction` already
uses, so the labels are not this harness's:

  * positives — `opposed` (outcome says one side, answer says the other): 5
  * negatives — `agrees` (both committed to the same side): 11
  * the other 8 (`split` against a side, or a non-committal side) are printed
    but enter neither rate; there is no right verdict for them to miss.

Every prompt and every threshold below was written once, before the first run,
and is not tuned on these 24 cases. Tuning a judge on the only labelled set and
then reporting its recall on that set would be the 25/27-vs-52% mistake again
(RESULTS.md §7).

Run:  python -m legal_agent.evaluation.judge_direction            # all judges, 2 passes
      python -m legal_agent.evaluation.judge_direction --report   # re-print the saved run
      python -m legal_agent.evaluation.judge_direction --lexical  # no-model control
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from legal_agent.evaluation.realworld import (
    DEFAULT_CASES,
    DEFAULT_CODING,
    compare_directions,
    load_direction_coding,
    load_document,
)

DEFAULT_ANSWERS = "evals/realworld_answers_run1.json"
DEFAULT_OUT = "evals/judge_direction_run1.json"

# ── prompts, fixed before the first run ──────────────────────────────────────
# The one question the owner asked: 「這段分析的結論方向是否站得住」. Each judge
# gets it in the format it was trained on, because an off-format prompt measures
# the formatting, not the judge.

# Prometheus 2 — its own reference-free absolute template, verbatim from
# prometheus-eval/prompts.py (ABS_SYSTEM_PROMPT + ABSOLUTE_PROMPT_WO_REF). No
# reference answer is passed: the only reference available is the real outcome,
# and a judge given the outcome is not a judge that could run in front of a user.
PROMETHEUS_SYSTEM = (
    "You are a fair judge assistant tasked with providing clear, objective feedback "
    "based on specific criteria, ensuring each assessment reflects the absolute "
    "standards set for performance."
)
PROMETHEUS_TEMPLATE = """###Task Description:
An instruction (might include an Input inside it), a response to evaluate, and a score rubric representing a evaluation criteria are given.
1. Write a detailed feedback that assess the quality of the response strictly based on the given score rubric, not evaluating in general.
2. After writing a feedback, write a score that is an integer between 1 and 5. You should refer to the score rubric.
3. The output format should look as follows: "(write a feedback for criteria) [RESULT] (an integer number between 1 and 5)"
4. Please do not generate any other opening, closing, and explanations.

###The instruction to evaluate:
{instruction}

###Response to evaluate:
{response}

###Score Rubrics:
{rubric}

###Feedback: """
DIRECTION_RUBRIC = """[Is the direction of the response's conclusion legally tenable? Judge only which side the analysis says the law supports and what it tells the person to do — not formatting, length or style.]
Score 1: The conclusion points the wrong way: it backs the side the law does not support, or tells the person to pursue a remedy the cited law does not give them.
Score 2: The conclusion mostly points the wrong way, with only minor correct elements.
Score 3: The direction is mixed or unclear; parts point each way, or the response never commits.
Score 4: The conclusion mostly points the right way, with minor doubtful elements.
Score 5: The conclusion clearly points the way the law supports, and the recommended course of action is one the cited law actually provides."""
INSTRUCTION_TEMPLATE = (
    "以下是一位台灣民眾描述的糾紛。請依台灣法律分析他的處境：他可以主張什麼、"
    "對方的說法站不站得住、接下來該做什麼。\n\n{question}"
)

# JudgeLM — conv_judge_single from baaivision/JudgeLM judgelm/llm_judge/common.py,
# cut to ONE answer. The released single template is the pair template with
# answer 1 pinned at 10 as a reference; there is no reference here (see above),
# so the pair is reduced to one assistant and its 1–10 scale kept. The criterion
# line is the only other change: 「helpfulness, relevance, accuracy, level of
# details」 would grade the answer in general, not the question asked.
JUDGELM_TEMPLATE = (
    "You are a helpful and precise assistant for checking the quality of the answer.\n"
    "[Question]\n{instruction}\n\n"
    "[The Start of Assistant 1's Answer]\n{response}\n\n"
    "[The End of Assistant 1's Answer]\n\n"
    "[System]\nWe would like to request your feedback on the performance of an AI "
    "assistant in response to the user question displayed above.\n"
    "Please rate whether the direction of the answer's conclusion is legally tenable: "
    "does it back the side the law actually supports, and is the course of action it "
    "recommends one the cited law actually provides? Do not rate formatting or style. "
    "The assistant receives a score on a scale of 1 to 10, where a higher score "
    "indicates a more tenable direction.\n"
    "Please first output a single line containing only one value indicating the score "
    "for Assistant 1. In the subsequent line, please provide a comprehensive "
    "explanation of your evaluation.\n\n"
    "### Response:"
)

# A general instruct model as judge — the control. Plain Chinese, one binary
# verdict on the exact question, reasons first so the verdict is not the first
# token it commits to.
PLAIN_TEMPLATE = """你是一位熟悉台灣法律的審稿人。下面是一位民眾描述的糾紛，以及一個法律助理給他的回答。

請只判斷一件事：這段回答的結論方向是否站得住？
「方向」指的是：它說法律站在哪一邊、它叫這個人去做什麼。條文是否存在、格式、文筆都不用管。
方向站不住的例子：法律其實站在對方那邊，回答卻說他有理；或叫他去走一條該條文根本沒有提供的路（例如把警察裁罰的條文說成可以向法院提告）。

【民眾的陳述】
{question}

【法律助理的回答】
{response}

先用兩三句說理由，最後一行只寫「判定：站得住」或「判定：站不住」。"""


@dataclass(frozen=True)
class Judge:
    name: str
    model: str        # Ollama tag
    style: str        # prometheus | judgelm | plain
    num_ctx: int
    note: str = ""


# The two judge models are imported once, from the GGUF files on Hugging Face
# (`ollama pull hf.co/...` stalled at 0 bytes here, so: download, check the
# sha256, then `ollama create <tag> -f Modelfile` with one line `FROM <path>`):
#   prometheus2-7b-judge  prometheus-eval/prometheus-7b-v2.0-GGUF
#                         prometheus-7b-v2.0.Q4_K_M.gguf
#                         sha256 5bb7b0fa6b244a8cad8d2bb29d0f96422c43d3497fe1ab9ced7fd1ead03cc976
#   judgelm-7b-judge      DevQuasar-4/BAAI.JudgeLM-7B-v1.0-GGUF
#                         BAAI.JudgeLM-7B-v1.0.Q4_K_M.gguf
#                         sha256 a6bbd173144ad9bef8709c89c3635f91dfaaeb454695f3de263ad5719b3c7721
JUDGES = (
    Judge("prometheus2-7b", "prometheus2-7b-judge",
          "prometheus", 8192, "official GGUF, Q4_K_M; Mistral-7B base"),
    Judge("judgelm-7b", "judgelm-7b-judge",
          "judgelm", 4096, "community GGUF of BAAI/JudgeLM-7B-v1.0, Q4_K_M; Vicuna/LLaMA-1 base, trained at 2048 ctx"),
    Judge("qwen2.5-7b", "qwen2.5:7b", "plain", 8192,
          "general instruct model as judge (control); same family as the public Space"),
    Judge("llama3.1-8b", "llama3.1:8b", "plain", 8192,
          "the model that WROTE these answers, grading itself"),
)
# PandaLM-7B is not here on purpose: it only compares two responses (output
# 「1」/「2」/「Tie」) and has no single-answer verdict. Pairing each answer with
# an invented opposite would measure the invention.

# Thresholds, fixed with the prompts. Bottom 40% of each scale is a flag.
FLAG_AT_OR_BELOW = {"prometheus": 2, "judgelm": 4}


def build_prompt(judge: Judge, question: str, response: str) -> tuple[str, str | None]:
    """(prompt, system). Only the opening description and the answer go in."""
    if judge.style == "prometheus":
        return PROMETHEUS_TEMPLATE.format(
            instruction=INSTRUCTION_TEMPLATE.format(question=question),
            response=response, rubric=DIRECTION_RUBRIC,
        ), PROMETHEUS_SYSTEM
    if judge.style == "judgelm":
        return JUDGELM_TEMPLATE.format(
            instruction=INSTRUCTION_TEMPLATE.format(question=question), response=response,
        ), None
    return PLAIN_TEMPLATE.format(question=question, response=response), None


_PROM_RESULT = re.compile(r"\[RESULT\]\s*\(?\s*([1-5])\b")
_FIRST_INT = re.compile(r"\b(10|[1-9])\b")
_PLAIN_VERDICT = re.compile(r"判定\s*[:：]\s*(站得住|站不住)")


def parse_verdict(style: str, text: str) -> tuple[bool | None, int | None]:
    """(flagged, score). flagged None = the output could not be read, which is
    counted and printed, never silently folded into 「not flagged」."""
    if style == "prometheus":
        m = _PROM_RESULT.search(text)
        if not m:
            return None, None
        score = int(m.group(1))
        return score <= FLAG_AT_OR_BELOW["prometheus"], score
    if style == "judgelm":
        first = text.strip().splitlines()[0] if text.strip() else ""
        m = _FIRST_INT.search(first)
        if not m:
            return None, None
        score = int(m.group(1))
        return score <= FLAG_AT_OR_BELOW["judgelm"], score
    hits = _PLAIN_VERDICT.findall(text)
    if not hits:
        return None, None
    return hits[-1] == "站不住", None


def _ollama(judge: Judge, prompt: str, system: str | None, host: str,
            timeout: float = 600.0) -> dict:
    options = {"temperature": 0.0, "seed": 0, "num_ctx": judge.num_ctx,
               "num_predict": 1024}
    if judge.style in ("judgelm", "prometheus"):
        # Raw, so the wrapper is exactly the one each model was trained on and
        # not whatever template a GGUF import guessed. JudgeLM: its own flat
        # template, no chat roles. Prometheus 2: the chat_template in
        # prometheus-eval/prometheus-7b-v2.0 tokenizer_config.json (BOS is
        # added by the runtime).
        if judge.style == "prometheus":
            prompt = f" [INST] {system}\n\n{prompt} [/INST]"
        payload = {"model": judge.model, "prompt": prompt, "raw": True,
                   "stream": False, "options": options}
        url = f"{host}/api/generate"
    else:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        payload = {"model": judge.model, "messages": messages, "stream": False,
                   "options": options}
        url = f"{host}/api/chat"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data.get("response") if "response" in data else data.get("message", {}).get("content")
    return {"text": text or "", "prompt_eval_count": data.get("prompt_eval_count"),
            "eval_count": data.get("eval_count"), "done_reason": data.get("done_reason")}


# ── the no-model control: direction words, 主文 against 理由 ─────────────────
# A judgment states its result in 主文 and argues it in 理由; a reversal between
# the two is visible without understanding either. The answers here have the
# same two places, because stage 3's prompt asks the same three questions every
# time (他可以向誰主張什麼 / 對方的說法站不站得住 / 接下來要準備什麼):
#
#   * 主文 — the verdict on the other side's argument: a clause that names 對方
#     (or the asker's own 說法/要求) and says 站得住 / 站不住 or 成立 / 不成立.
#   * 理由 — the claim line: a clause in which the asker 可以 / 得 / 有權 do
#     something (→ the asker) or 無法 / 不能 / 無權 (→ the other party).
#
# Two flag rules, both fixed from the prompt's structure before scoring and not
# tuned on the 24 answers:
#   contradiction — the cues point both ways;
#   no_verdict    — no 主文 at all: the answer never says whose argument holds.
# Like the judges, it reads only the generated answer, never the outcome.

_CLAUSE_SPLIT = re.compile(r"[。；;\n]")
_ECHO = re.compile(r"站不站得住(腳)?")
_REJECTS = re.compile(r"站不住|不成立|無理|不合法|沒有道理")
_HOLDS = re.compile(r"站得住|成立|有理")
_ASKER_SIDE = re.compile(r"(他|你)的(說法|主張|要求)")
_CLAIM_NEG = re.compile(r"(無法|不能|不可以)(向|主張|請求|要求)|無權|沒有權利")
_CLAIM_POS = re.compile(r"(可以|有權)|得(向|主張|請求|要求|終止)")
_CLAIM_SUBJECT = re.compile(r"^\s*(\(?\d\)?[.、]?)?\s*(他|你)")


def direction_cues(text: str) -> dict:
    """{'verdict': [...], 'claim': [...]} — each a list of 'asker'/'other_party'.
    Pure string matching, no model."""
    verdict: list[str] = []
    claim: list[str] = []
    for raw in _CLAUSE_SPLIT.split(text or ""):
        clause = _ECHO.sub("", raw)
        if "對方" in clause:
            if _REJECTS.search(clause):
                verdict.append("asker")
            elif _HOLDS.search(clause):
                verdict.append("other_party")
            continue
        if _ASKER_SIDE.search(clause):
            if _REJECTS.search(clause):
                verdict.append("other_party")
            elif _HOLDS.search(clause):
                verdict.append("asker")
            continue
        if not claim and _CLAIM_SUBJECT.match(clause):
            if _CLAIM_NEG.search(clause):
                claim.append("other_party")
            elif _CLAIM_POS.search(clause):
                claim.append("asker")
    return {"verdict": verdict, "claim": claim}


def lexical_verdicts(answers_path=DEFAULT_ANSWERS) -> dict:
    """The no-model check, in the same shape `run` produces for a judge, so the
    same `render` scores it against the same labels."""
    answers = json.loads(Path(answers_path).read_text(encoding="utf-8"))
    rows = {}
    for case_id, entry in answers.items():
        cues = direction_cues(entry.get("analysis") or entry.get("answer") or "")
        sides = set(cues["verdict"]) | set(cues["claim"])
        contradiction = sides == {"asker", "other_party"}
        no_verdict = not cues["verdict"]
        rows[case_id] = {"cues": cues, "contradiction": contradiction,
                         "no_verdict": no_verdict}
    return rows


def lexical_as_judges(rows: dict) -> dict:
    """Two rules → two pseudo-judges with one deterministic pass each."""
    def as_pass(key):
        return {i: {"flagged": (r["contradiction"] or r["no_verdict"]) if key == "either"
                    else r[key], "score": None} for i, r in rows.items()}
    return {"judges": {
        "lexical:contradiction": {"model": "no model", "style": "lexical", "num_ctx": 0,
                                  "note": "主文/理由 cues point both ways",
                                  "passes": [as_pass("contradiction")]},
        "lexical:contradiction|no_verdict": {"model": "no model", "style": "lexical",
                                             "num_ctx": 0,
                                             "note": "… or no verdict on the other side at all",
                                             "passes": [as_pass("either")]},
    }}


def labels(cases_path=DEFAULT_CASES, coding_path=DEFAULT_CODING) -> dict[str, dict]:
    """id -> {label_source, truth}. truth is 'wrong' (opposed), 'right' (agrees)
    or None (neither) — straight from the blind coding, never from a judge."""
    matches = compare_directions(load_document(cases_path), load_direction_coding(coding_path))
    out = {}
    for m in matches:
        truth = "wrong" if m.opposed else ("right" if m.agrees else None)
        out[m.id] = {"label_source": m.label_source, "truth": truth}
    return out


def run(judges=JUDGES, answers_path=DEFAULT_ANSWERS, repeat: int = 2,
        host: str | None = None) -> dict:
    from legal_agent import config

    host = (host or config.OLLAMA_HOST).rstrip("/")
    answers = json.loads(Path(answers_path).read_text(encoding="utf-8"))
    results: dict = {"judges": {}, "repeat": repeat, "answers_file": answers_path,
                     "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for judge in judges:
        passes = []
        for _ in range(repeat):
            rows = {}
            for case_id, entry in answers.items():
                prompt, system = build_prompt(judge, entry["initial_text"], entry["answer"])
                try:
                    raw = _ollama(judge, prompt, system, host)
                except (urllib.error.URLError, OSError) as exc:
                    raw = {"text": "", "error": str(exc)}
                flagged, score = parse_verdict(judge.style, raw["text"])
                rows[case_id] = {**raw, "flagged": flagged, "score": score}
                print(f"  {judge.name} {case_id} flagged={flagged} score={score}", flush=True)
            passes.append(rows)
        results["judges"][judge.name] = {
            "model": judge.model, "style": judge.style, "num_ctx": judge.num_ctx,
            "note": judge.note, "passes": passes,
        }
    return results


def _count(rows: dict, truth_by_id: dict, truth: str, pool: str | None = None) -> tuple[int, int, int]:
    """(flagged, unreadable, total) over cases whose blind truth is `truth`."""
    ids = [i for i, t in truth_by_id.items()
           if t["truth"] == truth and (pool is None or t["label_source"] == pool)]
    flagged = sum(1 for i in ids if rows[i]["flagged"] is True)
    unreadable = sum(1 for i in ids if rows[i]["flagged"] is None)
    return flagged, unreadable, len(ids)


def render(results: dict, truth_by_id: dict) -> str:
    lines = ["═══════ LLM 評審能不能抓出「推論方向錯」的答案(只量,不上線) ═══════",
             "標籤 = realworld --direction 的盲編碼:相反 → 方向錯;同向 → 方向對;其餘不計。",
             "評審只看當事人陳述與生成答案,看不到真實結局。"]
    for name, j in results["judges"].items():
        lines.append(f"\n── {name}  ({j['model']}, {j['style']}, num_ctx={j['num_ctx']}) ──")
        if j.get("note"):
            lines.append(f"   {j['note']}")
        for p, rows in enumerate(j["passes"], 1):
            caught = _count(rows, truth_by_id, "wrong")
            false = _count(rows, truth_by_id, "right")
            co, cd = (_count(rows, truth_by_id, "wrong", s) for s in ("official", "derived"))
            fo, fd = (_count(rows, truth_by_id, "right", s) for s in ("official", "derived"))
            all_flagged = sum(1 for r in rows.values() if r["flagged"] is True)
            unread = sum(1 for r in rows.values() if r["flagged"] is None)
            lines.append(
                f"   第{p}輪  方向錯抓到 {caught[0]}/{caught[2]}"
                f"(外部 {co[0]}/{co[2]}・推導 {cd[0]}/{cd[2]})"
                f" · 方向對被誤報 {false[0]}/{false[2]}"
                f"(外部 {fo[0]}/{fo[2]}・推導 {fd[0]}/{fd[2]})"
                f" · 24 件共標 {all_flagged} · 讀不出判定 {unread}"
            )
        if len(j["passes"]) > 1:
            first = j["passes"][0]
            diff = [i for i in first
                    if any(p[i]["flagged"] != first[i]["flagged"] for p in j["passes"][1:])]
            lines.append(f"   輪間判定不同:{len(diff)} 件" + (f"({', '.join(diff)})" if diff else ""))
        rows = j["passes"][0]
        for truth, head in (("wrong", "方向錯的 5 件"), ("right", "方向對的 11 件")):
            ids = [i for i, t in truth_by_id.items() if t["truth"] == truth]
            marks = []
            for i in ids:
                r = rows[i]
                v = "標" if r["flagged"] else ("?" if r["flagged"] is None else "—")
                s = f"{r['score']}" if r["score"] is not None else ""
                marks.append(f"{i.split('-')[0]}-{i.split('-')[1]}:{v}{s}")
            lines.append(f"   {head}:" + " ".join(marks))
    lines += [
        "",
        "方向錯 5 件的 flagged_count(現行四軸查核)全是 0 —— 這是評審要贏過的基準。",
        "提示詞與門檻在第一輪前寫定,沒有在這 24 件上調過。",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # python -m legal_agent.evaluation.judge_direction
    import argparse

    from legal_agent.evaluation import enable_utf8_stdout

    enable_utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="re-print the saved run, call no model")
    ap.add_argument("--lexical", action="store_true",
                    help="score the no-model direction-word check, call no model")
    ap.add_argument("--judges", default=",".join(j.name for j in JUDGES))
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    truth = labels()
    if args.lexical:
        print(render(lexical_as_judges(lexical_verdicts()), truth))
        raise SystemExit(0)
    if args.report:
        saved = json.loads(Path(args.out).read_text(encoding="utf-8"))
    else:
        wanted = set(args.judges.split(","))
        fresh = run([j for j in JUDGES if j.name in wanted], repeat=args.repeat)
        # Re-running one judge keeps the others already on disk.
        out = Path(args.out)
        saved = json.loads(out.read_text(encoding="utf-8")) if out.exists() else fresh
        saved["judges"].update(fresh["judges"])
        out.write_text(json.dumps(saved, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    print(render(saved, truth))
