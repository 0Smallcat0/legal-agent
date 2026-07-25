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


GENERIC_NOTE = (
    "通用流程:主管機關依問題領域而異(勞資→勞工局、消費→消保官/消基會、"
    "租屋→地方政府住宅主管機關、車禍→鄉鎮市調解委員會/法院)。"
    "本階梯為一般順序,個案請以檢索到的法條與主管機關指引為準。"
)


# Which authority actually handles a complaint, keyed by the statute the case
# turned out to be about. Procedural pointers only — no legal claims, nothing
# that needs to be verifiable against the corpus. Measured need: six lived
# sessions all got the same 「勞工局/消保官/住宅主管機關等」 catch-all, which tells
# a 打工族 nothing about where to actually file.
_AUTHORITY_BY_STATUTE: tuple[tuple[str, str, str], ...] = (
    ("勞動基準法", "勞工局 / 勞動檢查機構申訴",
     "向工作地的勞工局(勞動檢查處)申訴,或申請勞資爭議調解;申訴可具名或匿名"),
    ("消費者保護法", "消費者服務中心(1950)/ 消保官申訴",
     "撥 1950 或向地方政府消費者服務中心申訴;不成立可再申請消費爭議調解"),
    ("租賃住宅市場發展及管理條例", "地方政府住宅主管機關 / 租屋糾紛調處",
     "向房屋所在地縣市政府的住宅(地政)主管機關申請調處"),
    ("道路交通管理處罰條例", "行車事故鑑定 + 調解委員會",
     "向公路主管機關申請車輛行車事故鑑定,並同時向鄉鎮市區調解委員會聲請調解"),
    ("公寓大廈管理條例", "管委會 → 建管 / 公寓大廈主管機關",
     "先以書面向管委會反映;未改善再向縣市政府建管(公寓大廈)主管機關報請處理"),
    ("噪音管制法", "環保局 / 警察機關(依噪音來源分工)",
     "營業、營建、擴音等特定場所找環保局;近鄰生活噪音當下報警處理"),
    ("家庭暴力防治法", "113 保護專線 / 家庭暴力防治中心",
     "撥打 113 或聯繫縣市家庭暴力防治中心;必要時向法院聲請保護令"),
)

# A free-lawyer route the ladder never mentioned. Procedural, means-tested, and
# for a student with no money it is the most useful rung on the page.
_LEGAL_AID_RUNG = Rung(
    "legal_aid", "法律扶助 / 免費法律諮詢",
    "法扶基金會與各地方政府、律師公會提供免費法律諮詢;經資力審查通過者可獲扶助律師",
    (), "免費", "數日~數週", "低",
    "先撥法扶基金會或縣市政府法律諮詢專線預約諮詢;要打官司再評估申請扶助(須經資力審查)",
)


def _authority_rung(retrieved) -> Rung:
    """The 主管機關 rung, named for the statute the case actually turned on."""
    for statute in retrieved or []:
        for statute_id, title, next_step in _AUTHORITY_BY_STATUTE:
            if statute.statute_id == statute_id:
                return Rung("authority", title,
                            "向該領域主管機關申訴/檢舉,由公權力介入", (),
                            "免費", "數週", "中", next_step, False, False)
    return Rung(
        "authority", "主管機關申訴/檢舉",
        "向該領域主管機關申訴(勞工局/消保官/住宅主管機關等)", (),
        "免費", "數週", "中", "備妥證據向主管機關提出申訴", False, False,
    )


def build_generic_ladder(collected_facts: dict, retrieved=None) -> SolutionLadder:
    """Generic escalation ladder for non-noise problems (spec §3.4 fallback):
    same cheapest-first shape, no scenario-specific statutes baked in — the
    legal basis for a generic case is whatever Stage 3 retrieved, and the
    authority rung is named from those same retrieved statutes."""
    rungs = [
        Rung(
            "evidence", "蒐證與書面紀錄",
            "保存契約/對話紀錄/單據/照片,整理時間軸", (),
            "免費", "隨時", "低", "把事實與證據整理成一頁時間軸", False, True,
        ),
        Rung(
            "negotiate", "正式溝通與存證信函",
            "以書面(LINE/email/存證信函)明確提出請求與期限", (),
            "低", "數天", "低", "寄出書面請求,保留送達證明", False, False,
        ),
        Rung(
            "mediate", "調解",
            "鄉鎮市(區)調解委員會或主管機關調解,免費且具執行力", (),
            "免費", "數週", "中", "向所在地調解委員會聲請調解", False, False,
        ),
        _authority_rung(retrieved),
        _LEGAL_AID_RUNG,
        Rung(
            "litigation", "民事訴訟(最後手段)",
            "小額/簡易/通常程序,依金額與案情選擇", (),
            "中~高", "數月以上", "高", "評估金額與勝算,必要時諮詢律師", False, False,
        ),
    ]
    return SolutionLadder(rungs=rungs, note=GENERIC_NOTE)


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
