"""Tests for the Stage 4 solution ladder (step 4c). Deterministic, no LLM.

Run:  python -m pytest tests/test_solution.py -q
"""
from __future__ import annotations

from legal_agent.dialogue.solution import (
    _deadline_sentences,
    build_generic_ladder,
    build_solution_ladder,
)


class _Article:
    """Minimal stand-in for a retrieved Statute: the ladder reads only these three."""

    def __init__(self, statute_id: str, article_no: str, content: str) -> None:
        self.statute_id = statute_id
        self.article_no = article_no
        self.content = content


# Verbatim from the corpus.
_949 = _Article(
    "民法", "第949條",
    "占有物如係盜贓、遺失物或其他非基於原占有人之意思而喪失其占有者，"
    "原占有人自喪失占有之時起二年以內，得向善意受讓之現占有人請求回復其物。",
)
_805 = _Article("民法", "第805條", "第二項報酬請求權，因六個月間不行使而消滅。")
_11_1 = _Article(
    "消費者保護法", "第11-1條",
    "企業經營者與消費者訂立定型化契約前，應有三十日以內之合理期間，供消費者審閱全部條款內容。",
)
_226 = _Article("民法", "第226條", "因可歸責於債務人之事由，致給付不能者，債權人得請求賠償損害。")
_950 = _Article(
    "民法", "第950條",
    "盜贓、遺失物或其他非基於原占有人之意思而喪失其占有之物，如現占有人由公開交易場所，"
    "或由販賣與其物同種之物之商人，以善意買得者，非償還其支出之價金，不得回復其物。",
)
_686 = _Article(
    "民法", "第686條",
    "合夥未定有存續期間，或經訂明以合夥人中一人之終身，為其存續期間者，各合夥人得聲明退夥，"
    "但應於兩個月前通知他合夥人。\n前項退夥，不得於退夥有不利於合夥事務之時期為之。\n"
    "合夥縱定有存續期間，如合夥人有非可歸責於自己之重大事由，仍得聲明退夥，不受前二項規定之限制。",
)
_125 = _Article("民法", "第125條", "請求權，因十五年間不行使而消滅。但法律所定期間較短者，依其規定。")
_RENT_7 = _Article(
    "租賃住宅市場發展及管理條例", "第7條",
    "押金之金額，不得逾二個月之租金總額。\n出租人應於租賃契約消滅，承租人返還租賃住宅及清償"
    "租賃契約所生之債務時，返還押金或抵充債務後之賸餘押金。",
)
_440 = _Article(
    "民法", "第440條",
    "承租人租金支付有遲延者，出租人得定相當期限，催告承租人支付租金，如承租人於其期限內不為支付，"
    "出租人得終止契約。\n租賃物為房屋者，遲付租金之總額，非達二個月之租額，不得依前項之規定，"
    "終止契約。其租金約定於每期開始時支付者，並應於遲延給付逾二個月時，始得終止契約。\n"
    "租用建築房屋之基地，遲付租金之總額，達二年之租額時，適用前項之規定。",
)
_RENT_12 = _Article(
    "租賃住宅市場發展及管理條例", "第12條",
    "租賃契約消滅時，租賃住宅之返還，應由租賃當事人共同完成屋況及附屬設備之點交。一方未會同點交，"
    "經他方定相當期限催告仍不會同者，視為完成點交。\n前項點交後尚有遺留物，除租賃當事人另有約定外，"
    "經出租人定相當期限催告仍不取回時，視為拋棄其所有權，其所需處理費用，得由押金扣除，不足者，"
    "出租人得請求承租人給付。",
)


def test_articles_the_answer_skipped_are_shown_to_the_reader():
    """The answer cites 20 of 56 retrieved articles and two attempts to make the 8B
    model cite more both backfired. The ones it skipped are printed instead."""
    ladder = build_generic_ladder(
        {"problem": "我買到贓車"}, [_949, _805], cited=[("民法", "第805條")]
    )
    assert ladder.also_retrieved
    assert "民法第949條" in ladder.also_retrieved
    assert "自喪失占有之時起二年以內" in ladder.also_retrieved   # verbatim
    assert "民法第805條" not in ladder.also_retrieved            # already discussed
    assert ladder.also_retrieved in ladder.render()


def test_an_article_with_a_period_leads_the_skipped_list():
    """Read end to end, the 買到贓車 page claimed his good faith defeated the claim and
    printed §949 — 二年以內…得請求回復其物 — three lines below, in the deadline rung
    only: §949 sat sixth in retrieval order and the list showed five."""
    window = [_11_1, _226, _805, _949]
    block = build_generic_ladder(
        {"problem": "我買到贓車"}, window, stance="complainant", cited=[("民法", "第226條")]
    ).also_retrieved
    first = block.split("・")[1]
    assert "民法第805條" in first or "民法第949條" in first
    assert "民法第949條" in block


def test_no_skipped_block_when_the_answer_cited_everything():
    ladder = build_generic_ladder(
        {"problem": "我買到贓車"}, [_949], cited=[("民法", "第949條")]
    )
    assert ladder.also_retrieved is None


def test_the_letter_quotes_what_the_answer_cited_not_what_headed_the_window():
    """買到贓車's letter quoted §950/§805/§807 — 遺失物拾得 — because they head the
    retrieval window. Retrieval order cannot tell whose right an article states; the
    answer's own citations can."""
    # §949 sits fourth, as it sat sixth in the real 買到贓車 window — outside the three
    # the letter quotes.
    window = [_805, _11_1, _226, _949]
    plain = build_generic_ladder({"problem": "我買到贓車"}, window, stance="complainant")
    focused = build_generic_ladder(
        {"problem": "我買到贓車"}, window, stance="complainant", cited=[("民法", "第949條")]
    )
    assert "自喪失占有之時起二年以內" not in plain.letter_template.split("四、")[0]
    assert "自喪失占有之時起二年以內" in focused.letter_template
    assert focused.rungs[0].key == "deadline"
    assert "民法第949條" in focused.rungs[0].what_it_is


def test_the_letter_template_is_rendered_and_quotes_the_law_verbatim():
    """Measured: 「見 letter_template」 pointed at something render() never printed and
    neither run.py nor app.py picked up — the reader was sent to a page that did not
    exist. The template now prints, and its 依據 lines are corpus text."""
    ladder = build_generic_ladder({"problem": "我買到贓車"}, [_949], stance="complainant")
    out = ladder.render()
    assert "存證信函範本" in out
    assert "非法律意見" in out
    assert "自喪失占有之時起二年以內" in out          # verbatim §949
    assert "與你情況不符者請自行刪去" in out


def test_the_letter_quotes_no_period_the_window_happened_to_carry():
    """退租押金's letter told the landlord 「另請台端注意」 民法§686 — 合夥人退夥 — because
    a 兩個月 in the window was the first period found. The period is the sender's
    own clock and stays in the ladder; the letter keeps only its three 依據.

    §950 heads the window as it heads the real 買到贓車 one, BM25 and hybrid."""
    window = [_950, _11_1, _226, _949]
    ladder = build_generic_ladder({"problem": "我買到贓車"}, window, stance="complainant")
    assert "另請台端注意" not in ladder.letter_template
    assert "自喪失占有之時起二年以內" not in ladder.letter_template
    assert ladder.rungs[0].key == "deadline"
    assert "民法第949條" in ladder.rungs[0].what_it_is


def test_the_letter_quotes_the_whole_article_so_its_proviso_goes_with_it():
    """The deposit visitor's letter quoted §432's first paragraph — the tenant's
    duty of care — and left out the 但書 that exempts ordinary wear."""
    _432 = _Article(
        "民法", "第432條",
        "承租人應以善良管理人之注意，保管租賃物，租賃物有生產力者，並應保持其生產力。\n"
        "承租人違反前項義務，致租賃物毀損、滅失者，負損害賠償責任。但依約定之方法或依物之"
        "性質而定之方法為使用、收益，致有變更或毀損者，不在此限。",
    )
    letter = build_generic_ladder(
        {"rent_issue": "退租扣押金"}, [_RENT_7, _432], stance="complainant",
    ).letter_template
    assert "致有變更或毀損者，不在此限。" in letter
    assert "返還押金或抵充債務後之賸餘押金。" in letter


def test_no_letter_template_without_retrieval():
    """Nothing retrieved, nothing to cite — the letter would be blanks around blanks."""
    assert build_generic_ladder({"problem": "我買到贓車"}, []).letter_template is None


def test_the_first_step_names_what_the_user_said_they_have():
    """Every session used to open with 「把事實與證據整理成一頁時間軸」, whether the
    reader had lost a moving box or a wedding video."""
    step = build_generic_ladder(
        {"problem": "我花六萬八請婚攝,合約寫明三個月交件,我有匯款紀錄跟LINE對話"}, [_949]
    ).rungs
    evidence = next(r for r in step if r.key == "evidence")
    assert "合約" in evidence.next_step
    assert "匯款紀錄" in evidence.next_step


def test_the_first_step_falls_back_when_the_user_named_nothing():
    """Nothing is suggested — a document is named only if the user typed it."""
    evidence = next(
        r for r in build_generic_ladder({"problem": "鄰居很吵"}, [_949]).rungs
        if r.key == "evidence"
    )
    assert evidence.next_step == "把事實與證據整理成一頁時間軸"


def test_a_review_period_is_not_offered_as_a_deadline():
    """消保法§11-1's thirty days is a period the SELLER owes, not one the reader can
    miss. It was heading the list for the 冷氣修四次 session."""
    assert _deadline_sentences([_11_1]) == []


def test_an_article_with_no_period_surfaces_no_deadline():
    assert _deadline_sentences([_226]) == []
    assert all(r.key != "deadline" for r in build_generic_ladder({}, [_226]).rungs)


def test_the_deadline_is_quoted_verbatim_and_leads_the_ladder():
    ladder = build_generic_ladder({}, [_949])
    assert ladder.rungs[0].key == "deadline"
    assert ladder.rungs[0].recommended
    assert "自喪失占有之時起二年以內" in ladder.rungs[0].what_it_is


def test_a_period_from_another_dispute_does_not_lead_the_ladder():
    """退租押金's recommended first step was 「先確認期限」 quoting 民法§686 — 合夥人
    應於兩個月前通知 — because a 兩個月 in the user's words pulled it into the window."""
    window = [_RENT_7, _440, _RENT_12, _686]
    ladder = build_generic_ladder({"problem": "房東扣押金"}, window, stance="complainant")
    assert all(r.key != "deadline" for r in ladder.rungs)
    assert "民法第686條" not in ladder.render()


def test_a_limitation_period_is_quoted_whatever_the_dispute():
    """時效 cuts across every kind of dispute, so it is kept from anywhere in the window."""
    window = [_RENT_7, _440, _RENT_12, _686, _125]
    deadline = build_generic_ladder({}, window, stance="complainant").rungs[0]
    assert deadline.key == "deadline"
    assert deadline.legal_basis == ("民法第125條",)

_COST_RANK = {"免費": 0, "低": 1, "中": 2, "高": 3}

APARTMENT = {"building_type": "公寓大廈,有管委會", "noise_type": "深夜喧嘩爭吵", "actions_taken": ""}
HOUSE = {"building_type": "透天厝,無管委會", "noise_type": "深夜喧嘩爭吵", "actions_taken": ""}


def _keys(ladder):
    return [r.key for r in ladder.rungs]


def test_apartment_includes_hoa_rung():
    assert "hoa" in _keys(build_solution_ladder(APARTMENT))


def test_house_omits_hoa_rung():
    ladder = build_solution_ladder(HOUSE)
    assert "hoa" not in _keys(ladder)
    assert "police" in _keys(ladder)   # the rest of the ladder remains


def test_litigation_is_last_and_cost_is_non_decreasing():
    for facts in (APARTMENT, HOUSE):
        ladder = build_solution_ladder(facts)
        assert ladder.rungs[-1].key == "litigation"       # sue last
        ranks = [_COST_RANK[r.cost] for r in ladder.rungs]
        assert ranks == sorted(ranks), f"cost not cheap->costly: {ranks}"


def test_epa_section9_note_is_present():
    ladder = build_solution_ladder(APARTMENT)
    assert "環保局" in ladder.note and "§9" in ladder.note


def test_recommended_is_first_rung_when_nothing_tried():
    ladder = build_solution_ladder(APARTMENT)
    recommended = [r for r in ladder.rungs if r.recommended]
    assert len(recommended) == 1 and recommended[0].key == "hoa"


def test_already_reported_marks_police_done_and_points_to_next():
    facts = {"building_type": "透天厝", "noise_type": "深夜喧嘩", "actions_taken": "已經報過警了,沒用"}
    ladder = build_solution_ladder(facts)
    police = next(r for r in ladder.rungs if r.key == "police")
    assert police.done is True                              # marked done
    recommended = [r for r in ladder.rungs if r.recommended]
    assert len(recommended) == 1 and recommended[0].key == "mediation"   # next rung highlighted


def test_costs_stay_qualitative_no_ntd():
    ladder = build_solution_ladder(APARTMENT)
    for r in ladder.rungs:
        assert r.cost in {"免費", "低", "中", "高"}   # no invented NT$ figures


def test_letter_template_is_clearly_a_template():
    ladder = build_solution_ladder(APARTMENT)
    assert ladder.letter_template and "範本" in ladder.letter_template
    assert "非法律意見" in ladder.letter_template


def test_render_contains_note_and_orders_rungs():
    text = build_solution_ladder(APARTMENT).render()
    assert "環保局" in text
    assert text.index("反映管理委員會") < text.index("民事訴訟")   # cheap before litigation


# ── Generic ladder: name the window, and say free help exists ────────────────
def _statute(sid):
    from legal_agent.data.models import Statute

    return Statute(sid, "第1條", "內容", "2020-01-01", None, "法律", "http://x")


def test_authority_rung_is_named_from_the_retrieved_statute():
    from legal_agent.dialogue.solution import build_generic_ladder

    labour = build_generic_ladder({}, stance="complainant", retrieved=[_statute("勞動基準法")]).render()
    assert "勞工局" in labour and "勞資爭議調解" in labour

    consumer = build_generic_ladder({}, stance="complainant", retrieved=[_statute("消費者保護法")]).render()
    assert "1950" in consumer

    rental = build_generic_ladder({}, stance="complainant", retrieved=[_statute("租賃住宅市場發展及管理條例")]).render()
    assert "住宅" in rental and "調處" in rental


def test_authority_rung_falls_back_when_the_domain_is_unknown():
    from legal_agent.dialogue.solution import build_generic_ladder

    text = build_generic_ladder({}, stance="complainant", retrieved=[_statute("民法")]).render()
    assert "主管機關申訴/檢舉" in text


def test_refusal_recommends_the_free_consultation_not_evidence_gathering():
    # When retrieval came back empty the user has just been told 「這個問題我的
    # 資料庫沒有涵蓋」 — pointing at 蒐證 as the next step answers nothing.
    from legal_agent.dialogue.solution import build_generic_ladder

    refused = build_generic_ladder({}, stance="complainant", retrieved=[]).render()
    recommended = [line for line in refused.splitlines() if "建議下一步" in line]
    assert recommended and "法律扶助" in recommended[0]

    answered = build_generic_ladder({}, stance="complainant", retrieved=[_statute("勞動基準法")]).render()
    recommended = [line for line in answered.splitlines() if "建議下一步" in line]
    assert recommended and "蒐證" in recommended[0]


def test_generic_ladder_offers_free_legal_help_before_litigation():
    from legal_agent.dialogue.solution import build_generic_ladder

    text = build_generic_ladder({}, stance="complainant").render()
    assert "法律扶助" in text
    assert text.index("法律扶助") < text.index("民事訴訟")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
