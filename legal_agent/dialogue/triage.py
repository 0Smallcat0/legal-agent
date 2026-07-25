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
    # People report the BEHAVIOUR, not the word 「噪音」. Measured on a lived
    # session: 「樓上小孩每天晚上跑跳到十一二點,還會拖椅子」 — the textbook
    # complaint for the one scenario with a hand-built ladder — classified as
    # ambiguous, so it got the generic flow and never saw 報警/管委會/存證信函.
    "跑跳", "跑來跑去", "拖椅子", "拖桌", "蹦蹦", "砰砰", "哭鬧", "尖叫",
    "打球", "跳繩", "甩門", "摔門", "彈鋼琴", "唱歌",
]
# Personal-safety complaints are checked BEFORE noise, and that ordering is the
# whole point. Measured on a lived session: 「前男友…半夜按我家電鈴,還在我上班的
# 地方等我,我很害怕」 hit the noise keyword 「半夜」, so someone describing being
# stalked was handed the noise questionnaire — 「你住公寓大廈還是透天?」 — and the
# answer came back citing 社維法§72 深夜喧嘩 and the 噪音 routing principle.
_SAFETY = [
    "家暴", "暴力", "打我", "動手", "恐嚇", "威脅", "跟蹤", "騷擾", "糾纏",
    "前男友", "前女友", "前夫", "前妻", "保護令", "很害怕", "會怕", "性騷",
    "跟監", "堵我", "等我下班",
]

# The everyday domains the corpus actually covers. Without these rows the
# rule-based triage knew only 噪音 plus five neighbour disputes, so a plainly
# stated 「退租後房東說牆壁有釘孔要扣我兩個月押金」 fell through to 「ambiguous」 and
# the web demo replied 「這是租屋、勞資、消費、車禍、家事,還是鄰里的問題?」 —
# asking the user to classify what they had just described.
_OTHER = [
    ("rent", "租屋", ["押金", "退租", "房東", "房客", "承租", "租約", "租金",
                     "二房東", "續租", "違約金"]),
    ("labor", "勞資", ["加班", "資遣", "解僱", "薪水", "薪資", "工資", "老闆",
                      "雇主", "勞保", "責任制", "打工", "時薪", "離職"]),
    ("consumer", "消費", ["網購", "退貨", "退款", "賣家", "瑕疵", "蝦皮",
                         "消費", "訂金", "取消訂單"]),
    ("traffic", "車禍", ["車禍", "擦撞", "追撞", "肇事", "強制險", "初判表"]),
    ("family", "家事", ["離婚", "扶養", "監護", "遺產", "繼承", "贍養"]),
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
    if _hits(low, _SAFETY):
        return TriageResult(
            "other", "other:safety",
            message=(
                "你描述的涉及人身安全(騷擾/跟蹤/暴力/恐嚇)。這類問題走通用流程,"
                "不套用噪音問診;如果現在有危險,請直接撥 110,"
                "親密關係暴力可撥 113 或洽家庭暴力防治中心。"
            ),
        )
    if _hits(low, _NOISE):
        return TriageResult("noise", "noise")
    for cat, label, keywords in _OTHER:
        if _hits(low, keywords):
            return TriageResult(
                "other", f"other:{cat}",
                message=(
                    f"你描述的比較像「{label}」問題。「住宅噪音」有專屬問診流程,"
                    "其他問題走通用流程(同一套檢索與五道關卡,語料涵蓋民法、租賃住宅"
                    "條例、消保法、勞基法、道交條例等)。"
                ),
            )
    return TriageResult("ambiguous", None, question=DISCRIMINATING_QUESTION)
