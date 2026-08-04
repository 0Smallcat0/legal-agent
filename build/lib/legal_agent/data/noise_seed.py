"""Load the 9 human-verified 住宅噪音 statute articles into the corpus.

The verbatim 條文內容 and effective dates below were pulled from 全國法規資料庫
(law.moj.gov.tw) and human-verified. This module ONLY persists them — no
fetching, no paraphrasing, no reformatting. It reuses the existing write path
(cli.insert_statute) so the same validation/FK rules apply.

Idempotent: re-running skips any (statute_id, article_no, effective_from) that
already exists (catch sqlite3.IntegrityError) — never duplicates or overwrites.

All records: hierarchy_level = "法律", effective_to = None (current version).

Run:  python -m legal_agent.data.noise_seed
"""
from __future__ import annotations

import sqlite3

from legal_agent.cli import insert_statute
from legal_agent.config import DB_PATH
from legal_agent.data.database import connect, init_db
from legal_agent.data.models import Statute
from legal_agent.data.seed import seed_source_hierarchy

_BASE = "https://law.moj.gov.tw/LawClass/LawSingle.aspx"

# The 9 verified articles. Multi-line 條文內容 is written line-by-line with
# explicit "\n" so the exact newline structure is auditable; nothing is trimmed
# or reflowed. hierarchy_level / effective_to are constant per the task.
NOISE_STATUTES: list[Statute] = [
    Statute(
        statute_id="噪音管制法",
        article_no="第3條",
        content="本法所稱噪音，指超過管制標準之聲音。",
        effective_from="2008-12-03",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=O0030001&flno=3",
    ),
    Statute(
        statute_id="噪音管制法",
        article_no="第6條",
        content="製造不具持續性或不易量測而足以妨害他人生活安寧之聲音者，由警察機關依有關法規處理之。",
        effective_from="2008-12-03",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=O0030001&flno=6",
    ),
    Statute(
        statute_id="噪音管制法",
        article_no="第9條",
        content=(
            "噪音管制區內之下列場所、工程及設施，所發出之聲音不得超出噪音管制標準：\n"
            "一、工廠（場）。\n"
            "二、娛樂場所。\n"
            "三、營業場所。\n"
            "四、營建工程。\n"
            "五、擴音設施。\n"
            "六、其他經主管機關公告之場所、工程及設施。\n"
            "前項各款噪音管制之音量及測定之標準，由中央主管機關定之。"
        ),
        effective_from="2008-12-03",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=O0030001&flno=9",
    ),
    Statute(
        statute_id="社會秩序維護法",
        article_no="第72條",
        content=(
            "有下列各款行為之一者，處新臺幣一萬元以下罰鍰：\n"
            "一、於公共場所或公眾得出入之場所，酗酒滋事、謾罵喧鬧，不聽禁止者。\n"
            "二、製造噪音或深夜喧嘩，妨害公眾安寧，不聽禁止者。\n"
            "三、無正當理由，擅吹警笛或擅發其他警號者。"
        ),
        effective_from="2025-06-11",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=D0080067&flno=72",
    ),
    Statute(
        statute_id="公寓大廈管理條例",
        article_no="第16條",
        content=(
            "住戶不得任意棄置垃圾、排放各種污染物、惡臭物質或發生喧囂、振動及其他與此相類之行為。\n"
            "住戶不得於私設通路、防火間隔、防火巷弄、開放空間、退縮空地、樓梯間、共同走廊、防空避難設備等處所堆置雜物、設置柵欄、門扇或營業使用，或違規設置廣告物或私設路障及停車位侵占巷道妨礙出入。但開放空間及退縮空地，在直轄市、縣（市）政府核准範圍內，得依規約或區分所有權人會議決議供營業使用；防空避難設備，得為原核准範圍之使用；其兼作停車空間使用者，得依法供公共收費停車使用。\n"
            "住戶為維護、修繕、裝修或其他類似之工作時，未經申請主管建築機關核准，不得破壞或變更建築物之主要構造。\n"
            "住戶飼養動物，不得妨礙公共衛生、公共安寧及公共安全。但法令或規約另有禁止飼養之規定時，從其規定。\n"
            "住戶違反前四項規定時，管理負責人或管理委員會應予制止或按規約處理，經制止而不遵從者，得報請直轄市、縣（市）主管機關處理。"
        ),
        effective_from="2003-12-31",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=D0070118&flno=16",
    ),
    Statute(
        statute_id="公寓大廈管理條例",
        article_no="第47條",
        content=(
            "有下列行為之一者，由直轄市、縣（市）主管機關處新臺幣三千元以上一萬五千元以下罰鍰，並得令其限期改善或履行義務、職務；屆期不改善或不履行者，得連續處罰：\n"
            "一、區分所有權人會議召集人、起造人或臨時召集人違反第二十五條或第二十八條所定之召集義務者。\n"
            "二、住戶違反第十六條第一項或第四項規定者。\n"
            "三、區分所有權人或住戶違反第六條規定，主管機關受理住戶、管理負責人或管理委員會之請求，經通知限期改善，屆期不改善者。"
        ),
        effective_from="2003-12-31",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=D0070118&flno=47",
    ),
    Statute(
        statute_id="民法",
        article_no="第793條",
        content="土地所有人於他人之土地、建築物或其他工作物有瓦斯、蒸氣、臭氣、煙氣、熱氣、灰屑、喧囂、振動及其他與此相類者侵入時，得禁止之。但其侵入輕微，或按土地形狀、地方習慣，認為相當者，不在此限。",
        effective_from="2009-07-23",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=B0000001&flno=793",
    ),
    Statute(
        statute_id="民法",
        article_no="第195條",
        content=(
            "不法侵害他人之身體、健康、名譽、自由、信用、隱私、貞操，或不法侵害其他人格法益而情節重大者，被害人雖非財產上之損害，亦得請求賠償相當之金額。其名譽被侵害者，並得請求回復名譽之適當處分。\n"
            "前項請求權，不得讓與或繼承。但以金額賠償之請求權已依契約承諾，或已起訴者，不在此限。\n"
            "前二項規定，於不法侵害他人基於父、母、子、女或配偶關係之身分法益而情節重大者，準用之。"
        ),
        effective_from="2000-05-05",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=B0000001&flno=195",
    ),
    Statute(
        statute_id="民法",
        article_no="第184條",
        content=(
            "因故意或過失，不法侵害他人之權利者，負損害賠償責任。故意以背於善良風俗之方法，加損害於他人者亦同。\n"
            "違反保護他人之法律，致生損害於他人者，負賠償責任。但能證明其行為無過失者，不在此限。"
        ),
        effective_from="2000-05-05",
        effective_to=None,
        hierarchy_level="法律",
        source_url=f"{_BASE}?pcode=B0000001&flno=184",
    ),
]


def load_noise_statutes(conn: sqlite3.Connection) -> tuple[int, int]:
    """Insert each record via the existing write path; skip ones already present.

    Returns (inserted, skipped). A duplicate time-slice raises
    sqlite3.IntegrityError from insert_statute, which we swallow to stay idempotent.
    """
    inserted = 0
    skipped = 0
    for statute in NOISE_STATUTES:
        try:
            insert_statute(conn, statute)
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1
    return inserted, skipped


def main() -> int:
    init_db(DB_PATH)                     # tables exist
    conn = connect(DB_PATH)
    try:
        seed_source_hierarchy(conn)      # FK vocabulary exists (idempotent)
        inserted, skipped = load_noise_statutes(conn)
    finally:
        conn.close()
    print(f"inserted {inserted} / skipped {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
