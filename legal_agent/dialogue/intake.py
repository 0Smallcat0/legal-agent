"""Stage 2 — Structured intake (spec §3.2). Pre-designed 住宅噪音 checklist.

NO retrieval, NO LLM — this is the checklist the model-free path walks, and the
field set the model-driven intake (dialogue/smart_intake.py) extracts into. Each
field records a legally-relevant fact plus its rationale (why it matters).
Answers are filed by WHAT THEY SAY when a line unambiguously matches one open
field (route_answer), positionally otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntakeField:
    key: str
    question: str
    rationale: str   # the legal purpose this fact serves


# Batches of 2-3, presented and recorded in this order.
NOISE_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "noise_type",
            "噪音主要是什麼?(腳步/拖家具、深夜喧嘩爭吵、寵物吠叫、音響卡拉OK、裝修施工、冷氣/機械設備)",
            "分辨 社維法§72 / 噪音法§6(近鄰) vs 噪音法§9(特定場所)",
        ),
        IntakeField(
            "timing",
            "大多什麼時段?持續性還是偶發?",
            "深夜喧嘩(§72)、非持續(§6→警察)",
        ),
    ],
    [
        IntakeField(
            "building_type",
            "有管委會的公寓大廈,還是透天/無管委會?",
            "是否走 公寓大廈條例§16/§47",
        ),
        IntakeField(
            "impact",
            "對你的影響?(睡眠/健康/精神困擾,大概多嚴重)",
            "民法§195 情節重大",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有錄音/錄影或其他紀錄?",
            "各路徑的舉證",
        ),
        IntakeField(
            "actions_taken",
            "報過警嗎?反映過管委會/里長?對方知情、溝通過嗎?",
            "決定下一步升級",
        ),
    ],
]

ALL_FIELD_KEYS: list[str] = [f.key for batch in NOISE_CHECKLIST for f in batch]

# Generic fallback checklist (spec §3.4: non-noise problems get a shallower
# flow instead of a dead end). Two batches, four facts — enough for one good
# retrieval query, honest about being thinner than a scenario checklist.
GENERIC_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "problem",
            "發生了什麼事?對方是誰(例:房東、雇主、賣家、鄰居)?",
            "鎖定法律關係與爭點",
        ),
        IntakeField(
            "goal",
            # 停止 leads: the generic flow also carries personal-safety cases, and
            # offering 「拿回款項」 first to someone being stalked is tone-deaf.
            "你希望達成什麼結果?(例:要求對方停止、拿回款項、請求賠償)",
            "決定救濟方向",
        ),
    ],
    [
        IntakeField(
            "timeline",
            "事情何時發生?持續多久了?",
            "確認時效與事實時點",
        ),
        IntakeField(
            "actions_taken",
            "已經採取過哪些行動(例:溝通、存證、申訴)?",
            "決定下一步升級",
        ),
    ],
]


# ── Per-domain checklists ────────────────────────────────────────────────────
# Triage has classified rent / labor / consumer / traffic / family since corpus
# v2, and every one of them was then handed the same four generic questions: the
# classification was computed and thrown away, so a car-accident claim and an
# unreturned deposit were asked the identical 「發生了什麼事?」.
#
# Each list below is built the way SPEC §3.2 says a checklist must be — from the
# element-facts the governing articles actually require, decided in advance. The
# `why` names the article an answer feeds, so a question that stops earning its
# place becomes visible.

RENT_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "rent_issue",
            "租屋的問題是哪一種?(押金不退、修繕不處理、房東要提前收回、漲租、違約金、二房東)",
            "分辨 租賃住宅條例§7(押金) / §10(修繕) / 民法§429 修繕義務",
        ),
        IntakeField(
            "deposit_terms",
            "月租多少?押金押了幾個月?有沒有書面租約?",
            "租賃住宅條例§7 押金上限二個月;有無書面影響舉證",
        ),
    ],
    [
        IntakeField(
            "landlord_claim",
            "房東主張要扣什麼、金額多少?理由是什麼?",
            "區分正常使用之折舊(不得扣)與可歸責損害",
        ),
        IntakeField(
            "handover",
            "點交時有沒有拍照或簽紀錄?搬離日期是哪天?",
            "舉證責任 + 返還押金的起算日",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有匯款紀錄、對話紀錄、照片?",
            "各路徑的舉證",
        ),
        IntakeField(
            "actions_taken",
            "已經跟房東談過嗎?寄過存證信函或申請過調解嗎?",
            "決定下一步升級",
        ),
    ],
]

LABOR_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "labor_issue",
            "勞資問題是哪一種?(加班費、資遣費、欠薪、違法解僱、特休未休、職災)",
            "分辨 勞基法§24(延長工時工資) / §16-17(資遣) / §11-12(終止) / §38(特休)",
        ),
        IntakeField(
            "work_terms",
            "薪資怎麼算(月薪/時薪、多少)?每天大約工作幾小時、一週幾天?",
            "勞基法§24 加班費計算基礎與§30 正常工時",
        ),
    ],
    [
        IntakeField(
            "employment_span",
            "到職和離職(或現在)的日期?年資多久?",
            "勞基法§17 資遣費年資計算、§38 特休天數",
        ),
        IntakeField(
            "employer_reason",
            "雇主給的理由或說法是什麼?(例:責任制、業務緊縮、你自願離職)",
            "勞基法§84-1 需核備、§11 各款事由是否成立",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有出勤紀錄、薪資單、勞動契約、對話紀錄?",
            "勞基法§30 出勤紀錄由雇主保存,舉證有利勞方",
        ),
        IntakeField(
            "actions_taken",
            "申請過勞資爭議調解嗎?向勞工局申訴過嗎?",
            "決定下一步升級",
        ),
    ],
]

CONSUMER_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "consumer_issue",
            "消費問題是哪一種?(七日鑑賞期退貨、商品瑕疵、預付型會員、定型化契約、廣告不實)",
            "分辨 消保法§19(通訊交易解除權) / 民法§354 物之瑕疵擔保",
        ),
        IntakeField(
            "purchase_channel",
            "在哪裡買的?(網購平台、實體店面)金額多少?",
            "消保法§19 只適用通訊交易與訪問交易",
        ),
    ],
    [
        IntakeField(
            "delivery_date",
            "什麼時候收到商品或服務?",
            "消保法§19 七日鑑賞期自收受起算 — 這題決定權利還在不在",
        ),
        IntakeField(
            "seller_response",
            "賣家怎麼回應?有沒有說不能退的理由?",
            "消保法§19-1 合理例外情事、定型化契約條款是否無效",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有訂單紀錄、對話截圖、商品照片?",
            "各路徑的舉證",
        ),
        IntakeField(
            "actions_taken",
            "向平台或賣家申訴過嗎?打過1950或向消保官申訴嗎?",
            "決定下一步升級",
        ),
    ],
]

TRAFFIC_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "injury_damage",
            "是人受傷、車損,還是兩者都有?傷勢與修車金額大概多少?",
            "民法§193(醫療/工作損失) / §195(慰撫金) / §196(物之毀損)",
        ),
        IntakeField(
            "accident_date",
            "事故發生在哪一天?",
            "民法§197 侵權時效二年 — 這題決定還告不告得成",
        ),
    ],
    [
        IntakeField(
            "fault",
            "有沒有報警、做筆錄?拿到初判表或申請過鑑定嗎?雙方各自怎麼說?",
            "民法§217 與有過失,決定求償折扣",
        ),
        IntakeField(
            "insurance",
            "雙方有沒有強制險?對方有沒有第三人責任險?聯絡過保險公司嗎?",
            "強制險是人身傷害的第一順位,先於訴訟",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有行車紀錄器、現場照片、醫療單據、修車估價單?",
            "損害數額的舉證",
        ),
        IntakeField(
            "actions_taken",
            "談過和解嗎?申請過調解嗎?對方態度如何?",
            "決定下一步升級",
        ),
    ],
]

FAMILY_CHECKLIST: list[list[IntakeField]] = [
    [
        IntakeField(
            "family_issue",
            "家事問題是哪一種?(離婚、未成年子女監護或會面、扶養費、遺產繼承、贍養費)",
            "分辨 民法§1052(裁判離婚) / §1055(未成年子女) / §1114(扶養) / §1138 起(繼承)",
        ),
        IntakeField(
            "relationship",
            "雙方的關係與期間?(結婚幾年、被繼承人與你的關係)",
            "身分關係決定適用哪一編",
        ),
    ],
    [
        IntakeField(
            "family_timeline",
            "關鍵時點是哪天?(分居起、被繼承人過世日、對方停止給付日)",
            "民法§1174 拋棄繼承三個月、§1146 回復請求權時效",
        ),
        IntakeField(
            "assets_children",
            "有沒有未成年子女?有沒有財產或債務要處理?",
            "民法§1055 子女最佳利益、§1030-1 剩餘財產分配",
        ),
    ],
    [
        IntakeField(
            "evidence",
            "有沒有戶籍謄本、財產清單、對話或轉帳紀錄?",
            "各路徑的舉證",
        ),
        IntakeField(
            "actions_taken",
            "談過協議嗎?聲請過調解或訪視了嗎?",
            "決定下一步升級",
        ),
    ],
]

# problem_type -> checklist. A type absent from here falls to GENERIC_CHECKLIST,
# so adding a triage category can never dead-end a conversation.
CHECKLISTS: dict[str, list[list[IntakeField]]] = {
    "noise": NOISE_CHECKLIST,
    "rent": RENT_CHECKLIST,
    "labor": LABOR_CHECKLIST,
    "consumer": CONSUMER_CHECKLIST,
    "traffic": TRAFFIC_CHECKLIST,
    "family": FAMILY_CHECKLIST,
    "generic": GENERIC_CHECKLIST,
}


def domain_of(problem_type: str | None) -> str:
    """The checklist key for a triage label.

    Triage reports the finer types prefixed — 「other:rent」, not 「rent」 — and a
    plain dict lookup on that silently missed, which is how five domains kept
    getting the generic questionnaire after they had their own checklists.
    """
    key = (problem_type or "generic").split(":")[-1]
    return key if key in CHECKLISTS else "generic"


def checklist_for(problem_type: str | None) -> list[list[IntakeField]]:
    """The checklist for a triage label, generic when it names no domain."""
    return CHECKLISTS[domain_of(problem_type)]


def _checklist(session_state) -> list[list[IntakeField]]:
    """The checklist for this session (problem_type is duck-typed off state)."""
    return checklist_for(getattr(session_state, "problem_type", None))


def next_questions(session_state) -> list[IntakeField]:
    """Return the next batch of still-unanswered fields (2-3), or [] when the
    whole checklist is complete. Reads session_state.collected_facts (duck-typed
    to avoid a circular import with flow)."""
    asked = getattr(session_state, "asked_keys", set())   # duck-typed: fakes omit it
    for batch in _checklist(session_state):
        # Already asked and still blank means they did not want to answer it.
        # Skipping to the NEXT batch beats re-asking the same sentence, which is
        # the 「不夠智能」 complaint in its purest form.
        unanswered = [
            f for f in batch
            if f.key not in session_state.collected_facts and f.key not in asked
        ]
        if unanswered:
            return unanswered
    return []


# Words that identify WHICH field an answer is about. Positional filing alone
# mis-files constantly in the model-free web demo: a visitor who answered
# 「公寓大廈有管委會」 had it stored as the previous question's answer and was then
# asked 「有管委會的公寓大廈,還是透天/無管委會?」 — the thing they had just said.
# Conservative by construction: a line is re-routed only when it matches exactly
# ONE still-unanswered field, otherwise the positional rule stands.
FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "building_type": ("公寓", "大廈", "透天", "管委會", "套房", "華廈", "宿舍", "社區"),
    "evidence": ("錄音", "錄影", "照片", "截圖", "分貝", "檢測", "沒有證據", "沒錄"),
    # 「口頭要求被拒」 is an actions_taken answer that matched none of these and
    # was demoted to narrative — the cost of refusing to label what we cannot
    # recognise. 要求 is also a goal hint on purpose: the ambiguity sends the
    # line to the field that was actually asked.
    "actions_taken": ("報警", "報過警", "里長", "申訴", "檢舉", "調解", "溝通過",
                      "按門鈴", "反映", "口頭", "談過", "催", "被拒", "要求",
                      "存證", "寄信"),
    "impact": ("睡不好", "失眠", "精神", "健康", "上班", "壓力", "受不了", "耳鳴"),
    "timing": ("半夜", "深夜", "凌晨", "白天", "晚上", "每天", "偶爾", "持續"),
    "goal": ("我想", "希望", "拿回", "要求", "請求", "賠償", "停止", "解約"),
    "timeline": ("多久", "個月", "半年", "一年", "已經"),
}


def route_answer(line: str, unanswered: set[str]) -> str | None:
    """The one unanswered field this line unambiguously answers, else None."""
    hits = [
        key for key in unanswered
        if any(word in line for word in FIELD_HINTS.get(key, ()))
    ]
    return hits[0] if len(hits) == 1 else None


def _answers_the_question_asked(line: str, pending: list[str]) -> bool:
    """True when the line matches the hint words of a field we actually asked
    about this turn. Checking ALL fields' hints instead is too loose: 「釘孔是掛
    照片留下的」 hit the evidence hints — a field the generic checklist never asks
    — and thereby claimed the goal slot. Fields with no hint list keep the old
    positional behaviour, since nothing better is known about them."""
    return any(
        any(word in line for word in FIELD_HINTS[key])
        for key in pending if key in FIELD_HINTS
    ) or any(key not in FIELD_HINTS for key in pending)


def record_answers(session_state, message: str) -> None:
    """Store the user's reply against the fields asked last turn
    (session_state.pending_questions), one answer per non-empty line, positionally
    — except where a line unambiguously answers a DIFFERENT still-open field, in
    which case it is filed there instead. A missing line leaves its field
    unanswered (it is simply re-asked next turn)."""
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip()]
    facts = session_state.collected_facts
    open_keys = {
        f.key for batch in _checklist(session_state) for f in batch if f.key not in facts
    }

    positional: list[str] = []
    for line in lines:
        target = route_answer(line, open_keys)
        if target is not None:
            facts[target] = line
            open_keys.discard(target)
        elif _answers_the_question_asked(line, session_state.pending_questions):
            positional.append(line)
        else:
            # It answers nothing we asked. Filing it positionally is a guess, and
            # a wrong guess is worse than a blank: the visitor SEES it. Measured
            # on the model-free web demo — 「我想拿回押金」 shown as 已採取行動,
            # 「租約到期才搬走」 as 目標, every field shifted one place. Keep the
            # words verbatim where they belong: the free-text description.
            facts["problem"] = f"{facts['problem']} / {line}" if facts.get("problem") else line

    # The leftover lines pair with the still-open asked fields IN ORDER — each
    # list needs its own cursor, or a routed line silently eats a positional slot.
    cursor = 0
    for key in session_state.pending_questions:
        if key in facts:            # already filled by routing this turn
            continue
        if cursor >= len(positional):
            break
        facts[key] = positional[cursor]
        cursor += 1
