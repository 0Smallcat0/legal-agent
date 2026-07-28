"""Tests for the 口語→法條語彙 expansion table (retrieval/lexicon.py).

The table's VALUE is measured by the golden set (evals/RESULTS.md); these
tests pin its CONTRACT: additive only, verbatim-grounded, and silent when the
feature is off.

Run:  python -m pytest tests/test_lexicon.py -q
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from legal_agent.retrieval.lexicon import LEXICON, expand, expansions  # noqa: E402


def test_expansion_is_additive_never_replacing():
    original = "樓上半夜很吵,我失眠想求償"
    out = expand(original)
    assert out.startswith(original)      # user's words stay verbatim, in front
    assert len(out) > len(original)      # and statutory vocabulary was added


def test_untriggered_text_is_returned_unchanged():
    # a query with no everyday trigger must not be widened at all
    assert expand("商標搶註") == "商標搶註"
    assert expansions("商標搶註") == []


def test_everyday_words_reach_statutory_vocabulary():
    # the gap the table exists to close: the user's word never appears in the
    # article, the article's word never appears in the query
    assert "非財產上之損害" in expansions("我要請求精神賠償")
    assert "延長工作時間之工資" in expansions("公司不給加班費")
    assert "通訊交易" in expansions("網購想退貨")
    assert "按人數平均繼承" in expansions("父親過世遺產怎麼分")


def test_co_ownership_survives_a_passing_mention_of_inheritance():
    """Measured defect: 「我跟哥哥一人一半繼承了一間房子,我想賣他不肯」 filled its
    whole window with 繼承編 (§1138–§1176) off the single word 繼承. The question
    is partition of co-owned property; 繼承 only says how they got it."""
    out = expansions("我跟哥哥一人一半繼承了一間房子,我想賣掉分錢,他堅持不賣還自己住在裡面")
    assert "得隨時請求分割共有物" in out              # §823 — the actual remedy
    assert "按其應有部分，對於共有物之全部，有使用收益之權" in out   # §818 — the price of sole use
    assert "按人數平均繼承" in out                    # the inheritance row still fires


def test_how_much_do_i_owe_reaches_the_measure_of_damages():
    """Measured: 「我到底該賠多少」 for a scratched car returned 道路交通管理處罰
    條例 penalty articles — administrative fines, not what one driver owes
    another. Liability and the SIZE of it are different questions."""
    out = expansions("我擦撞到別人的車只有一道刮痕,對方要我賠八萬還算停業損失,我到底該賠多少")
    assert "不法毀損他人之物者，被害人得請求賠償其物因毀損所減少之價額" in out   # §196
    assert "可得預期之利益，視為所失利益" in out                                # §216
    assert "損害之發生或擴大，被害人與有過失者，法院得減輕賠償金額" in out       # §217


def test_renovation_reaches_the_contract_for_work_chapter():
    """Measured: 「師傅裝修廚房,水管沒接好會漏水,還催我付尾款」 returned the
    tenancy and 相鄰關係 chapters off the word 漏水. Nobody in that story is a
    tenant; 承攬 is its own chapter and answers the whole question."""
    out = expansions("我找師傅裝修廚房,做完發現水管沒接好會漏水,他還一直催我付尾款")
    assert "定作人得定相當期限，請求承攬人修補之" in out              # §493
    assert "定作人得解除契約或請求減少報酬" in out                    # §494


def test_a_pay_deduction_reaches_the_article_that_forbids_it():
    out = expansions("公司說我遲到還打破設備,直接從薪水扣了八千")
    assert "雇主不得預扣勞工工資作為違約金或賠償費用" in out           # 勞基§26

    # 違約金 alone must NOT reach it: the same word appears in every contract
    # dispute, and a labour article has no business in those windows.
    assert "雇主不得預扣勞工工資作為違約金或賠償費用" not in expansions(
        "契約寫違約金十萬,對方要我付"
    )


def test_earnest_money_and_the_limitation_clock_are_reachable():
    """Two questions ordinary people ask first, neither of which the liability
    articles answer: 「斡旋金拿得回來嗎」 and 「這麼久了還來得及嗎」."""
    deposit = expansions("我付了十萬斡旋金,屋主後來不賣了,想全額拿回來")
    assert "由他方受有定金時，推定其契約成立" in deposit                       # §248
    assert "契約因可歸責於受定金當事人之事由" in deposit                        # §249

    late = expansions("三年前有人騎車撞到我,現在還能跟他求償嗎?來不來得及")
    assert any("二年間不行使而消滅" in term for term in late)                  # §197
    assert "消滅時效，因左列事由而中斷" in late                                 # §129


def test_a_landlord_letting_himself_in_has_a_civil_side_too():
    """刑§306 was the only article the trespass row carried, so a tenant asking
    「房東自己開門進我房間,算侵犯我的權利嗎」 got the criminal answer and nothing
    civil. §423 is the promise a tenancy makes about exclusive use."""
    out = expansions("房東沒有事先講就自己開門進我房間,他說他有備份鑰匙想進就進")
    assert "無故侵入他人住宅" in out                       # 刑§306
    assert "保持其合於約定使用、收益之狀態" in out          # 民法§423


def test_asking_whether_someone_must_pay_reaches_the_tort_clause():
    # 「我可以要求他賠嗎」 matched nothing: 賠 only existed inside 賠償 and 賠錢.
    assert "因故意或過失，不法侵害他人之權利者" in expansions(
        "樓上水管破裂漏到我家,天花板整片壞掉,我可以要求他賠嗎"
    )
    # Bare 賠 stays out of the trigger list — only the forms that name the other
    # party do — so a contract clause about 賠付 does not drag in tort articles.
    assert "因故意或過失，不法侵害他人之權利者" not in expansions("違約金賠付方式怎麼寫")


def test_money_sent_by_mistake_reaches_unjust_enrichment():
    """返還不當得利 is the 12th most common 案由 in the harvested judgments and the
    session set had never covered it: 「轉帳打錯,三萬匯給不認識的人」 was refused at
    資料不足 while 民法§179 sat in the corpus saying exactly that."""
    out = expansions("我網銀轉帳打錯帳號,三萬塊匯給一個不認識的人,他說錢已經花掉了不還我")
    assert "無法律上之原因而受利益，致他人受損害者，應返還其利益" in out   # §179
    assert "受領人於受領時，知無法律上之原因或其後知之者" in out          # §182


def test_a_living_parent_reaches_guardianship_not_inheritance():
    out = expansions("我爸失智兩年,連我都認不得,弟弟拿他存摺印章把錢領走說是爸爸同意的")
    assert "受監護宣告之人，無行為能力" in out                        # §15
    assert "其意思表示，係在無意識或精神錯亂中所為者亦同" in out       # §75 — 「他同意的」
    assert "法院得因本人、配偶、四親等內之親屬" in out                 # §14


def test_an_old_debt_reaches_the_articles_that_size_it():
    """§125/§129/§144 answer 「還要不要還」; §126 and §205 answer 「還多少」 — interest
    runs on a five-year clock and anything over 16% a year is void."""
    out = expansions("十五年前的卡債,本金八萬,剩下都是利息跟違約金,資產管理公司來催收")
    assert "其各期給付請求權，因五年間不行使而消滅" in out             # §126
    assert "約定利率，超過週年百分之十六者，超過部分之約定，無效" in out  # §205


def test_expansions_are_deduplicated_and_ordered():
    # 「失眠」 appears in two entries; its shared terms must not repeat
    out = expansions("失眠又要賠償")
    assert len(out) == len(set(out))


def test_every_statutory_term_appears_verbatim_in_the_corpus():
    """The discipline that makes this table trustworthy: the statutory side is
    COPIED from real article text, never invented. Checked against the live
    corpus when one exists (skipped in a bare checkout)."""
    from legal_agent.config import DB_PATH

    if not Path(DB_PATH).exists():
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT content FROM statutes").fetchall()
    finally:
        conn.close()
    if not rows:
        return
    corpus = "\n".join(r[0] for r in rows)
    missing = [
        term
        for _triggers, statutory in LEXICON
        for term in statutory
        if term not in corpus
    ]
    assert not missing, f"not verbatim in any article: {missing}"
