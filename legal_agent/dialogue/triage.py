"""Stage 1 — Triage (spec §3.2). Rule-based v1: NO retrieval, NO LLM.

Coarse-classify the opening complaint by keyword rules into `noise` (the only
built scenario) vs. `other` (leak / threat / pets / odor / space -> generic flow
not built yet) vs. `ambiguous` (e.g. "我有惡鄰居" -> ask a discriminating
question instead of answering). The LLM classifier is a later step.
"""
from __future__ import annotations

from dataclasses import dataclass

# One discriminating question (spec §3.2) for vague openings. Corpus v2 covers
# far more than neighbour disputes — the options must not suggest otherwise.
DISCRIMINATING_QUESTION = (
    "可以多說一點嗎?例如:這是租屋、勞資、消費、車禍、家事,"
    "還是鄰里(噪音/漏水)類的問題?發生了什麼事?"
)

# Keyword rules (lowercased; Chinese is unaffected by lower()). Noise is checked
# FIRST because it is the built scenario (e.g. 狗吠/很吵 -> noise, not pets).
_NOISE = [
    "噪音", "吵", "大聲", "喧嘩", "喧囂", "吠", "狗叫", "音響", "卡拉ok", "ktv",
    "深夜", "半夜", "三更", "施工", "裝修", "分貝", "低頻", "震動", "擾人", "安寧",
    "聲音", "腳步", "拖家具", "喇叭", "重低音", "打鼓", "樂器",
]
_OTHER = [
    ("leak", "漏水", ["漏水", "滲水", "壁癌", "水管", "天花板"]),
    ("threat", "言語衝突/恐嚇", ["恐嚇", "威脅", "辱罵", "謾罵", "挑釁", "衝突", "罵", "嗆"]),
    ("pets", "寵物", ["寵物", "養狗", "養貓", "放養", "糞便", "便溺", "貓砂"]),
    ("odor", "氣味", ["異味", "惡臭", "臭味", "油煙", "菸味", "煙味", "味道", "燒香"]),
    ("space", "占用空間", ["占用", "佔用", "堆放", "堆置", "侵占", "停車", "雜物", "擋住", "通道"]),
]


@dataclass(frozen=True)
class TriageResult:
    kind: str                     # "noise" | "other" | "ambiguous"
    problem_type: str | None      # "noise" | f"other:{cat}" | None
    question: str | None = None   # discriminating question (ambiguous case)
    message: str | None = None    # generic-not-built notice (other case)


def _hits(low: str, keywords: list[str]) -> bool:
    return any(kw in low for kw in keywords)


def classify(message: str) -> TriageResult:
    """Coarse-classify the opening complaint. NO retrieval, NO LLM."""
    low = (message or "").lower()
    if _hits(low, _NOISE):
        return TriageResult("noise", "noise")
    for cat, label, keywords in _OTHER:
        if _hits(low, keywords):
            return TriageResult(
                "other", f"other:{cat}",
                message=(
                    f"你描述的比較像「{label}」問題。目前僅建置「住宅噪音」情境,"
                    "其他鄰里糾紛的通用流程尚未建立(後續步驟)。"
                ),
            )
    return TriageResult("ambiguous", None, question=DISCRIMINATING_QUESTION)
