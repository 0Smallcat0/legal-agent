"""Stage 4 — Solution output (spec §3.2). Rule-based, NO LLM, NO retrieval of its own.

A RANKED escalation ladder, cheapest / lowest-effort FIRST and litigation LAST
("don't rush to sue" — spec §3.2). `build_solution_ladder` is the hand-built
住宅噪音 ladder (管委會 rung only for 公寓大廈; tried steps marked done, the next
actionable rung highlighted); `build_generic_ladder` covers every other domain;
`build_respondent_ladder` serves the side being complained about. Costs/times are
QUALITATIVE (免費 / 低 / 中 / 高) — no NT$ figures are invented. The one exception
is the generic litigation rung: when the user typed the amount, the 裁判費 is
computed from 民事訴訟法's own brackets (`court_fee`), never estimated.

`retrieved` is Stage 3's retrieval window, reused, never re-queried: it supplies
the verbatim deadline rung, the generic letter's 依據 lines, the authority rung,
the respondent's thresholds, and the "also retrieved" block.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from legal_agent.anti_hallucination.verifier import _parse_number
from legal_agent.retrieval.families import _CIVIL_RANGES, _CROSS_CUTTING, statute_family

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
    also_retrieved: str | None = None
    # The complainant's heading is an escalation promise. A respondent is not
    # escalating anything, and the heading is the first line he reads.
    header: str = "建議處理順序(由低成本 → 高成本;打官司是最後手段):"

    def render(self) -> str:
        lines = [self.header]
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
        # Rungs point at the letter template, so it must be on the page.
        if self.also_retrieved:
            lines.append("")
            lines.append(self.also_retrieved)
        if self.letter_template:
            lines.append("")
            lines.append(self.letter_template)
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
        legal_basis=("鄉鎮市調解條例第23條", "鄉鎮市調解條例第27條"),
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


def _is_apartment(building_type: str) -> bool:
    bt = building_type or ""
    if "透天" in bt:
        return False
    return ("公寓" in bt) or ("大廈" in bt) or ("管委會" in bt and "無管委會" not in bt)


def _already_tried(key: str, actions_taken: str) -> bool:
    a = actions_taken or ""
    return any(kw in a for kw in _TRIED_KEYWORDS.get(key, ()))


GENERIC_NOTE = (
    "通用流程:主管機關依問題領域而異(勞資→勞工局、消費→消保官/消基會、"
    "租屋→地方政府住宅主管機關、車禍→鄉鎮市調解委員會/法院)。"
    "本階梯為一般順序,個案請以檢索到的法條與主管機關指引為準。"
)


# Which authority actually handles a complaint, keyed by the statute the case
# turned out to be about. Procedural pointers only — no legal claims, nothing
# that needs to be verifiable against the corpus. (Six lived sessions had all
# got the same 「勞工局/消保官/住宅主管機關等」 catch-all, which says nothing about
# where to file.)
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


# A period only counts when the sentence that carries it is ABOUT a deadline —
# 「二年以內」 in §949 is one, 「二年」 inside a definition is not. Both halves must
# be present in the same sentence, and the sentence is quoted VERBATIM, because
# the model invents deadlines (evals/HISTORY.md).
_PERIOD = re.compile(r"[一二三四五六七八九十兩0-9]+\s*(?:年|個月|月|日|星期|週)")
# A right dying — that is what the user has to act before.
_LOSES_RIGHT = ("時效", "不行使", "消滅", "屆滿")
# A period that is merely a window to do something in. Kept, but ranked below.
_PLAIN_PERIOD = ("以內", "期間", "逾期")
# 消保法§11-1's 「三十日以內之合理期間，供消費者審閱」 is a period the SELLER owes,
# not a deadline the reader can miss.
_NOT_A_DEADLINE = ("審閱",)


# Things a person says they already have, so the first rung names THEIR evidence.
# Nothing here is suggested — a word only appears if the user typed it.
_EVIDENCE_WORDS = (
    "合約", "契約", "收據", "發票", "匯款紀錄", "匯款單", "轉帳紀錄", "對話紀錄",
    "LINE", "簡訊", "email", "照片", "影片", "監視器", "錄音", "診斷證明", "估價單",
    "報價單", "行照", "名片", "會單", "存證信函", "出勤紀錄", "薪資單", "送洗單",
    "行程表", "裝箱照片", "清單", "字條", "保固卡", "維修紀錄", "驗屋報告",
)


def _evidence_next_step(collected_facts: dict) -> str | None:
    """The first rung's instruction, naming the documents the user said they have."""
    said = " ".join(str(v) for v in (collected_facts or {}).values() if v)
    have = [w for w in _EVIDENCE_WORDS if w in said]
    if not have:
        return None
    return (
        f"先把你提到的{'、'.join(have[:4])}掃描或截圖存檔,依發生時間排成一頁,"
        "後面每一步都用得到"
    )


def _also_retrieved_block(retrieved, cited) -> str | None:
    """Articles retrieval found that the ANSWER never mentioned, quoted verbatim.

    The model cites few of the retrieved articles and prompting it to cite more
    lost (evals/RESULTS.md §3), so the skipped ones are printed for the reader."""
    if not retrieved or not cited:
        return None
    wanted = {(sid, ano) for sid, ano in cited}
    missing = [s for s in retrieved if (s.statute_id, s.article_no) not in wanted]
    if not missing:
        return None
    # An article that states a period is one the reader can be caught by, so it
    # leads — otherwise one sitting sixth in retrieval order never shows.
    missing.sort(key=lambda s: not _deadline_sentences([s]))
    body = "\n".join(
        f"・{s.statute_id}{s.article_no}:{(s.content or '').splitlines()[0]}"
        for s in missing[:5]
    )
    return (
        "※ 以下條文有檢索到,但上面的分析沒有提到——逐字列出各條第一項供你自己判斷是否相關"
        f"(共 {len(missing)} 條,列出前 {min(len(missing), 5)} 條):\n{body}"
    )


def _generic_letter(retrieved, collected_facts: dict) -> str | None:
    """A 存證信函 the reader can copy, with the law quoted VERBATIM from what was
    retrieved. The blanks are the FACTS and the amount; the POSTURE is written in
    — 主旨 demands that 台端 do something 以維本人權益, and 說明四 announces that the
    sender will 依法主張權利 if the deadline passes.

    So it is a claimant's letter, not a neutral one: `build_generic_ladder`
    withholds it from anyone who has not said they are the one asserting.

    It quotes no period. The letter goes to the other side, and a period is the
    sender's own clock, already the ladder's first rung. Picked from anywhere in
    the window it was also the one line no 「請自行刪去」 covered: 退租押金 mailed
    民法§686 (合夥人退夥) to the landlord, and with a model, 勞基法§9-1 (競業禁止).

    Each article is quoted whole. Its first paragraph alone sent a tenant's
    landlord §432's duty of care without the 但書 that exempts ordinary wear.
    Keeping only articles of the lead article's kind was measured and rejected:
    retrieval's first article is often the off-topic one, and on the 168 stored
    sessions 19 lost every expected article from the letter."""
    if not retrieved:
        return None
    cited = retrieved[:3]
    basis = "\n".join(
        f"    {i}. {s.statute_id}{s.article_no}:"
        + "\n       ".join((s.content or "").splitlines())
        for i, s in enumerate(cited, 1)
    )
    evidence = _evidence_next_step(collected_facts)
    have = "(可附上:" + evidence.split("先把你提到的")[1].split("掃描")[0] + ")" if evidence else ""
    return (
        "【存證信函範本(僅供參考,非法律意見;方括號請自行填寫)】\n"
        "寄件人:【你的姓名】  地址:【你的地址】\n"
        "收件人:【對方姓名/公司】  地址:【對方地址】\n"
        "主旨:請台端於【期限,例:文到七日】內【你的請求,例:返還○○元 / 交付○○ / 修補瑕疵】,\n"
        "      以維本人權益。\n"
        "說明:\n"
        f"一、本人與台端間【簡述關係與時間,例:於民國114年3月委由台端承攬○○工程】。{have}\n"
        "二、【事實經過:發生什麼、你何時反映、對方如何回覆——照你自己的話寫】\n"
        "三、上開情形涉及下列規定(逐字引錄自現行條文;與你情況不符者請自行刪去):\n"
        f"{basis}\n"
        "四、請於上開期限內處理,逾期本人將依法主張權利,特此函達。\n"
        "此致\n【收件人】\n"
        "                              寄件人:【簽名】   中華民國【年】年【月】月【日】日\n"
    )


def _deadline_sentences(retrieved) -> list[tuple[str, str]]:
    """(article ref, verbatim sentence) for every retrieved article whose own text
    states a period. Nothing is paraphrased and nothing is computed. Sentences
    about a right EXPIRING rank ahead of plain-period ones."""
    ranked: list[tuple[int, str, str]] = []
    for statute in retrieved or []:
        ref = f"{statute.statute_id}{statute.article_no}"
        best: tuple[int, str] | None = None
        for sentence in re.split(r"[。\n]", statute.content or ""):
            if not _PERIOD.search(sentence) or any(w in sentence for w in _NOT_A_DEADLINE):
                continue
            if any(w in sentence for w in _LOSES_RIGHT):
                rank = 0
            elif any(w in sentence for w in _PLAIN_PERIOD):
                rank = 1
            else:
                continue
            if best is None or rank < best[0]:
                best = (rank, sentence.strip())
        if best is not None:
            ranked.append((best[0], ref, best[1]))
    ranked.sort(key=lambda row: row[0])
    return [(ref, sentence) for _rank, ref, sentence in ranked]


_RANGE_STARTS = sorted(lo for lo, _hi, _family in _CIVIL_RANGES)


def _kind(statute) -> str:
    """The kind of dispute an article belongs to: the shared family table first,
    the statute itself outside 民法, and for a 民法 article the table leaves out, the
    stretch of the code between the same two mapped ranges — so §949 goes with
    §950 (占有) and §686 (合夥) goes with neither §440 nor §7."""
    family = statute_family(f"{statute.statute_id}{statute.article_no}")
    if family is not None:
        return family
    number = re.match(r"第(\d+)", statute.article_no or "")
    if statute.statute_id != "民法" or not number:
        return statute.statute_id
    after = next((lo for lo in _RANGE_STARTS if lo > int(number.group(1))), 0)
    return f"民法<{after}"


def _on_topic(retrieved) -> list:
    """The window cut to the dispute the case is about, for quoting periods.

    The tail of an eight-article window is often another dispute's: 退租押金 led its
    ladder with 民法§686, 合夥人退夥. A period is quoted from the first three
    articles (the answer's own citations first, `_answer_first`), from one of the
    same kind as them, or from a rule that cuts across every kind (時效). On the 168
    stored sessions the quoted periods go from 93 to 72 and all 16 that are
    expected articles stay (evals/RESULTS.md §8.2)."""
    window = list(retrieved or [])
    kinds = {_kind(s) for s in window[:3]} - _CROSS_CUTTING
    if not kinds:
        return window
    return [s for i, s in enumerate(window)
            if i < 3 or _kind(s) in kinds or _kind(s) in _CROSS_CUTTING]


def _deadline_rung(retrieved) -> Rung | None:
    """Surface the periods the retrieved articles themselves state. A claim dies of
    a deadline the user never heard of, and no other rung mentions time at all."""
    deadlines = _deadline_sentences(_on_topic(retrieved))
    if not deadlines:
        return None
    quoted = ";".join(f"{ref}「{sentence}」" for ref, sentence in deadlines[:3])
    return Rung(
        "deadline", "先確認期限(檢索到的條文自己寫了期間)",
        f"以下期間出現在本案檢索到的條文原文中,逐字引用:{quoted}。"
        "起算日與是否中斷因個案而異,請以條文與律師意見為準",
        tuple(ref for ref, _ in deadlines[:3]),
        "免費", "立刻", "低",
        "對照條文確認你的情況距離期間屆滿還有多久,再決定要不要先寄存證信函中斷時效",
        False, True,
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


def _answer_first(retrieved, cited) -> list:
    """Retrieval order with the articles the ANSWER actually cited moved to the front.

    Retrieval rank cannot tell whose right an article states; the answer's own
    citations can."""
    if not retrieved or not cited:
        return list(retrieved or [])
    wanted = {(sid, ano) for sid, ano in cited}
    head = [s for s in retrieved if (s.statute_id, s.article_no) in wanted]
    tail = [s for s in retrieved if (s.statute_id, s.article_no) not in wanted]
    return head + tail


# The venue that actually hears each kind of dispute. 「鄉鎮市調解委員會」 is right
# for a neighbour quarrel and wrong for most of the rest: a car crash is paid by
# 強制險 long before anyone mediates, a consumer complaint has a free hotline and a
# 消保官, and family matters must attempt 調解 first. Free/low-cost steps stay
# ahead of paid ones, litigation stays last.
_GENERIC_MEDIATE = Rung(
    "mediate", "調解",
    "鄉鎮市(區)調解委員會或主管機關調解,免費且具執行力",
    ("鄉鎮市調解條例第23條", "鄉鎮市調解條例第27條"),
    "免費", "數週", "中", "向所在地調解委員會聲請調解", False, False,
)

_DOMAIN_RUNGS: dict[str, list[Rung]] = {
    "rent": [
        Rung(
            "rent_dispute", "租賃住宅爭議調處",
            "直轄市/縣市不動產租賃爭議處理,由主管機關受理,免費",
            ("租賃住宅市場發展及管理條例第16條",),
            "免費", "數週", "中",
            "向房屋所在地的地政或建管單位申請租賃爭議調處", False, False,
        ),
        _GENERIC_MEDIATE,
    ],
    "labor": [
        Rung(
            "labor_report", "向勞工局申訴/檢舉",
            "主管機關可命雇主限期改善並裁罰;申訴人身分受保密",
            ("勞動基準法第74條",),
            "免費", "數週", "低",
            "向公司所在地勞工局(處)申訴,附出勤與薪資紀錄", False, False,
        ),
        Rung(
            "labor_mediate", "勞資爭議調解",
            "勞資爭議處理法的正式程序,免費;調解成立與民事確定判決同一效力",
            # Deliberately empty: 勞資爭議處理法 is not in the corpus, and this
            # project does not cite what it cannot verify. The rung still tells
            # the reader where to go — it just does not pretend to a legal basis.
            (),
            "免費", "數週", "中",
            "向勞工局申請勞資爭議調解(可線上申請)", False, False,
        ),
    ],
    "consumer": [
        Rung(
            "consumer_hotline", "1950 消費者服務專線 / 消保官申訴",
            "先向企業經營者申訴;未獲妥適處理可向消保官申訴",
            ("消費者保護法第43條",),
            "免費", "數日~數週", "低",
            "撥 1950 或到消費者保護會線上申訴,附訂單與對話紀錄", False, False,
        ),
        Rung(
            "consumer_mediate", "消費爭議調解",
            "直轄市/縣市消費爭議調解委員會,免費且具執行力",
            ("消費者保護法第44條",),
            "免費", "數週", "中",
            "申訴未果後向消費爭議調解委員會申請調解", False, False,
        ),
    ],
    "traffic": [
        Rung(
            "compulsory_insurance", "申請強制汽車責任保險給付",
            "人身傷亡不論肇責都可先向對方強制險請求;不影響後續求償",
            ("強制汽車責任保險法第7條", "強制汽車責任保險法第25條"),
            "免費", "交齊文件次日起十個工作日內給付", "低",
            "備診斷證明、醫療單據與事故證明,向對方投保的產險公司申請理賠", False, False,
        ),
        Rung(
            "traffic_mediate", "鄉鎮市調解委員會調解",
            "車禍調解的常見途徑,免費;調解成立經法院核定與判決同效力",
            ("鄉鎮市調解條例第23條", "鄉鎮市調解條例第27條"),
            "免費", "數週", "中",
            "向事故地或對方住所地調解委員會聲請,帶初判表與估價單", False, False,
        ),
    ],
    "family": [
        Rung(
            "family_mediate", "家事調解(多數家事事件的前置程序)",
            "向法院聲請調解,由調解委員協助;離婚、親權、扶養多須先經調解",
            (),
            "低", "數週~數月", "中",
            "向對方住所地的地方法院家事庭聲請調解", False, False,
        ),
    ],
}


# Rungs that only make sense when the READER is the one asserting a claim: each
# is 申請 / 申訴 / 檢舉 / 聲請 against the other side. Handed to a landlord accused of
# keeping a deposit, or a driver blamed for the crash, it says 「report the other side」.
_ASSERTING_RUNGS = frozenset({
    "negotiate", "authority", "litigation",
    "labor_report", "consumer_hotline", "compulsory_insurance",
})

# Mediation is the exception, and the reason is what mediation IS: both parties
# attend, either may apply, and applying is not an admission. The wording was
# the problem, not the step — so these survive with the two-way sentence added
# rather than being silenced.
_TWO_WAY_MEDIATION = (
    ";調解由雙方到場,任何一方都可以聲請,被要求的一方主動聲請不等於承認對方的主張"
)

# 強制險 is silenced for a different reason than the rest: its next_step names
# the other party outright — 「向對方投保的產險公司申請理賠」 — so handing it to
# the person blamed for the crash instructs him to claim against his own
# counterparty.

NON_ASSERTING_NOTE = (
    "以下少了幾個步驟,是刻意的。申訴、檢舉、寄存證信函、提起訴訟這些階段是寫給"
    "「提出主張的一方」的;在還不知道你是哪一方、或你是被要求的一方時端出來,等於"
    "叫你去對要求你的人採取行動。想看那一組,只要說一句你是提出主張的一方。"
)


def _deadline_for_stance(rung: Rung | None, stance: str | None) -> Rung | None:
    """A period means opposite things to the two sides, so it is labelled.

    The claimant's version tells him to consider 存證信函 to interrupt the clock;
    that sentence handed to a respondent is an instruction to act on someone
    else's deadline.
    """
    if rung is None or stance == "complainant":
        return rung
    if stance == "respondent":
        return replace(
            rung,
            key="other_side_deadline", title="對方主張權利的期間(條文原文)",
            next_step="把日期對照條文原文自己看過;本工具不判斷這段期間是否已經經過,"
                      "也不代表期間經過就對你有利",
            recommended=False,
        )
    return replace(
        rung,
        next_step="對照條文確認距離期間屆滿還有多久;這段期間對哪一方有意義,"
                  "取決於是誰在向誰主張權利",
    )


# ── Suing: which track and what fee, from the amount the user typed ──────────
# Every quoted line is a verbatim substring of the article it names in the
# shipped corpus (tests/test_litigation_rung.py checks each one). The thresholds
# and brackets are the statute's; the arithmetic is the only thing computed, and
# nothing is computed from an amount the user did not type.
_SMALL_CLAIMS = ("民事訴訟法第436-8條",
                 "關於請求給付金錢或其他代替物或有價證券之訴訟，其標的金額或價額在"
                 "新臺幣十萬元以下者，適用本章所定之小額程序。")
_SUMMARY = ("民事訴訟法第427條",
            "關於財產權之訴訟，其標的之金額或價額在新臺幣五十萬元以下者，適用本章所定之簡易程序。")
_SUMMARY_ANY_AMOUNT = ("民事訴訟法第427條", "下列各款訴訟，不問其標的金額或價額一律適用簡易程序：")
_SUMMARY_TRAFFIC = ("民事訴訟法第427條", "十一、本於道路交通事故有所請求而涉訟者。")
_FEE_ARTICLE = "民事訴訟法第77-13條"
# (above this amount, up to the next row's, NT$ per 萬, the clause that says so)
_FEE_BRACKETS = (
    (0, 1_000, "在新臺幣十萬元以下部分，徵收裁判費一千元"),
    (100_000, 100, "逾十萬元至一百萬元部分，每萬元徵收一百元"),
    (1_000_000, 90, "逾一百萬元至一千萬元部分，每萬元徵收九十元"),
    (10_000_000, 80, "逾一千萬元至一億元部分，每萬元徵收八十元"),
    (100_000_000, 70, "逾一億元至十億元部分，每萬元徵收七十元"),
    (1_000_000_000, 60, "逾十億元部分，每萬元徵收六十元"),
)
_FEE_ODD = "其畸零之數不滿萬元者，以萬元計算"
# What the court actually collects is higher: 臺灣高等法院's 113-12-30 standard adds
# 5/10 to the first 十萬 and 3/10 above it. That standard is not in the corpus, so
# the page states the statutory ceiling on any surcharge instead of its figure.
_SURCHARGE = ("民事訴訟法第77-27條", "但其加徵之額數，不得超過原額數十分之五。")
_PAYMENT_ORDER = ("民事訴訟法第508條",
                  "債權人之請求，以給付金錢或其他代替物或有價證券之一定數量為標的者，"
                  "得聲請法院依督促程序發支付命令。")
_PAYMENT_ORDER_FEE = ("民事訴訟法第77-19條", "下列聲請或提出異議，徵收裁判費新臺幣五百元：")
_PAYMENT_ORDER_FEE_ITEM = ("民事訴訟法第77-19條", "五、聲請發支付命令。")
_PAYMENT_ORDER_OBJECTED = ("民事訴訟法第519條",
                           "債務人對於支付命令於法定期間合法提出異議者，支付命令於異議範圍內"
                           "失其效力，以債權人支付命令之聲請，視為起訴或聲請調解。")
_FREE_MEDIATION = ("鄉鎮市調解條例第23條",
                   "調解，除勘驗費應由當事人核實開支外，不得徵收任何費用，或以任何名義收受報酬。")

LITIGATION_QUOTES = (
    _SMALL_CLAIMS, _SUMMARY, _SUMMARY_ANY_AMOUNT, _SUMMARY_TRAFFIC,
    *((_FEE_ARTICLE, clause) for _low, _rate, clause in _FEE_BRACKETS),
    (_FEE_ARTICLE, _FEE_ODD), _SURCHARGE, _PAYMENT_ORDER, _PAYMENT_ORDER_FEE,
    _PAYMENT_ORDER_FEE_ITEM, _PAYMENT_ORDER_OBJECTED, _FREE_MEDIATION,
)


def court_fee(amount: int) -> int:
    """民事訴訟法§77-13's 裁判費 for a 財產權 claim of `amount`, before any §77-27
    surcharge. 「畸零之數不滿萬元者，以萬元計算」: the amount is rounded UP to 萬."""
    wan = -(-amount // 10_000) * 10_000
    fee = _FEE_BRACKETS[0][1]
    for (low, rate, _), nxt in zip(_FEE_BRACKETS[1:], (*_FEE_BRACKETS[2:], None), strict=True):
        if wan > low:
            top = wan if nxt is None else min(wan, nxt[0])
            fee += (top - low) // 10_000 * rate
    return fee


@dataclass(frozen=True)
class ClaimAmount:
    low: int        # equal to `high` for an exact figure;
    high: int       # 「八萬多」 is 80,001 to 89,999
    said: str       # the user's own words, quoted back to them


# A figure followed by 萬/千/元/塊 (「八萬」「三千」「3000元」「1.5萬」「八萬多」
# 「四十幾萬」「兩千多萬」) or led by 新臺幣/NT$. A bare number is never money:
# 「三個月」「5年」 carry no unit.
_MONEY = re.compile(
    r"(?P<cur>新臺幣|新台幣|NT\$)?\s*"
    r"(?P<num>[0-9０-９][0-9０-９,，]*(?:\.[0-9]+)?\s*(?:萬(?:[0-9０-９]+千?)?|千)?"
    r"|[零〇一二兩三四五六七八九十百千萬壹貳參肆伍陸柒捌玖拾佰仟]+)"
    r"(?P<more>多|幾)?(?P<wan>萬)?\s*(?P<yuan>元|塊)?"
)
# A figure the user gave per month / per item is a rate, not what is owed.
_RATE_BEFORE = ("每", "月薪", "月付", "月費", "月租", "月繳", "月領", "個月", "年薪",
                "時薪", "日薪", "一天", "一年", "薪水", "薪資", "一次", "一期")
# 「押金兩個月共三萬二」: the months were counted and this is their sum, not a rate.
_TOTAL_BEFORE = re.compile(r"(?:共|合計|總計|加起來)是?\s*$")
# The other side's figure — a cap, an offer or a charge (「最高賠三千」「只肯退我五千」
# 「還要收手續費三千」) — is what the user disputes, not what they claim. 「沒收」 is not.
_THEIRS_BEFORE = re.compile(
    r"(?:(?:只|最高|最多|頂多)(?:能|肯|願意?)?(?:賠|退|付|給)我?"
    r"|(?<![沒回])收(?:取)?(?:手續費|服務費|費用)?)$"
)
# 「大概八萬」「快七萬」「不到十萬」 state no amount to compute from.
_HEDGE_BEFORE = ("大概", "大約", "約", "快", "將近", "差不多", "不到", "接近", "超過",
                 "至少", "最多", "最高", "上看", "幾")
# 「欠我三十萬」「我想把八萬塊要回來」: the figure the user says is the claim.
_CLAIM_BEFORE = re.compile(r"(?:欠我|還我|要回|拿回|討回|追回|求償|金額)(?:這|那|全部|全額|總共)?\s*$")
_CLAIM_AFTER = re.compile(r"^\s*(?:能不能|可不可以|有沒有辦法)?(?:要回|拿回|討回|追回|要得回|拿得回)")
_NOT_MONEY_AFTER = "人次件個張台輛坪公分年月日天週歲名戶位份條項款號樓層"
_CLAUSE = re.compile(r"[,，。;；!！?？\n、]")
_PLACE = {"十": 10, "百": 100, "千": 1000, "萬": 10_000, "拾": 10, "佰": 100, "仟": 1000}
_FULLWIDTH_DIGITS = {ord("０") + i: ord("0") + i for i in range(10)}
# 「幾萬」「數千」「上萬」 name an order of magnitude, not an amount.
_VAGUE_LEAD = "幾數多上好"


def _figure(num: str) -> tuple[int, int] | None:
    """(value, the place of its last unit) for one money figure, or None.

    「三萬八」 is 38,000 in speech, not 30,008, and 「一千八」 is 1,800: a lone digit
    after 萬/千/百 is that unit's next place down. An Arabic 「30」 has the place of
    its last nonzero digit, so 「30多萬」 runs to 39萬 like 「三十多萬」."""
    num = num.replace(" ", "").translate(_FULLWIDTH_DIGITS).replace(",", "").replace("，", "")
    arabic = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(?:(萬)([0-9]+)?(千)?|(千))?", num)
    if arabic:
        lead, wan, tail, tail_k, k = arabic.groups()
        unit = 10_000 if wan else 1000 if k else 1
        value = float(lead) * unit
        if tail:                                  # 3萬5千 / 3萬5 (spoken) / 3萬5000
            value += int(tail) * (1000 if tail_k or len(tail) == 1 else 1)
            unit = 1000 if tail_k or len(tail) == 1 else 1
        elif unit == 1 and "." not in lead:       # 30(多萬) / 3000(多元)
            unit = 10 ** (len(lead) - len(lead.rstrip("0")))
        return (int(value), unit) if value == int(value) else None
    spoken = re.fullmatch(r"(.*[萬千百])([一二兩三四五六七八九])", num)
    if spoken:
        head = _parse_number(spoken.group(1))
        unit = _PLACE[spoken.group(1)[-1]]
        if head is None:
            return None
        return head + _parse_number(spoken.group(2)) * unit // 10, unit // 10
    value = _parse_number(num)
    if value is None:
        return None
    units = [_PLACE[ch] for ch in num if ch in _PLACE]
    return value, (units[-1] if units else 1)


def claim_amount(collected_facts: dict) -> tuple[ClaimAmount | None, tuple[str, ...]]:
    """The one amount the user stated, or (None, every money phrase they used).

    Never picks among several: a 月薪, a 總價 and a 訂金 in one story leave nobody
    able to say which is the claim, so the rung asks. A figure the user says they
    want back (「欠我三十萬」「把八萬塊要回來」) is the claim even when others appear."""
    said = " ".join(str(v) for v in (collected_facts or {}).values() if v)
    marked: dict[tuple[int, int], str] = {}
    plain: dict[tuple[int, int], str] = {}
    rates: set[int] = set()
    vague: list[str] = []
    for m in _MONEY.finditer(said):
        num, more, wan = m.group("num"), m.group("more"), m.group("wan")
        yuan = m.group("yuan") or m.group("cur")
        if not (wan or yuan or any(ch in num for ch in "萬千仟")):
            continue                              # no unit: not money
        if yuan == "塊" and not (wan or any(ch in num for ch in "萬千仟百佰")
                                 or sum(ch.isdigit() for ch in num) >= 3):
            continue                              # 一塊農地 / 少一塊都不行: a piece, not a dollar
        if said[m.end():m.end() + 1] and said[m.end()] in _NOT_MONEY_AFTER and not yuan:
            continue                              # 三千人 / 兩萬次
        start = m.start("num")
        phrase = m.group(0).strip()
        if num[:1] in "萬千百仟佰":               # 千萬不要 / 萬一 — unless 幾萬 / 上萬
            if said[start - 1:start] and said[start - 1] in _VAGUE_LEAD:
                vague.append(said[start - 1:m.end()].strip())
            continue
        figure = _figure(num)
        before = _CLAUSE.split(said[max(0, start - 8):start])[-1]
        if figure is None:
            vague.append(phrase)
            continue
        value, place = figure
        if wan:
            value, place = value * 10_000, place * 10_000
        low, high = (value + 1, value + place - 1) if more else (value, value)
        if ((any(w in before for w in _RATE_BEFORE) and not _TOTAL_BEFORE.search(before))
                or _THEIRS_BEFORE.search(before)):
            rates.update((low, high))
            continue
        hedge = next((h for w in _HEDGE_BEFORE for h in (w + "是", w) if before.endswith(h)), "")
        if hedge:                                 # quoted back with the hedge: 「大概兩百萬」
            vague.append(said[start - len(hedge):m.end()].strip())
            continue
        claimed = _CLAIM_BEFORE.search(before) or _CLAIM_AFTER.search(said[m.end():m.end() + 8])
        (marked if claimed else plain).setdefault((low, high), phrase)
    # A figure once given as a rate (or as the other side's) is one wherever else it appears.
    marked = {k: v for k, v in marked.items() if not set(k) & rates}
    plain = {k: v for k, v in plain.items() if not set(k) & rates}
    if len(marked) == 1:
        (low, high), phrase = next(iter(marked.items()))
        return ClaimAmount(low, high, phrase), ()
    if not marked and len(plain) == 1 and not vague:
        (low, high), phrase = next(iter(plain.items()))
        return ClaimAmount(low, high, phrase), ()
    return None, tuple(dict.fromkeys([*marked.values(), *plain.values(), *vague]))


def _track(amount: int, domain: str | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    """(程序, the verbatim lines it rests on) for a money claim of `amount`."""
    if amount <= 100_000:
        return "小額程序", (_SMALL_CLAIMS,)
    if amount <= 500_000:
        return "簡易程序", (_SUMMARY,)
    if domain == "traffic":
        return "簡易程序", (_SUMMARY_ANY_AMOUNT, _SUMMARY_TRAFFIC)
    return "通常程序", (_SUMMARY, _SUMMARY_ANY_AMOUNT)


def _fee_clauses(amount: int) -> str:
    """The §77-13 clauses `court_fee(amount)` used, each quoted on its own."""
    wan = -(-amount // 10_000) * 10_000
    clauses = [clause for low, _rate, clause in _FEE_BRACKETS if wan > low or low == 0]
    if wan > _FEE_BRACKETS[1][0] and amount % 10_000:
        clauses.append(_FEE_ODD)                  # rounding only moves a fee above 十萬
    return "「" + "」「".join(clauses) + "」"


def _quote(ref_and_text: tuple[str, str]) -> str:
    ref, text = ref_and_text
    return f"{ref}「{text}」"


def _litigation_rung(collected_facts: dict, domain: str | None) -> Rung:
    """The last rung, priced from the amount the user typed — or asking for it."""
    claim, phrases = claim_amount(collected_facts)
    free = f"對照:調解不用錢——{_quote(_FREE_MEDIATION)}"
    if claim is not None:
        track, basis = _track(claim.low, domain)
        if _track(claim.high, domain)[0] != track:
            claim, phrases = None, (claim.said,)
    if claim is None:
        ask = (f"你提到了好幾個金額(「{'」「'.join(phrases[:4])}」),不知道哪一個是你要請求的"
               if len(phrases) > 1 else f"你提到的「{phrases[0]}」不是確切的請求金額"
               if phrases else "你還沒說要向對方請求多少錢")
        return Rung(
            "litigation", "民事訴訟(最後手段)",
            "走哪種程序、裁判費多少,都由請求金額決定:十萬元以下小額程序"
            f"({_SMALL_CLAIMS[0]})、五十萬元以下簡易程序({_SUMMARY[0]})、其餘通常程序;"
            f"裁判費依{_FEE_ARTICLE}按金額級距計算。{free}",
            (_SMALL_CLAIMS[0], _SUMMARY[0], _FEE_ARTICLE, _FREE_MEDIATION[0]),
            "中~高", "數月以上", "高",
            f"{ask}——告訴我總金額(例如「8萬元」),才能算出適用的程序與裁判費;"
            "沒有金額就不算,免得猜錯",
            False, False,
        )
    low_fee, high_fee = court_fee(claim.low), court_fee(claim.high)
    ceiling = high_fee + high_fee // 2
    shown = (f"{claim.low:,} 元" if claim.low == claim.high
             else f"{claim.low:,}~{claim.high:,} 元")
    fee = f"{low_fee:,} 元" if low_fee == high_fee else f"{low_fee:,}~{high_fee:,} 元"
    what = (
        f"以你提到的「{claim.said}」({shown})計算,若這就是你要請求的金額:"
        f"適用{track}——{';'.join(_quote(b) for b in basis)}。"
        f"裁判費依{_FEE_ARTICLE}{_fee_clauses(claim.high)}算出 {fee};"
        f"高等法院可以再加徵,{_quote(_SURCHARGE)},所以實繳在 {low_fee:,}~{ceiling:,} 元之間,"
        "以法院通知為準。"
        f"請求的是金錢,也可以先聲請支付命令:{_quote(_PAYMENT_ORDER)},"
        f"{_PAYMENT_ORDER_FEE[0]}「{_PAYMENT_ORDER_FEE[1]}」「{_PAYMENT_ORDER_FEE_ITEM[1]}」;"
        f"但對方一提異議,{_quote(_PAYMENT_ORDER_OBJECTED)}。{free}"
    )
    refs = (*dict.fromkeys(b[0] for b in basis), _FEE_ARTICLE, _SURCHARGE[0],
            _PAYMENT_ORDER[0], _PAYMENT_ORDER_FEE[0], _PAYMENT_ORDER_OBJECTED[0],
            _FREE_MEDIATION[0])
    return Rung(
        "litigation", f"民事訴訟(最後手段):{track}",
        what, refs,
        f"裁判費 {low_fee:,}~{ceiling:,} 元(律師費另計)", "數月以上", "高",
        "把裁判費跟你能拿回的金額、要花的時間比一比再決定;要打就備齊證據寫起訴狀,"
        "沒把握先用上面的免費法律諮詢",
        False, False,
    )


def build_generic_ladder(collected_facts: dict, retrieved=None, cited=None,
                         domain: str | None = None,
                         stance: str | None = None) -> SolutionLadder:
    """Generic escalation ladder for non-noise problems (spec §3.4 fallback):
    same cheapest-first shape, no scenario-specific statutes baked in — the
    legal basis for a generic case is whatever Stage 3 retrieved, and the
    authority rung is named from those same retrieved statutes.

    `cited` is the (statute_id, article_no) pairs the ANSWER cited; when given, the
    deadline and the letter are drawn from those first."""
    retrieved = _answer_first(retrieved, cited)
    deadline = _deadline_for_stance(_deadline_rung(retrieved), stance)
    rungs = [
        Rung(
            "evidence", "蒐證與書面紀錄",
            "保存契約/對話紀錄/單據/照片,整理時間軸", (),
            "免費", "隨時", "低",
            _evidence_next_step(collected_facts) or "把事實與證據整理成一頁時間軸",
            False, bool(retrieved) and deadline is None,
        ),
        Rung(
            "negotiate", "正式溝通與存證信函",
            "以書面(LINE/email/存證信函)明確提出請求與期限", (),
            "低", "數天", "低",
            "照下方範本填好寄出(郵局存證信函一式三份),保留回執作為送達證明"
            if retrieved else "寄出書面請求,保留送達證明",
            False, False,
        ),
        *_DOMAIN_RUNGS.get(domain, [_GENERIC_MEDIATE]),
        _authority_rung(retrieved),
        # When retrieval came back EMPTY the honesty gate has just said the corpus
        # does not cover this, so the useful next step is a free consultation.
        replace(_LEGAL_AID_RUNG, recommended=not retrieved),
        _litigation_rung(collected_facts, domain),
    ]
    if deadline is not None:
        rungs.insert(0, deadline)

    note, letter = GENERIC_NOTE, _generic_letter(retrieved, collected_facts)
    if stance != "complainant":
        kept = []
        for rung in rungs:
            if rung.key in _ASSERTING_RUNGS:
                continue
            if "調解" in rung.title or "調處" in rung.title:
                rung = replace(rung, what_it_is=rung.what_it_is + _TWO_WAY_MEDIATION)
            kept.append(rung)
        # The recommendation may have gone with a dropped rung, and a ladder with
        # nothing flagged is better than one flagging a step that is no longer there.
        if not any(r.recommended for r in kept):
            for i, r in enumerate(kept):
                if not r.done:
                    kept[i] = replace(r, recommended=True)
                    break
        rungs = kept
        # The letter drafts one side's demand — see _generic_letter's docstring.
        note, letter = f"{NON_ASSERTING_NOTE}\n{GENERIC_NOTE}", None

    return SolutionLadder(
        rungs=rungs,
        note=note,
        letter_template=letter,
        also_retrieved=_also_retrieved_block(retrieved, cited),
    )


# ── The respondent's side ────────────────────────────────────────────────────
# The complainant's ladder, handed to the party being complained about, tells him
# to report himself (報警 with the 社維法§72 that fines him as 依據) and to sue the
# neighbour who complained. See evals/RESULTS.md §8.
#
# Nothing here is an inverted ladder. There is no cheapest-first escalation for
# someone who is not asserting a claim, and inventing one so there is something
# to print is how the wrong-side ladder came about in the first place. What a
# respondent can be given is what the statutes themselves say the complaining
# side must still establish — verbatim, with no conclusion attached.

# Words that mark a CONDITION inside an article rather than a penalty. Every one
# is readable off 社維法§72, 公寓大廈條例§16 and 民法§793 without seeing any case:
# 不聽禁止者 / 經制止而不遵從者 / 但其侵入輕微…不在此限 / 情節重大. 具名 comes from
# the police handling principle, which states who must identify themselves before
# a case is 移送法辦.
_THRESHOLD_WORDS = (
    "不聽禁止", "經制止", "不遵從", "不在此限", "情節重大", "具名", "限期",
)


def _threshold_sentences(retrieved) -> list[tuple[str, str]]:
    """(article ref, verbatim sentence) for every retrieved article whose own text
    states a condition. Quoted, never paraphrased, and never summed into a
    conclusion about whether the condition is met here."""
    out: list[tuple[str, str]] = []
    for statute in retrieved or []:
        ref = f"{statute.statute_id}{statute.article_no}"
        # Up to TWO sentences per article. 社維法§72 states 不聽禁止者 in both its
        # first clause (酗酒滋事、謾罵喧鬧) and its second (製造噪音或深夜喧嘩), and
        # taking one per article printed the first — a real condition, from the
        # wrong clause. Picking by which clause fits this case would be tuning
        # against the case; printing both is not.
        found = 0
        for sentence in re.split(r"[。\n]", statute.content or ""):
            if found >= 2:
                break
            if any(word in sentence for word in _THRESHOLD_WORDS):
                out.append((ref, sentence.strip()))
                found += 1
    return out


RESPONDENT_NOTE = (
    "你是被投訴的一方,所以這裡沒有列「下一步該做什麼」的階梯——這個工具的階梯是為"
    "提出投訴的一方寫的(報警、寄存證信函、聲請調解、提告),端給你會變成叫你對投訴你的"
    "人做這些事。空著並說明原因,好過給你反方向的指示。\n"
    "上面列的是條文自己寫的要件與原文,是否成立要看個案;本工具不會、也不能告訴你"
    "「這樣不會被罰」。重大爭議請諮詢律師。"
)


def build_respondent_ladder(collected_facts: dict, retrieved=None) -> SolutionLadder:
    """What a respondent can be given: the retrieved articles' own conditions,
    verbatim, plus the records he himself can keep. No escalation, no letter."""
    rungs: list[Rung] = []
    thresholds = _threshold_sentences(retrieved)
    if thresholds:
        quoted = ";".join(f"{ref}「{sentence}」" for ref, sentence in thresholds[:6])
        rungs.append(Rung(
            "thresholds", "先讀條文自己寫的要件(逐字)",
            f"以下要件出現在本案檢索到的條文原文中,逐字引用:{quoted}。"
            "這些是條文寫下的條件,不是本工具對你的案子的判斷",
            tuple(dict.fromkeys(ref for ref, _ in thresholds[:6])),
            "免費", "立刻", "低",
            "把上面每一句對照你的實際情形逐條看過;有疑問時以條文原文與律師意見為準",
            False, True,
        ))
    # A period in these articles is the OTHER side's clock, and that is exactly
    # how it is labelled. Handing a respondent 「你要在二年內…」 would be the same
    # error as the ladder: a deadline printed to the wrong party reads as an
    # instruction to act on it.
    deadlines = _deadline_sentences(_on_topic(retrieved))
    if deadlines:
        quoted = ";".join(f"{ref}「{sentence}」" for ref, sentence in deadlines[:3])
        rungs.append(Rung(
            "other_side_deadline", "對方主張權利的期間(條文原文)",
            f"以下期間出現在本案檢索到的條文原文中,逐字引用:{quoted}。"
            "這是對方主張權利的期間,不是你要做什麼的期限;起算日與是否中斷因個案而異",
            tuple(ref for ref, _ in deadlines[:3]),
            "免費", "立刻", "低",
            "把日期對照條文原文自己看過;本工具不判斷這段期間是否已經經過,"
            "也不代表期間經過就對你有利", False, False,
        ))
    rungs.append(Rung(
        "records", "保存你這一側的紀錄",
        "把已經發生的事寫下來並留存:何時被反映、誰來過、你當下在做什麼、你如何回應",
        (), "免費", "隨時", "低",
        _evidence_next_step(collected_facts)
        or "依時間順序記下每一次被反映的日期、對方說法、你的回應與改善作為,並保留書面或訊息紀錄",
        False, not thresholds,
    ))
    return SolutionLadder(
        rungs=rungs,
        note=RESPONDENT_NOTE,
        letter_template=None,      # the template accuses someone else of noise
        also_retrieved=None,
        header="你這一側可以做的事(這不是升級階梯,也不會叫你對投訴你的人採取行動):",
    )


def build_solution_ladder(collected_facts: dict, retrieved=None,
                          stance: str | None = None) -> SolutionLadder:
    """Build the ranked 住宅噪音 escalation ladder from the collected facts.

    Cheapest/lowest-effort first, litigation last; the 管委會 rung is included only
    for 公寓大廈; rungs already attempted are marked done and the first not-done rung
    is flagged as the recommended next step. `retrieved` supplies the deadline
    rung when it carries a time-limited article.

    `stance` is the seat the user is in. A respondent gets `build_respondent_ladder`
    instead — the rungs below are the complainant's actions, and handing them to
    the person being complained about tells him to report himself.
    """
    if stance == "respondent":
        return build_respondent_ladder(collected_facts, retrieved)

    facts = collected_facts or {}
    building_type = facts.get("building_type", "")
    actions_taken = facts.get("actions_taken", "")

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

    # A deadline is the only thing here that cannot be repaired once missed, so
    # it leads, exactly as it does in the generic ladder.
    deadline = _deadline_rung(retrieved)
    if deadline is not None:
        rungs = [deadline, *(replace(r, recommended=False) for r in rungs)]

    return SolutionLadder(
        rungs=rungs,
        note=EPA_NOTE,
        letter_template=LETTER_TEMPLATE,
    )
