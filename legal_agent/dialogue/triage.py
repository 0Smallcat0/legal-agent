"""Stage 1 — Triage (spec §3.2). Rule-based: NO retrieval, NO LLM.

Coarse-classify the opening complaint by keyword rules into `noise` (the one
scenario with a hand-built checklist and ladder), `other:<domain>` (personal
safety, rent / labor / consumer / traffic / family, neighbour leak / threat /
pets / odor / space — all served by the generic flow), or `ambiguous` (e.g.
"我有惡鄰居" -> ask one discriminating question instead of answering). Both
intake paths, including the model-driven one, classify with these rules.

Also infers which side of the complaint the user is on (`classify_stance`).
"""
from __future__ import annotations

import re
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
    # People report the BEHAVIOUR, not the word 「噪音」 (「樓上小孩跑跳、拖椅子」).
    "跑跳", "跑來跑去", "拖椅子", "拖桌", "蹦蹦", "砰砰", "哭鬧", "尖叫",
    "打球", "跳繩", "甩門", "摔門", "彈鋼琴", "唱歌",
]
# Personal-safety complaints are checked BEFORE noise, and that ordering is the
# whole point: 「前男友…半夜按我家電鈴…我很害怕」 hits the noise word 「半夜」, and a
# stalking victim must not get the noise questionnaire.
# HARM words only. Relationship words (前夫/前妻/前男友/分手) misfire — a divorced
# father asking about visitation is not a safety case.
_SAFETY = [
    "家暴", "暴力", "打我", "動手", "恐嚇", "威脅", "跟蹤", "騷擾", "糾纏",
    "保護令", "很害怕", "會怕", "性騷", "跟監", "堵我", "等我下班",
    "一直傳訊息", "按我家電鈴",
]

# The everyday domains the corpus covers, plus the neighbour disputes. A plainly
# stated domain must not fall through to 「ambiguous」 and be asked to classify itself.
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


# ── Which side of the complaint the user is on ───────────────────────────────
# The checklists, ladders and letter templates are written for the party MAKING
# the complaint; handed to a respondent they tell him to report himself
# (evals/RESULTS.md §8).
#
# So the seat is inferred where the sentence says it, and ASKED where it does
# not. It is never assumed silently: an assumption nobody states is one the
# reader cannot correct.
STANCE_QUESTION = (
    "先確認一件事,因為它會改變後面每一題的意思:"
    "是別人製造的聲音吵到你,還是有人反映/投訴你這邊太吵?"
)
# The same question outside the noise scenario: the generic ladder is the
# complainant's too (申訴, 檢舉, 申請理賠, 存證信函, 提告).
STANCE_QUESTION_GENERIC = (
    "先確認一件事,因為它會改變後面每一題的意思:"
    "是你要向對方主張什麼,還是對方在向你要求或指控什麼?"
)


def stance_question(problem_type: str | None) -> str:
    return STANCE_QUESTION if problem_type == "noise" else STANCE_QUESTION_GENERIC

# "Someone is complaining about ME." Phrases only — a bare 「我被」 or 「投訴」
# cannot tell the two sides apart, and a wrong stance is worse than no stance.
# 「被鄰居投訴」 does not contain 「被投訴」, so one pattern covers 被X投訴 /
# 被X檢舉 / 被X反映 for any short X, instead of a row per neighbour noun.
_BEING_COMPLAINED_ABOUT = re.compile(
    r"被[^,,。.;;\s]{0,6}?(?:投訴|檢舉|申訴|反映|抗議|舉發|報警)"
)
_RESPONDENT = [
    # Outside the noise scenario the same seat is described differently: the
    # landlord accused of keeping a deposit, the employer under a complaint, the
    # seller a buyer reported, the driver blamed for the crash.
    "告我", "對我提告", "要我賠", "要我付", "要求我賠", "跟我求償", "向我求償",
    "被求償", "說我違約", "指控我", "申訴我", "投訴我的", "客訴我",
    "收到存證信函", "收到律師函", "收到支付命令", "收到通知書", "被申訴",
    "房客說我", "房東說我", "員工說我", "客人說我", "對方說我",
    "投訴我", "檢舉我", "反映我", "抗議我", "說我太吵", "說我很吵", "說我家太吵",
    "說我製造", "嫌我吵", "嫌我太吵", "被投訴", "被檢舉", "被反映", "被抗議",
    "鄰居說我", "樓下說我", "樓上說我", "隔壁說我", "來勸導我", "勸導我",
    "指控我", "怪我", "我被說", "說我這邊",
]
# "The noise is reaching ME." The historical default of this whole path, stated
# explicitly so that 「neither」 becomes a real answer instead of a silent guess.
_COMPLAINANT = [
    "吵到我", "吵得我", "很吵", "太吵", "受不了", "睡不著", "睡不好", "失眠",
    "影響我", "干擾我", "擾人", "妨害我", "對方", "鄰居", "樓上", "樓下",
    "隔壁", "他們", "對面",
    # Outside the noise scenario, 「X 沒有對我做 Y」 is how a claimant states it.
    # Without these rows almost every rent/labour/consumer session would fall to
    # None and be asked a question its own sentence already answered.
    "不還我", "不讓我", "不給我", "沒還我", "沒給我", "沒付我", "欠我",
    "不處理", "不修", "不退", "拒絕", "我要退", "想拿回", "跟我要",
]


def classify_stance(message: str) -> str | None:
    """「respondent」 / 「complainant」 / None — None means ASK, never assume.

    Respondent is checked FIRST and wins a tie: 「鄰居說我太吵」 carries 鄰居 and
    說我太吵 at once, and the complainant list is deliberately the looser of the
    two because it is the seat this whole path was built in.
    """
    low = (message or "").lower()
    if _BEING_COMPLAINED_ABOUT.search(low) or _hits(low, _RESPONDENT):
        return "respondent"
    if _hits(low, _COMPLAINANT):
        return "complainant"
    return None


STANCE_LABELS = {
    "respondent": "被投訴的一方",
    "complainant": "提出投訴的一方",
}
# The parenthetical names the dispute, so it only fits a noise case: a
# landlord accused over a deposit is not 「你這邊太吵」.
_NOISE_STANCE_DETAIL = {
    "respondent": "(有人反映你這邊太吵)",
    "complainant": "(別人的聲音吵到你)",
}


def stance_line(stance: str | None, problem_type: str | None = None) -> str:
    """The one visible line that makes the system's assumption correctable.

    Silence reads as endorsement — the same lesson the verification section
    learned when it rendered only on a flag.
    """
    if stance not in STANCE_LABELS:
        return (
            "【本次假設】還沒確認你是哪一方,下面預設你是提出投訴的一方;"
            "若相反請說一句,我改。"
        )
    is_noise = (problem_type or "").split(":")[-1] == "noise"
    detail = _NOISE_STANCE_DETAIL[stance] if is_noise else ""
    return f"【本次假設】你是{STANCE_LABELS[stance]}{detail}。如果反了,直接說一句,我改。"


@dataclass(frozen=True)
class TriageResult:
    kind: str                     # "noise" | "other" | "ambiguous"
    problem_type: str | None      # "noise" | f"other:{cat}" | None
    question: str | None = None   # discriminating question (ambiguous case)
    label: str | None = None      # 「租屋」「勞資」… — for a human one-liner
    message: str | None = None    # said only when it carries something ACTIONABLE
    # True when the message must be said IMMEDIATELY, before any intake — the
    # personal-safety route carries the 110 / 113 pointer. A domain notice
    # (「聽起來像租屋問題」) is useful in a UI that shows it, and noise in a CLI
    # where the assistant is about to reply naturally anyway.
    urgent: bool = False


def _hits(low: str, keywords: list[str]) -> bool:
    return any(kw in low for kw in keywords)


def classify(message: str) -> TriageResult:
    """Coarse-classify the opening complaint. NO retrieval, NO LLM."""
    low = (message or "").lower()
    if _hits(low, _SAFETY):
        return TriageResult(
            "other", "other:safety", label="人身安全",
            message=(
                "先講最要緊的:如果現在有危險,請直接撥 110;"
                "親密關係或家庭暴力可撥 113,或聯繫當地家庭暴力防治中心。"
            ),
            urgent=True,
        )
    if _hits(low, _NOISE):
        return TriageResult("noise", "noise")
    for cat, label, keywords in _OTHER:
        if _hits(low, keywords):
            # No message: the dialogue layer acknowledges the domain in one line,
            # without explaining the system's own plumbing.
            return TriageResult("other", f"other:{cat}", label=label)
    return TriageResult("ambiguous", None, question=DISCRIMINATING_QUESTION)
