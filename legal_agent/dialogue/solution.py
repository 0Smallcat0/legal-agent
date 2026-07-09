"""Stage 4 — Solution output (spec §3.2). Rule-based, NO LLM, NO retrieval.

Give a RANKED escalation ladder for 住宅噪音, cheapest / lowest-effort FIRST and
litigation LAST ("don't rush to sue" — spec §3.2). Rungs are selected from the
collected facts (e.g. the 管委會 rung only for 公寓大廈; steps already tried are
marked done and the next actionable rung is highlighted). Costs/times are
QUALITATIVE (免費 / 低 / 中 / 高) — no NT$ figures are invented.

Mechanisms 3/4/5 are NOT here (next step). The `retrieved` argument is accepted
for a future refinement (attaching verbatim article text to legal_basis) but is
unused in v1.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# §9 / 環保局 exclusion note — ALWAYS present in the output (spec: this must appear).
EPA_NOTE = (
    "若噪音源為工廠/娛樂/營業/營建等「特定場所」(噪音管制法§9),改走環保局檢舉——"
    "近鄰生活噪音不適用§9。"
)

# 存證信函 fill-in template — clearly a TEMPLATE, not legal advice.
LETTER_TEMPLATE = """【存證信函範本(僅供參考,非法律意見;請依實際情況填寫)】
寄件人:【你的姓名】  地址:【你的地址】
收件人:【對方姓名 / 戶號】  地址:【對方地址】
主旨:請停止製造噪音,以維護居住安寧。
說明:
一、台端自【時間 / 期間,例:民國114年5月起】,於【時段,例:每日深夜11時後】在
    【地點,例:本棟○樓】持續發出【噪音情形,例:拖拉家具、喧嘩爭吵】,妨害本人生活安寧。
二、上開情形涉及社會秩序維護法第72條、噪音管制法第6條及民法第793條相鄰關係等規定。
三、請台端自即日起停止上述行為;如未改善,本人將依法【要求,例:報請主管機關裁處 / 提起訴訟】,
    並保留一切法律權利。
此致
【收件人】
                              寄件人:【簽名】   中華民國【年】年【月】月【日】日
"""


@dataclass(frozen=True)
class Rung:
    key: str
    title: str
    what_it_is: str
    legal_basis: tuple[str, ...]   # article refs, corpus-format (統名+第X條)
    cost: str                      # 免費 / 低 / 中 / 高  (qualitative)
    time: str
    effort: str                    # 低 / 中 / 高
    next_step: str
    done: bool = False             # already tried (inferred from actions_taken)
    recommended: bool = False      # the next actionable rung to take


@dataclass
class SolutionLadder:
    rungs: list[Rung]
    note: str
    letter_template: str | None = None
    specific_venue_suspected: bool = False

    def render(self) -> str:
        lines = ["建議處理順序(由低成本 → 高成本;打官司是最後手段):"]
        for i, r in enumerate(self.rungs, 1):
            tags = []
            if r.done:
                tags.append("已嘗試")
            if r.recommended:
                tags.append("👉 建議下一步")
            tag = ("  [" + "、".join(tags) + "]") if tags else ""
            basis = ("　依據:" + "、".join(r.legal_basis)) if r.legal_basis else ""
            lines.append(f"{i}. {r.title}{tag}")
            lines.append(f"   說明:{r.what_it_is}{basis}")
            lines.append(f"   成本:{r.cost}｜時間:{r.time}｜心力:{r.effort}")
            lines.append(f"   下一步:{r.next_step}")
        lines.append("")
        lines.append("※ " + self.note)
        return "\n".join(lines)


# Canonical ladder, already ordered cheapest/lowest-effort FIRST, litigation LAST.
_BASE_RUNGS: list[Rung] = [
    Rung(
        key="hoa",
        title="反映管理委員會",
        what_it_is="向社區管委會反映,請其依規約制止並處理。",
        legal_basis=("公寓大廈管理條例第16條", "公寓大廈管理條例第47條"),
        cost="免費", time="即時~數日", effort="低",
        next_step="向管委會提出(書面)反映,請依第16條制止;不改善可依第47條報請主管機關處理。",
    ),
    Rung(
        key="police",
        title="報警請警察到場",
        what_it_is="近鄰生活噪音,請警察到場勸導/處理。",
        legal_basis=("社會秩序維護法第72條", "噪音管制法第6條"),
        cost="免費", time="即時", effort="低",
        next_step="噪音發生當下報警(110),請警察到場;依社維法第72條可裁罰、噪音法第6條由警察處理。",
    ),
    Rung(
        key="mediation",
        title="里長 / 鄉鎮市區調解委員會 調解",
        what_it_is="申請調解;調解成立經法院核定具執行力。",
        legal_basis=(),
        cost="免費", time="數週", effort="中",
        next_step="向里長或區公所調解委員會申請調解;成立後與確定判決有同一效力。",
    ),
    Rung(
        key="letter",
        title="寄發存證信函",
        what_it_is="正式要求對方停止,並建立書面證據(可用下方範本)。",
        legal_basis=(),
        cost="低", time="數日", effort="中",
        next_step="寄發存證信函正式要求停止製造噪音(見 letter_template),保留回執作為證據。",
    ),
    Rung(
        key="litigation",
        title="民事訴訟",
        what_it_is="訴請排除侵害或請求損害賠償(最後手段)。",
        legal_basis=("民法第793條", "民法第184條", "民法第195條第1項"),
        cost="高", time="數月~數年", effort="高",
        next_step="評估後提起民事訴訟:排除侵害(民法第793條)或損害賠償(第184條、第195條第1項,須情節重大)。建議先諮詢律師。",
    ),
]

# Which actions_taken keywords mean a given rung was already attempted.
_TRIED_KEYWORDS = {
    "hoa": ("管委會", "管理委員會"),
    "police": ("報警", "報過警", "警察", "叫警察", "找警察", "110"),
    "mediation": ("調解", "里長"),
    "letter": ("存證",),
    "litigation": ("訴訟", "起訴", "提告", "告他"),
}
# §9 "特定場所" hints (near-neighbour home noise does NOT go this route).
_SPECIFIC_VENUE = ("工廠", "娛樂", "營業", "營建", "擴音")


def _is_apartment(building_type: str) -> bool:
    bt = building_type or ""
    if "透天" in bt:
        return False
    return ("公寓" in bt) or ("大廈" in bt) or ("管委會" in bt and "無管委會" not in bt)


def _already_tried(key: str, actions_taken: str) -> bool:
    a = actions_taken or ""
    return any(kw in a for kw in _TRIED_KEYWORDS.get(key, ()))


def _is_specific_venue(noise_type: str) -> bool:
    nt = noise_type or ""
    return any(kw in nt for kw in _SPECIFIC_VENUE)


def build_solution_ladder(collected_facts: dict, retrieved=None) -> SolutionLadder:
    """Build the ranked 住宅噪音 escalation ladder from the collected facts.

    Cheapest/lowest-effort first, litigation last; the 管委會 rung is included only
    for 公寓大廈; rungs already attempted are marked done and the first not-done rung
    is flagged as the recommended next step. `retrieved` is unused in v1.
    """
    facts = collected_facts or {}
    building_type = facts.get("building_type", "")
    actions_taken = facts.get("actions_taken", "")
    noise_type = facts.get("noise_type", "")

    rungs: list[Rung] = []
    for base in _BASE_RUNGS:
        if base.key == "hoa" and not _is_apartment(building_type):
            continue  # 管委會 rung only applies to 公寓大廈
        rungs.append(replace(base, done=_already_tried(base.key, actions_taken)))

    # Highlight the first not-yet-tried rung as the recommended next step.
    for i, r in enumerate(rungs):
        if not r.done:
            rungs[i] = replace(r, recommended=True)
            break

    return SolutionLadder(
        rungs=rungs,
        note=EPA_NOTE,
        letter_template=LETTER_TEMPLATE,
        specific_venue_suspected=_is_specific_venue(noise_type),
    )
