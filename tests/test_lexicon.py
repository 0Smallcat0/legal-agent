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


def test_an_adult_asked_to_support_an_absent_parent():
    """「我爸五歲就離家沒付過扶養費,現在中風要我付安養費」 returned the 未成年子女
    監護 chapter. The asker is 38; §1118-1 is the article that answers them."""
    out = expansions("我爸在我五歲就離家沒付過扶養費,現在中風住院社工要我付安養費")
    assert "得請求法院減輕其扶養義務" in out                      # §1118-1
    assert "對負扶養義務者無正當理由未盡扶養義務" in out          # §1118-1 第2款
    assert "左列親屬，互負扶養之義務" in out                      # §1114


def test_divorce_is_reachable_at_all():
    """「老公外遇還動手,我想離婚他死不肯簽」 was REFUSED at 資料不足 while §1052
    lists nine grounds — none of which needs the other side to agree."""
    out = expansions("我老公外遇還動手打我,我想離婚他死不肯簽")
    assert "夫妻之一方，有下列情形之一者，他方得向法院請求離婚" in out   # §1052
    assert "對於未成年子女權利義務之行使或負擔" in out                  # §1055


def test_disclaiming_an_inheritance_reaches_the_deadline():
    # The asker literally asked 「有沒有期限」 and the three-month article was absent.
    out = expansions("我爸過世留下債務,銀行說貸款要我們還,聽說可以拋棄繼承")
    assert "應於知悉其得繼承之時起三個月內，以書面向法院為之" in out      # §1174
    assert "繼承人對於被繼承人之債務，以因繼承所得遺產為限，負清償責任" in out  # §1148


def test_being_fired_reaches_whether_it_was_allowed_at_all():
    """「叫我今天別來,理由是態度不佳」 returned §16/§17/§20 — how much severance —
    which quietly concedes the dismissal was valid. §11 is the exhaustive list of
    grounds, and 態度不佳 is not on it."""
    out = expansions("公司叫我今天就別來了,理由是態度不佳跟主管不合,能不能要求回去上班")
    assert "非有左列情事之一者，雇主不得預告勞工終止勞動契約" in out    # 勞基§11
    assert "勞工有左列情形之一者，雇主得不經預告終止契約" in out        # 勞基§12


def test_an_encroaching_wall_reaches_the_right_to_have_it_removed():
    out = expansions("鄰居把圍牆蓋進我家土地五十公分,地政測量確認越界,他不肯拆")
    assert "土地所有人建築房屋非因故意或重大過失逾越地界者" in out       # §796
    assert "所有人對於無權占有或侵奪其所有物者，得請求返還之" in out     # §767


def test_an_instalment_demand_is_capped_by_the_article_that_caps_it():
    out = expansions("刷分期三十期上了三期想停,業者說要一次付完剩下的二十七期")
    assert "除買受人遲付之價額已達全部價金五分之一外" in out            # §389

    # …but a voucher session that merely MENTIONS paying by instalment must not
    # be dragged in: 「刷卡分期還有六期沒繳完」 cost 民法§256 its seat once.
    assert "除買受人遲付之價額已達全部價金五分之一外" not in expansions(
        "美容店買了三萬元療程套票,做兩次店就關門了,當時刷卡分期還有六期沒繳完"
    )


def test_arrears_reach_the_article_the_committee_is_suing_under():
    out = expansions("管委會說我欠三年管理費要告我,含滯納金六萬多")
    assert "經定相當期間催告仍不給付者，管理負責人或管理委員會得訴請法院命其給付" in out  # §21
    assert "共用部分、約定共用部分之修繕、管理、維護，由管理負責人或管理委員會為之" in out  # §10

    # 管委會 alone must NOT fire it: it appears in most noise sessions, where this
    # row's phrases took the seats 社維法§72 needed — golden fell 19 -> 17 once.
    assert not any("管理負責人或管理委員會得訴請法院" in term
                   for term in expansions("樓上很吵,我跟管委會反映過好幾次都沒用"))


def test_unpaid_goods_reach_the_duty_to_pay():
    """「出貨三批四十幾萬,對方拖了快一年」 was REFUSED at 資料不足."""
    out = expansions("出貨給一家公司三批貨四十幾萬,月結六十天,對方拖著不付款")
    assert "買受人對於出賣人，有交付約定價金及受領標的物之義務" in out   # §367
    assert "債權人得請求依法定利率計算之遲延利息" in out                # §233


def test_estate_partition_uses_the_estate_article():
    """§1164 belongs in the inheritance row, not the co-ownership one — putting it
    there cost oos-02-inheritance its 民法§1141 (golden 19 -> 18)."""
    assert "繼承人得隨時請求分割遺產" in expansions("我爸過世三年遺產一直沒分,哥哥不肯談")
    # the general co-ownership question is unaffected and still gets §823
    assert "得隨時請求分割共有物" in expansions("房子我跟哥哥各二分之一,我想賣他不肯")


def test_a_driver_on_duty_puts_the_employer_on_the_hook():
    """「貨運公司的車送貨時撞到我,司機叫我找公司」 got the driver's liability and its
    size, and nothing about WHO to sue — which was the whole question."""
    out = expansions("貨運公司的貨車送貨時撞到我,司機說他只是員工叫我找公司")
    assert "受僱人因執行職務，不法侵害他人之權利者，由僱用人與行為人連帶負損害賠償責任" in out  # §188
    assert "數人共同不法侵害他人之權利者，連帶負損害賠償責任" in out                        # §185


def test_an_excessive_penalty_reaches_the_article_that_cuts_it():
    # 消保§12 and 民法§247-1 ask whether the clause is VOID; §252 is what a court
    # does with one that is merely excessive.
    assert "約定之違約金額過高者，法院得減至相當之數額" in expansions(
        "健身房提前解約要付剩餘期數再加三萬違約金"
    )


def test_being_talked_into_signing_reaches_rescission():
    """「櫃姐說是體驗紀錄,結果是兩年療程契約」 was REFUSED at 資料不足."""
    out = expansions("櫃姐說免費體驗,叫我簽同意書,結果是兩年二十四期的療程契約,沒給我看內容")
    assert "因被詐欺或被脅迫而為意思表示者，表意人得撤銷其意思表示" in out   # §92
    assert "應於發見詐欺或脅迫終止後，一年內為之" in out                    # §93


def test_a_debtor_moving_assets_reaches_the_revocation_right():
    """「他欠我一百萬,查到上個月把名下唯一的房子過戶給兒子」 returned the 消費借貸
    articles — he owes me — and nothing about undoing the transfer."""
    out = expansions("欠我一百萬的人把名下唯一的房子過戶給他兒子說是贈與")
    assert "債務人所為之無償行為，有害及債權者，債權人得聲請法院撤銷之" in out   # §244
    assert "債務人怠於行使其權利時，債權人因保全債權" in out                    # §242


def test_an_agent_who_kept_the_money_reaches_the_mandate_chapter():
    out = expansions("我委託代辦幫我處理修繕補助,給了八萬代辦費,他沒送件也不退錢")
    assert "受任人因處理委任事務，所收取之金錢、物品及孳息，應交付於委任人" in out  # §541
    assert "當事人之任何一方，得隨時終止委任契約" in out                          # §549

    # Bare 委任 is not a trigger: 「爸爸沒有立過任何委任或授權書」 said in passing
    # cost the dementia session its 民法§14 once.
    assert not any("受任人因處理委任事務" in term for term in expansions(
        "我爸重度失智,沒有立過任何委任或授權書,弟弟把他的錢領走"
    ))


def test_a_neighbour_wanting_it_fixed_reaches_restitution():
    """「隔壁施工把我家牆壁震出裂縫,對方說給五萬了事」 returned the 承攬 chapter off
    the word 施工 — the asker is the NEIGHBOUR, not the person who hired anyone."""
    out = expansions("隔壁施工把我家牆壁震出裂縫,對方說給五萬了事,我要的是修回原狀")
    assert "應回復他方損害發生前之原狀" in out                               # §213
    assert "債權人得請求支付回復原狀所必要之費用，以代回復原狀" in out         # §213 III


def test_a_joint_debtor_reaches_what_happens_after_paying():
    out = expansions("三個人一起簽的借據寫連帶債務人,債主只找我一個要全部,付了能不能跟他們要")
    assert "連帶債務之債權人，得對於債務人中之一人或數人或其全體" in out       # §273
    assert "得向他債務人請求償還各自分擔之部分" in out                        # §281


def test_a_divorce_does_not_end_the_duty_to_a_child():
    """「前夫說監護權判給我他就不用付扶養費」 put §1118-1 — how to REDUCE a
    maintenance duty — at rank 1, the opposite of what this asker needs."""
    out = expansions("離婚後前夫說監護權判給我,他就沒有義務再付扶養費,一年多沒給了")
    assert "父母對於未成年子女之扶養義務，不因結婚經撤銷或離婚而受影響" in out   # §1116-2


def test_a_resolution_passed_without_notice_reaches_both_halves():
    out = expansions("管委會開會決議每戶加收兩萬,我完全沒收到開會通知")
    assert "應由召集人於開會前十日以書面載明開會內容，通知各區分所有權人" in out  # 條例§30
    assert "社員得於決議後三個月內請求法院撤銷其決議" in out                     # 民法§56


def test_a_thing_repaired_four_times_reaches_incomplete_performance():
    out = expansions("裝好的冷氣一直漏水,修了四次還是壞,保固快過了")
    assert "因可歸責於債務人之事由，致為不完全給付者" in out              # §227
    assert "因不完全給付而生前項以外之損害者，債權人並得請求賠償" in out   # §227 II


def test_one_co_owner_can_sue_an_outsider_alone():
    """「共有地被工廠堆廢棄物,堂哥說懶得管,我一個人能不能告」 — the row reached the
    articles co-owners use against EACH OTHER and none about outsiders."""
    assert "各共有人對於第三人，得就共有物之全部為本於所有權之請求" in expansions(
        "我跟堂哥各持分一半的空地被工廠堆廢棄物,堂哥不配合,我一個人能不能告"
    )


def test_a_sham_sale_is_void_before_it_is_revocable():
    out = expansions("他把店面賣給老婆的弟弟,價金市價三成又沒有金流,這種假買賣能不能打掉")
    assert "表意人與相對人通謀而為虛偽意思表示者，其意思表示無效" in out          # §87
    assert "債務人所為之無償行為，有害及債權者，債權人得聲請法院撤銷之" in out    # §244


def test_an_impostor_account_reaches_the_right_to_stop_it():
    """「有人用我的照片跟名字開假帳號到處借錢」 returned the 消費借貸 chapter — 借錢
    is what the impostor does, not what the asker is asking about."""
    out = expansions("有人用我的照片跟名字開假帳號,到處加我朋友借錢,我想讓他停止")
    assert "人格權受侵害時，得請求法院除去其侵害" in out                        # §18
    assert "姓名權受侵害者，得請求法院除去其侵害，並得請求損害賠償" in out       # §19


def test_a_spite_wall_reaches_abuse_of_right():
    # The wall is on HIS OWN land and crosses nothing, so 越界建築 does not apply.
    assert "權利之行使，不得違反公共利益，或以損害他人為主要目的" in expansions(
        "隔壁在自己地上砌三米高的牆擋我的光,他那邊根本沒在用,就是要讓我不好過"
    )


def test_inherited_property_must_be_registered_before_it_is_sold():
    """「三個繼承人都同意賣,代書說還沒辦繼承登記不能賣」 returned the
    estate-DIVISION articles and not the one that says why the 代書 is right."""
    assert "於登記前已取得不動產物權者，應經登記，始得處分其物權" in expansions(
        "我媽過世留下的房子還沒辦繼承登記,代書說不能賣,一定要先登記嗎"
    )                                                                    # §759


def test_a_disputed_clause_reaches_how_contracts_are_read():
    # Triggers are the words the session used — 「該用誰的解釋」,「業務講的」 —
    # not 「文字含糊」, which is how a label describes it, not how a person says it.
    out = expansions("合約只寫每年保養兩次,業務講的是上下半年各一次,到底該用誰的解釋")
    assert "解釋意思表示，應探求當事人之真意，不得拘泥於所用之辭句" in out   # §98
    assert "當事人互相表示意思一致者，無論其為明示或默示，契約即為成立" in out  # §153


def test_two_debts_reach_set_off():
    """「我借他三十萬他沒還,我也欠他二十萬貨款,可以互相抵掉嗎」 returned the loan and
    sale articles — both debts, neither answer."""
    out = expansions("我借給合夥人三十萬他沒還,我也欠他二十萬貨款,可以互相抵掉只還差額嗎")
    assert "抵銷，應以意思表示，向他方為之" in out                                    # §335
    assert any("互為抵銷" in term for term in out)                                    # §334


def test_a_waiver_of_statutory_minimums_is_void():
    """「自願不加勞保、自願放棄加班費」 returned §24/§32/§36/§39 — how overtime is
    CALCULATED — which quietly assumes the waiver worked."""
    out = expansions("公司要我簽同意書自願不加勞保也自願放棄加班費,不簽就不錄用,算不算數")
    assert "法律行為，違反強制或禁止之規定者，無效" in out                    # §71
    assert "雇主與勞工所訂勞動條件，不得低於本法所定之最低標準" in out         # 勞基§1


def test_a_paternity_question_is_not_a_divorce_question():
    # 「我們正在談離婚」 in the same story pulled the whole window into 離婚.
    assert "夫妻之一方或子女能證明子女非為婚生子女者，得提起否認之訴" in expansions(
        "婚姻中生的小孩做了親子鑑定不是我的,戶政還登記我是父親,想解除父子關係"
    )                                                                        # §1063


def test_stepping_in_for_an_absent_neighbour_reaches_negotiorum_gestio():
    out = expansions("樓上出國水管爆了漏到我家,我只好自己找水電修好,花了兩萬八想跟他要")
    assert "管理事務，利於本人，並不違反本人明示或可得推知之意思者" in out   # §176

    # 聯絡不上 is NOT a trigger: it is said whenever anyone has gone quiet, and it
    # cost a prepaid-voucher session its 民法§256 for one run.
    assert not any("管理事務，利於本人" in term for term in expansions(
        "美容店買了三萬元療程套票,做兩次店就關門,老闆也聯絡不上"
    ))


def test_joint_ownership_consent_is_not_the_partition_question():
    out = expansions("三兄妹的房子,大哥說他不同意就不能租,兩個人同意能不能就出租")
    assert "公同共有物之處分及其他之權利行使，除法律另有規定外，應得公同共有人全體之同意" in out  # §828

    # Bare 公同共有 is NOT a trigger: every estate is 公同共有 before it is divided,
    # and it cost a partition session its 民法§1164.
    assert not any("應得公同共有人全體之同意" in term for term in expansions(
        "我爸過世三年遺產一直沒分,登記三個人公同共有,我想把遺產分一分"
    ))


def test_deliberate_concealment_costs_more_than_a_mistake():
    """「業者自己的單子早就知道是泡水車」 reached 瑕疵擔保 and nothing about the
    asker's actual question — whether deliberate deceit costs the seller more."""
    assert "因企業經營者之故意所致之損害，消費者得請求損害額五倍以下之懲罰性賠償金" in expansions(
        "二手車業者說沒泡過水,他們自己的單子早就知道,他們是故意的,能不能多要一些"
    )                                                                    # 消保§51


def test_being_told_to_stay_home_does_not_cost_the_wage():
    assert "僱用人受領勞務遲延者，受僱人無補服勞務之義務，仍得請求報酬" in expansions(
        "公司叫我先不用來上班在家等通知,兩個月只給一半薪水,說我沒來上班"
    )                                                                        # §487


def test_a_co_debtor_paying_releases_the_others():
    out = expansions("我是連帶保證人,朋友說他已經全部還清了,銀行還是寄存證信函來要我還")
    assert any("他債務人亦同免其責任" in term for term in out)                # §274

    # 求償 is not a trigger: it is said in every compensation question and once
    # displaced 民法§197/§129 from a limitation-period session.
    assert not any("他債務人亦同免其責任" in term for term in expansions(
        "三年前有人騎車撞到我,現在我還能跟他求償嗎"
    ))


def test_shared_part_repairs_reach_who_pays():
    out = expansions("頂樓平台防水層破了漏到我家,管委會說要大家分攤,這筆錢到底誰要出錢")
    assert "共用部分、約定共用部分之修繕、管理、維護，由管理負責人或管理委員會為之" in out  # 條例§10
    assert "共有部分之修繕費及其他負擔" in out                                        # 民法§799-1


def test_a_seal_used_without_permission_is_not_my_contract():
    """「兒子拿我的印章跟裝潢公司簽了六十萬」 returned the whole 承攬 chapter — the
    asker is not a party to anything yet."""
    out = expansions("我兒子拿我的印章去跟裝潢公司簽約,簽名不是我簽的,我完全不知情")
    assert "無代理權人以代理人之名義所為之法律行為，非經本人承認，對於本人不生效力" in out  # §170
    assert "無代理權人，以他人之代理人名義所為之法律行為，對於善意之相對人，負損害賠償之責" in out  # §110


def test_a_guarantor_set_off_is_capped_at_the_share():
    assert any("以該債務人應分擔之部分為限，得主張抵銷" in term for term in expansions(
        "我是連帶保證人,債權人自己也欠我表哥八十萬貨款,我能不能拿來抵"
    ))                                                                    # §277


def test_an_unborn_child_already_counts():
    assert "胎兒以將來非死產者為限，關於其個人利益之保護，視為既已出生" in expansions(
        "先生過世我懷孕七個月,婆家說小孩還沒出生不算繼承人,遺產要先分一分"
    )                                                                    # §7


def test_a_ten_year_disappearance_reaches_the_declaration_of_death():
    """「我爸十年前出門就沒再回來,戶政說要先有死亡宣告」 returned the whole 繼承編 —
    the step BEFORE any of it was missing."""
    out = expansions("我爸十年前出門就沒再回來,報警協尋沒消息,要怎麼辦死亡宣告,要等多久")
    assert "失蹤人失蹤滿七年後，法院得因利害關係人或檢察官之聲請，為死亡之宣告" in out  # §8
    assert "受死亡宣告者，以判決內所確定死亡之時，推定其為死亡" in out                # §9


def test_a_mandate_that_ended_midway_reaches_its_own_articles():
    """A separate row rather than five phrases in the existing 委任 one: that row
    is at three seats already, and stuffing it would only move the loss."""
    out = expansions("代書辦到一半過世了,先付的六萬能不能拿回來,還是做多少算多少")
    assert "委任關係，因當事人一方死亡、破產或喪失行為能力而消滅" in out              # §550
    assert "委任關係，因非可歸責於受任人之事由，於事務處理未完畢前已終止者" in out    # §548

    # …and the still-running mandate session keeps its own articles.
    running = expansions("我委託代辦幫我處理修繕補助,給了八萬代辦費,他沒送件也不退錢")
    assert "受任人因處理委任事務，所收取之金錢、物品及孳息，應交付於委任人" in running  # §541


def test_a_seller_who_keeps_delaying_reaches_the_way_out():
    out = expansions("合約寫兩個月交貨,拖了五個月一直說缺料,我不想等了想解約拿回訂金")
    assert any("得定相當期限催告其履行" in term for term in out)            # §254


def test_withholding_payment_until_delivery_is_a_right():
    assert "因契約互負債務者，於他方當事人未為對待給付前，得拒絕自己之給付" in expansions(
        "合約寫安裝完成後付尾款,他說要先收錢才願意來裝,我可以堅持裝好再付嗎"
    )                                                                    # §264


def test_a_five_household_meeting_reaches_the_threshold():
    out = expansions("三十二戶的社區只有五戶出席就通過動用三百萬,這個決議有沒有效")
    assert any("三分之二以上出席" in term for term in out)                 # 條例§31
    assert "召集人得就同一議案重新召集會議" in out                          # 條例§32


def test_a_notice_that_cannot_be_delivered_reaches_public_service():
    """「存證信函被退回招領逾期,我想催告他還錢但根本送不到」 returned the 消費借貸
    chapter — the debt, not the delivery problem."""
    assert "表意人非因自己之過失，不知相對人之姓名、居所者，得依民事訴訟法公示送達之規定" in expansions(
        "存證信函寄到戶籍地被退回招領逾期,人搬走不知道去哪,要怎麼合法通知他"
    )                                                                    # §97


def test_a_partly_capable_parent_reaches_the_middle_setting():
    # §15-2 is the setting between full capacity and monitorship; the row fires
    # even though the 監護宣告 row still wins the first seat on table order.
    assert "受輔助宣告之人為下列行為時，應經輔助人同意" in expansions(
        "我爸輕度失智,生活可以自理也認得人,但常被推銷亂花錢,我不想剝奪他所有決定權"
    )                                                                    # §15-2


def test_terms_extracted_from_urgency_reach_the_article_about_urgency():
    """「對方知道我很急,借三十萬要我三個月還四十五萬」 returned the 消費借貸 chapter,
    as if the terms were ordinary. §74 looks at HOW they were obtained."""
    assert "法律行為，係乘他人之急迫、輕率或無經驗，使其為財產上之給付或為給付之約定" in expansions(
        "我媽住院急需三十萬,對方知道我很急,我當時沒辦法只好簽"
    )                                                                    # §74


def test_a_guardian_cannot_simply_sell_the_home():
    out = expansions("我是媽媽的監護人,舅舅們說賣掉房子送安養院,我想堅持不賣")
    assert "監護人對於受監護人之財產，非為受監護人之利益，不得使用、代為或同意處分" in out   # §1101
    assert "監護人於執行有關受監護人之生活、護養療治及財產管理之職務時，應尊重受監護人之意思" in out  # §1112


def test_siblings_share_the_duty_by_means():
    """「安養院只找我要錢,哥哥姊姊都說沒錢不出」 reached §1116 — the order among
    people ENTITLED to support — which is the mirror of the question."""
    out = expansions("安養院只找我要錢,哥哥姊姊都說沒錢不出,扶養是不是應該一起分擔")
    assert "負扶養義務者有數人時，應依左列順序定其履行義務之人" in out                # §1115
    assert "負扶養義務者有數人而其親等同一時，應各依其經濟能力，分擔義務" in out      # §1115 末項


def test_a_customer_may_stop_the_work_and_pay_only_the_loss():
    assert "工作未完成前，定作人得隨時終止契約。但應賠償承攬人因契約終止而生之損害" in expansions(
        "裝潢做到一半品質很差,我想喊停找別人,他說我違約要賠他全部的錢"
    )                                                                    # §511


def test_an_adult_childs_debt_is_his_own():
    out = expansions("兒子剛滿十八在外面借了十五萬,對方說我是父親要負責幫他還")
    assert "滿十八歲為成年" in out                                        # §12
    assert any("由其代負履行責任之契約" in term for term in out)          # §739


def test_fittings_reach_both_sides_of_the_question():
    out = expansions("租五年自己花錢裝的鐵窗焊上去、冷氣嵌入式,房東說不能拆走")
    assert "動產因附合而為不動產之重要成分者，不動產所有人，取得動產所有權" in out   # §811
    assert "承租人就租賃物支出有益費用，因而增加該物之價值者" in out                # §431


def test_whether_joint_liability_exists_at_all():
    """The window gave every CONSEQUENCE of joint liability — §273/§274/§277/
    §280/§281 — while the question was whether it exists."""
    out = expansions("三個人都簽名但沒有寫連帶,對方要我一個人還六十萬,全部還是三分之一")
    assert "數人負同一債務，明示對於債權人各負全部給付之責任者，為連帶債務" in out   # §272
    assert "無前項之明示時，連帶債務之成立，以法律有規定者為限" in out              # §272 II


def test_a_parent_with_sole_custody_reaches_the_duty_behind_it():
    assert "父母對於未成年之子女，有保護及教養之權利義務" in expansions(
        "親權判給我,前夫接去過夜就不還我,說他也是爸爸有權帶,我想把女兒接回來"
    )                                                                    # §1084


def test_the_label_on_the_contract_is_not_the_test():
    """「每天打卡上班,主管排班也管我請假,可是公司要我簽承攬契約」 returned the entire
    承攬 chapter — because the contract is CALLED 承攬, while the question is
    whether it IS one."""
    out = expansions("我每天打卡上班,主管排班也管我請假,但公司說我簽的是承攬,我算不算員工")
    assert "稱僱傭者，謂當事人約定，一方於一定或不定之期限內為他方服勞務，他方給付報酬之契約" in out  # §482
    assert "勞工：指受雇主僱用從事工作獲致工資者" in out                                        # 勞基§2


def test_an_heir_shut_out_reaches_the_inheritance_clock():
    out = expansions("調謄本才發現哥哥用我沒有簽過的分割協議書把房子登記到自己名下")
    assert "繼承權被侵害者，被害人或其法定代理人得請求回復之" in out          # §1146
    assert "自知悉被侵害之時起，二年間不行使而消滅" in out                    # §1146 II


def test_clearing_out_reaches_the_duty_to_return_the_thing():
    # 清運 had been pulling in the 運送 and 倉庫 chapters.
    out = expansions("退租搬走後房東說我沒清乾淨要扣一萬五清運費")
    assert "承租人於租賃關係終止後，應返還租賃物" in out                      # §455


def test_a_favour_asked_and_accepted_is_a_mandate():
    """「請朋友幫我賣二手車,他說只是幫忙不是受我委託」 returned the 買賣瑕疵 articles
    off the word 賣, with nothing that tests his claim."""
    out = expansions("我請朋友幫我賣二手車,賣了十八萬錢不給我,他說只是幫忙不是受我委託")
    assert "稱委任者，謂當事人約定，一方委託他方處理事務，他方允為處理之契約" in out   # §528
    assert "受任人因處理委任事務，支出之必要費用" in out                            # §546


def test_rent_still_accepted_keeps_the_lease_alive():
    assert "租賃期限屆滿後，承租人仍為租賃物之使用收益，而出租人不即表示反對之意思者，視為以不定期限繼續契約" in expansions(
        "租約到期沒續約,我照常繳房租他也照收,現在說要我兩週內搬走"
    )                                                                    # §451


def test_waiting_for_a_hearing_reaches_the_faster_order():
    assert "法院核發暫時保護令或緊急保護令，得不經審理程序" in expansions(
        "聲請保護令一個多月還沒開庭,對方昨天又來砸東西,有沒有更快的方式"
    )                                                                    # 家暴法§16


def test_how_much_support_is_its_own_question():
    """The set already reached WHO owes (§1115) and whether it can be reduced
    (§1118-1); 「我爸要我每個月給五萬,我薪水六萬還要養兩個小孩」 is the third one."""
    assert "扶養之程度，應按受扶養權利者之需要，與負扶養義務者之經濟能力及身分定之" in expansions(
        "我爸要我每個月給他五萬,我薪水六萬還要養兩個小孩,扶養費到底怎麼算"
    )                                                                    # §1119

    # 名下沒有財產 is NOT a 脫產 trigger: it describes poverty, and it hijacked
    # this very session once.
    assert not any("有害及債權者" in term for term in expansions("爸爸名下沒有財產,只有勞保年金"))


def test_money_left_for_safekeeping_reaches_the_fork():
    """「出國前把八十萬交給朋友保管,他拿去周轉」 was REFUSED at 資料不足."""
    out = expansions("出國前把八十萬現金交給朋友保管,他拿去周轉,這算保管還是借他")
    assert "稱寄託者，謂當事人一方以物交付他方，他方允為保管之契約" in out          # §589
    assert "寄託物為代替物時，如約定寄託物之所有權移轉於受寄人" in out              # §602


def test_an_outside_wall_reaches_the_definition_that_settles_it():
    assert "共有部分，指區分所有建築物專有部分以外之其他部分及不屬於專有部分之附屬物" in expansions(
        "社區外牆磁磚掉下來砸到我的車,管委會說那面牆是頂樓那戶的專有部分"
    )                                                                    # §799


def test_the_guardianship_articles_are_reachable_from_plain_words():
    """Filed as a 「floor artefact」 for several rounds because the CLI reaches these
    through its focused dense query. No phrase in the table matched either
    article, so a flat fact string never got them."""
    out = expansions("我想聲請監護宣告,可是弟弟也要當監護人,法院會怎麼決定誰當監護人")
    assert "法院為監護之宣告時，應依職權就配偶、四親等內之親屬" in out            # §1111
    assert "成年人之監護，除本節有規定者外，準用關於未成年人監護之規定" in out     # §1113


def test_when_rent_falls_due_is_reachable():
    assert "承租人應依約定日期，支付租金" in expansions(
        "房東要我一次先付一年租金三十萬,原本是月付一萬五"
    )                                                                    # §439


def test_a_divisible_debt_without_a_joint_clause_is_split():
    # §272 (shipped last round) says joint liability needs an express term;
    # §271 says what happens without one.
    out = expansions("借據沒寫連帶,三個人簽名,我要還全部還是三分之一")
    assert "數人負同一債務或有同一債權，而其給付可分者" in out                   # §271
    assert "應各平均分擔或分受之" in out                                      # §271


def test_a_mistake_reaches_the_route_that_does_not_depend_on_how_it_was_bought():
    """「實體店面下訂,看錯電壓」 returned 消保法§19 and the 通訊交易 articles — for a
    purchase the asker had explicitly said was NOT online."""
    assert "意思表示之內容有錯誤，或表意人若知其事情即不為意思表示者，表意人得將其意思表示撤銷之" in expansions(
        "在實體店面訂了縫紉機,下單時看錯電壓,收到才發現用不了"
    )                                                                    # §88


def test_a_guarantee_reaches_the_article_that_goes_against_the_asker():
    assert "保證債務，除契約另有訂定外，包含主債務之利息、違約金、損害賠償及其他從屬於主債務之負擔" in expansions(
        "我幫同事作保,保證書只寫保證借款五十萬,銀行說連利息違約金都要我負責"
    )                                                                    # §740


def test_paying_another_persons_debt_reaches_subrogation():
    assert "就債之履行有利害關係之第三人為清償者，於其清償之限度內承受債權人之權利" in expansions(
        "車登記在我名下,銀行要拖車,我只好先幫他把八萬繳掉,想跟他要回來"
    )                                                                    # §312


def test_treatment_period_reaches_the_prohibition_not_the_procedure():
    """「被機器壓傷手還在復健,公司寄資遣通知」 returned §11/§12/§14/§16/§18 — how a
    contract is ended — plus §59 for the money. §13 says he may not end it."""
    assert "勞工在第五十條規定之停止工作期間或第五十九條規定之醫療期間，雇主不得終止契約" in expansions(
        "我被機器壓傷手還在復健也還沒回去上班,公司昨天寄資遣通知"
    )                                                                    # 勞基§13


def test_goods_broken_in_transit_reach_who_bears_the_risk():
    assert "買賣標的物之利益及危險，自交付時起，均由買受人承受負擔" in expansions(
        "店家安排的貨運路上翻車桌面裂了,我還沒簽收,這個損失該誰承擔"
    )                                                                    # §373


def test_negotiorum_gestio_now_carries_its_own_rule():
    # §176 shipped without §172 two rounds ago — the consequence without the rule.
    assert "未受委任，並無義務，而為他人管理事務者" in expansions(
        "樓上出國水管爆了漏到我家,我只好自己找水電修好"
    )                                                                    # §172


def test_a_new_guardian_reaches_the_next_step_not_the_appointment():
    """「法院上個月裁定我當監護人,接下來要辦什麼」 returned §14/§15/§1111 — how a
    guardian is APPOINTED, which had already happened."""
    out = expansions("法院裁定我當媽媽的監護人,接下來要辦什麼,社工說有東西要在期限內送法院")
    assert "監護開始時，監護人對於受監護人之財產，應依規定會同" in out          # §1099
    assert "監護人應以善良管理人之注意，執行監護職務" in out                   # §1100


def test_a_wedding_day_delivery_reaches_rescission_without_demand():
    """「約定婚禮當天早上八點送到,對方到中午都沒來」 was REFUSED at 資料不足."""
    out = expansions("花藝約定婚禮當天早上八點送到,對方都沒來,第三天才說要補送,我可以直接不要了嗎")
    assert "依契約之性質或當事人之意思表示，非於一定時期為給付不能達其契約之目的" in out  # §255
    assert "遲延後之給付，於債權人無利益者，債權人得拒絕其給付" in out                  # §232


def test_mould_that_makes_a_tenant_ill_reaches_the_right_to_leave():
    """「房東說當初帶看你自己也看過了」 — §424 answers that sentence directly: where
    the defect endangers health the tenant may terminate even having known."""
    assert "如有瑕疵，危及承租人或其同居人之安全或健康時" in expansions(
        "租的套房整面牆都是黑黴壁癌,住進去半年一直咳嗽,房東說當初也看過"
    )                                                                    # §424


def test_a_committee_that_does_nothing_reaches_its_own_job_list():
    assert "管理委員會之職務如下" in expansions(
        "管委會收管理費卻什麼都不做,大廳燈壞三個月沒換,依法該做哪些事"
    )                                                                    # 條例§36


def test_a_cohabiting_partner_is_a_family_member_not_an_analogy():
    """The window gave 家暴法§63-1 — which covers partners who do NOT live
    together — to someone who does. §3 is the article itself."""
    out = expansions("我跟男友同居三年,沒有結婚也沒登記,朋友說不算家暴")
    assert "本法所定家庭成員，包括下列各員及其未成年子女" in out              # §3
    assert "現有或曾有同居關係、家長家屬或家屬間關係者" in out                # §3 第2款


def test_a_buyer_defending_his_title_reaches_his_own_side():
    """「原屋主的兒子說登記是錯的,要我把房子還回去」 returned §244/§242/§87/§88 —
    every way a transaction gets UNDONE, which is the opposite of what he needs."""
    out = expansions("原屋主的兒子跑來說當初過戶是被騙的、登記是錯的,要我還回去,我完全不知道")
    assert "不動產物權經登記者，推定登記權利人適法有此權利" in out            # §759-1
    assert "因信賴不動產登記之善意第三人" in out                            # §759-1 II


def test_a_pipe_overhead_is_still_an_intrusion():
    # §797 covers the branches; nothing covered the airspace.
    assert "土地所有權，除法令有限制外，於其行使有利益之範圍內，及於土地之上下" in expansions(
        "隔壁的冷氣排水管架在我家院子上方,樹枝也越過圍牆"
    )                                                                    # §773


def test_where_to_sue_is_its_own_question():
    assert "消費訴訟，得由消費關係發生地之法院管轄" in expansions(
        "業者在高雄我住台北,他們說要告就去高雄告,我可不可以在台北告"
    )                                                                    # 消保法§47


def test_agreement_on_thing_and_price_is_the_contract():
    """「LINE 上談好十二萬,他回『好,就這個價』,隔天說沒簽約不算」 returned the
    買賣瑕疵 chapter — what happens when goods are defective, not whether a sale
    exists."""
    assert "當事人就標的物及其價金互相同意時，買賣契約即為成立" in expansions(
        "在LINE上談好二手鋼琴十二萬,他回好就這個價,隔天說沒簽約所以不算"
    )                                                                    # §345


def test_the_article_the_other_side_relies_on_is_in_the_window():
    """The opponent's whole argument rested on 損益相抵; the window carried
    §184/§188/§193/§213 and never the article being used against the asker."""
    assert "基於同一原因事實受有損害並受有利益者，其請求之賠償金額，應扣除所受之利益" in expansions(
        "我的車體險先賠了十二萬,對方說他只要賠六萬因為我已經領過保險金"
    )                                                                    # §216-1


def test_a_signed_agreement_without_registration():
    out = expansions("三個繼承人簽了分割協議書還沒辦登記,大哥說協議不算數,現在算誰的")
    assert "不動產物權，依法律行為而取得、設定、喪失及變更者，非經登記，不生效力" in out  # §758
    assert "公同共有之關係，自公同關係終止，或因公同共有物之讓與而消滅" in out            # §830


def test_the_settlement_paper_the_whole_question_is_about():
    """「對方拿一張和解書給我簽,一個月後醫生說頸椎要開刀」 returned §563/§473/
    §611/§144/§197/§125 — nothing about the paper she signed."""
    out = expansions("車禍當天對方拿一張和解書給我簽,寫賠我三萬塊兩清,我當場簽了")
    assert "和解有使當事人所拋棄之權利消滅" in out           # §737 — what he is holding
    assert "和解不得以錯誤為理由撤銷之" in out               # §738 — the only way back


def test_refusing_to_settle_is_not_having_settled():
    """「我不想和解了」 contains 和解了 and means the opposite — the denied-premise
    failure mode, so every trigger requires the settlement to have happened."""
    out = expansions("他一直找我談,我不想和解了,直接告他可以嗎")
    assert "和解有使當事人所拋棄之權利消滅" not in out


def test_a_demand_letter_alone_does_not_stop_the_clock():
    """The asker's belief 「寄了存證信函時效就中斷了」 is the defect: §130 says the
    interruption is undone unless a suit follows within six months."""
    assert "時效因請求而中斷者，若於請求後六個月內不起訴，視為不中斷" in expansions(
        "兩年前有寄存證信函催他還錢,我想說這樣時效就中斷了就先放著"
    )                                                                    # §130


def test_a_demand_letter_as_proof_of_notice_is_not_a_clock_event():
    """Bare 「寄存證信函」 was rejected as a trigger: three sessions send one as
    evidence that notice was given, and §130 has no business in their windows."""
    out = expansions("管委會寄存證信函說我欠了三年管理費要告我,可是電梯壞了半年他們都不修")
    assert "時效因請求而中斷者，若於請求後六個月內不起訴，視為不中斷" not in out


def test_undoing_your_own_gift_is_not_the_creditor_undoing_a_debtors():
    """The act is identical from both sides — only the role differs. 「贈與過戶給
    兒子,過戶完他就搬走」 got the CREDITOR's §244/§242/§87 and nothing she could use."""
    out = expansions("我三年前把名下的房子贈與過戶給兒子,講好他要照顧我到老,結果過戶完他就搬走")
    assert "對於贈與人有扶養義務而不履行者" in out                        # §416 II
    assert "贈與撤銷後，贈與人得依關於不當得利之規定，請求返還贈與物" in out  # §419
    assert "債務人所為之無償行為，有害及債權者，債權人得聲請法院撤銷之" not in out  # §244


def test_the_creditor_chasing_a_transfer_still_reaches_244():
    """Narrowing 脫產 must not cost the session that motivated it."""
    assert "債務人所為之無償行為，有害及債權者，債權人得聲請法院撤銷之" in expansions(
        "他欠我一百萬,查到他上個月把名下唯一的房子過戶給他兒子,說是贈與"
    )                                                                    # §244


def test_a_will_written_by_someone_else_is_still_a_will():
    """「弟弟說遺囑不是爸爸親手寫的所以無效」 got §1144/§1138/§1141/§1165/§1176 —
    how an estate is divided, which is the question AFTER this one."""
    out = expansions("找了三個鄰居當見證人,爸爸口述由其中一個人代筆寫遺囑,大家都簽名蓋章")
    assert "遺囑應依左列方式之一為之" in out                      # §1189 — 自書 is one of five
    assert "代筆遺囑，由遺囑人指定三人以上之見證人" in out          # §1194 — the checklist


def test_a_session_that_says_there_was_no_will_is_not_a_will_case():
    """遺囑 sits in seven sessions, one of them a denial, and 見證人 in two about
    signed agreements — neither is a trigger, so neither drags the 遺囑方式 in."""
    denial = expansions("爸爸沒有留遺囑,三個兄弟姊妹要怎麼分")
    assert "代筆遺囑，由遺囑人指定三人以上之見證人" not in denial
    agreement = expansions("協議書三個人都簽名蓋章,也有見證人,但還沒去地政辦登記")
    assert "遺囑應依左列方式之一為之" not in agreement


def test_the_people_a_company_sent_are_the_companys_problem():
    """「公司說是工人自己不小心,叫我去找工人賠,工人是臨時找的」 got the whole tort
    chapter — the answer for a stranger's accident, not for a paid contract.
    「臨時找的」 is the sentence that denies §188's 受僱人 link; §224 does not need it."""
    assert (
        "債務人之代理人或使用人，關於債之履行有故意或過失時，債務人應與自己之故意或過失負同一責任"
        in expansions("搬家公司來的工人把餐桌摔壞,公司叫我去找工人賠,說工人是臨時找的")
    )                                                                    # §224


def test_a_business_that_changed_hands_carries_its_debts():
    out = expansions("老闆把店頂讓給別人,新老闆接手後繼續開,舊老闆積欠我三個月薪水")
    assert "就他人之財產或營業，概括承受其資產及負債者" in out      # §305
    assert "事業單位改組或轉讓時" in out                          # 勞基§20


def test_what_the_debt_buyer_bought_includes_the_defences():
    """「資產管理公司說債權買過去了,要我還十八萬;我還過六萬,銀行也還欠我存款」
    got §204/§205/§233/§126 and four 繼承 articles."""
    out = expansions("資產管理公司說債權已經買過去了,我當初有還過六萬,銀行也還欠我一筆存款")
    assert "債務人於受通知時，所得對抗讓與人之事由，皆得以之對抗受讓人" in out   # §299 I
    assert "債務人得對於受讓人主張抵銷" in out                                 # §299 II


def test_a_living_debtor_is_not_an_heir():
    """欠銀行 was a trigger on the 拋棄繼承 row until a card-debt session came back
    half 繼承編. Same shape as 過戶給 — the words fit both people."""
    out = expansions("我的卡債本來是欠銀行的,現在資產管理公司要我一次還清十八萬")
    assert "應於知悉其得繼承之時起三個月內，以書面向法院為之" not in out
    assert "繼承人對於被繼承人之債務，以因繼承所得遺產為限，負清償責任" not in out


def test_the_heir_who_hid_the_will():
    """「我哥一直說沒有遺囑,後來看到爸爸的遺囑被他藏起來」 got §1138/§1141/§1164/
    §1165/§1173/§1176 — how to split an estate, not who still gets a share."""
    assert "偽造、變造、隱匿或湮滅被繼承人關於繼承之遺囑者" in expansions(
        "我爸過世後我哥一直說沒有遺囑,後來我看到爸爸親筆寫的遺囑被他藏起來不拿出來"
    )                                                                    # §1145 I 4


def test_releasing_one_debtor_does_not_release_the_guarantor():
    """The window answered 「誰可以被追」 with §273/§274/§277/§280/§281 when the
    question was 「他被放掉了,我少還多少」."""
    out = expansions("銀行跟公司談好只還一百五十萬就結案,公司都被免除了我還要不要還")
    assert "債權人向連帶債務人中之一人免除債務，而無消滅全部債務之意思表示者" in out  # §276


def test_the_sentence_used_against_the_man_who_paid():
    """「對方說我是自願付的不能反悔」 is §180 III, and it turns on 明知 — the window
    had §225/§226/§259/§267 and 無因管理, never the article being quoted at him."""
    out = expansions("我為了息事寧人先幫他付了二十萬,對方說我是自願付的不能反悔")
    assert "因清償債務而為給付，於給付時明知無給付之義務者" in out          # §180 III
    assert "無法律上之原因而受利益，致他人受損害者，應返還其利益" in out  # §179


def test_whether_the_owner_can_be_sued_at_all():
    """「負責人說那是公司的事跟他個人無關」 got §225/§226/§232/§255/§256 and §35 —
    every article about the company failing to perform, none about reaching him."""
    assert (
        "法人對於其董事或其他有代表權之人因執行職務所加於他人之損害，與該行為人連帶負賠償之責任"
        in expansions("負責人親自跟我簽約收錢,補習班關門後他說那是公司的事跟他個人無關")
    )                                                                    # §28


def test_a_quarrel_is_not_a_noise_complaint():
    """Bare 「吵」 put 社維法§72 in a debt window (「對方一直來我家吵」) and fired on
    a beating (「昨天吵架他推我」). The compounds keep the noise sessions."""
    debt = expansions("我哥欠人家錢跑掉,對方一直來我家吵,我先幫他付了二十萬")
    assert "製造噪音或深夜喧嘩" not in debt
    beating = expansions("我跟男友同居三年,昨天吵架他推我撞到櫃子,手臂瘀青")
    assert "製造噪音或深夜喧嘩" not in beating
    still_noise = expansions("樓上小孩每天晚上跑跳,半夜還很吵,我已經失眠去看醫生")
    assert "製造噪音或深夜喧嘩" in still_noise


def test_a_deadline_that_lands_on_a_holiday():
    """The window was §248/§249/§252/§254 and 消保§11-1/§12 — every article
    assuming he was late. §122 is what decides whether he was."""
    out = expansions("最後付款日那天剛好是端午節連假銀行沒開,我十號一上班就匯了,遇假日怎麼算")
    assert "其期日或其期間之末日，為星期日、紀念日或其他休息日時，以其休息日之次日代之" in out  # §122


def test_a_form_the_parties_agreed_on_is_a_condition():
    """§166 is the mirror of §345/§153: where the parties agreed a form, the
    contract is PRESUMED not to exist until the form is complete."""
    assert "契約當事人約定其契約須用一定方式者，在該方式未完成前，推定其契約不成立" in expansions(
        "雙方說好要簽正式書面契約才算數,還沒簽他就說口頭就已經成立了"
    )                                                                    # §166


def test_court_applications_are_not_noise_complaints():
    """Bare 「聲」 is inside 聲請. All five of its firings across the stored
    sessions are court applications, and two of those windows paid seats for it."""
    for q in ["我聲請到通常保護令了,可是前男友還是每天來我家樓下按門鈴",
              "我想聲請監護宣告,爸爸失智兩年了",
              "銀行寄信說要聲請拍賣我的房子"]:
        assert "製造噪音或深夜喧嘩" not in expansions(q)
    assert "製造噪音或深夜喧嘩" in expansions("樓上小孩跑跳,半夜還很吵,我失眠去看醫生")


def test_a_registration_transfer_is_not_a_defect_claim():
    """過戶 fired the 買賣瑕疵 row in nine sessions and only two were purchases;
    the other seven — 脫產, 假買賣, 遺腹子, 受任人過世, 贈與, 藏遺囑 — got §360."""
    assert "缺少出賣人所保證之品質者" not in expansions(
        "我爸過世後我哥把遺囑藏起來,還去把印鑑證明辦一辦要去過戶"
    )
    assert "缺少出賣人所保證之品質者" in expansions(
        "中古屋交屋後才發現漏水,賣方跟仲介都說不知道"
    )


def test_asking_how_a_number_is_worked_out_is_not_a_maintenance_case():
    """怎麼算 outranked the specific rows — three characters beats two — and put
    民法§1119 in reserved seat #1 of a payment-deadline window."""
    assert "扶養之程度，應按受扶養權利者之需要，與負扶養義務者之經濟能力及身分定之" not in expansions(
        "契約上沒有寫遇假日怎麼算,對方說我遲延要沒收訂金"
    )
    assert "扶養之程度，應按受扶養權利者之需要，與負扶養義務者之經濟能力及身分定之" in expansions(
        "我想知道扶養費到底怎麼算,是照他的需要還是照我的收入"
    )


def test_does_this_count_is_not_a_waiver_question():
    """「這樣過戶算不算數」 took reserved seat #0 in a 脫產 window ahead of 名下唯一
    and 民法§244 fell out of the eight. The waiver row's own session keeps firing
    on 同意書/都簽了/自願放棄."""
    assert "法律行為，違反強制或禁止之規定者，無效" not in expansions(
        "他把名下唯一的房子過戶給兒子,我想知道這樣過戶算不算數"
    )
    assert "法律行為，違反強制或禁止之規定者，無效" in expansions(
        "公司要我簽一張同意書自願放棄加班費,同事說大家都簽了"
    )


def test_the_keeper_cannot_hand_it_back_whenever_he_likes():
    """「家具寄放在朋友倉庫,說好放到年底,兩個月他就叫我馬上搬走」 returned the
    warehouse-operator chapter (§613–§624) and §589/§602."""
    out = expansions("我把一整套家具寄放在朋友的倉庫,說好放到年底,兩個月他就叫我這禮拜搬走")
    assert "定有返還期限者，受寄人非有不得已之事由，不得於期限屆滿前返還寄託物" in out  # §598 II
    assert "寄託物返還之期限，雖經約定，寄託人仍得隨時請求返還" in out                # §597


def test_a_clause_that_sells_a_daughter_is_void_on_its_face():
    """The window was the loan and the interest — §308/§335/§474/§476/§478/§203 and
    刑§344. The question was whether the CLAUSE stands."""
    assert "法律行為，有背於公共秩序或善良風俗者，無效" in expansions(
        "借據上寫如果沒有按時還,要他女兒去酒店上班抵債"
    )                                                                    # §72


def test_dating_a_fact_is_not_asking_about_the_clock():
    """三年前/五年前 fired the limitation row in seven sessions and only one was
    about the clock; a house-purchase session was spending four of eight seats on
    §125/§129/§144/§197."""
    assert "請求權，因十五年間不行使而消滅" not in expansions(
        "我三年前買的房子,最近原屋主的兒子跑來說當初過戶是被騙的"
    )
    assert "請求權，因十五年間不行使而消滅" in expansions(
        "三年前有人騎車撞到我,現在還能跟他求償嗎,來不來得及"
    )


def test_an_unpaid_favour_can_still_come_with_a_bill():
    """「請隔壁鄰居幫我顧店,沒談到錢,出院後他要六萬工錢」 returned §793/§774/§776/
    §778 — the 相鄰關係 chapter, because the helper happens to be a neighbour."""
    out = expansions("我住院請隔壁鄰居幫我顧店,當初只說麻煩你一下沒談到錢,他現在要工錢")
    assert "報酬縱未約定，如依習慣或依委任事務之性質，應給與報酬者，受任人得請求報酬" in out  # §547
    assert "受任人因處理委任事務，支出之必要費用，委任人應償還之" in out                    # §546


def test_family_without_kinship_is_still_family():
    """The session says twice that there was no adoption and the window answered
    with §1076-1/§1077/§1079 — the denied-premise failure mode."""
    out = expansions("我從小被姑姑帶大,戶口沒有遷過去也沒有辦收養,一直住在她家到我結婚")
    assert "雖非親屬，而以永久共同生活為目的同居一家者，視為家屬" in out   # §1123 III
    assert "家長家屬相互間" in out                                       # §1114 IV


def test_being_out_of_contact_is_not_a_prepaid_trader_going_bust():
    """聯絡不上 put 消保§17 (預付型交易履約擔保) into a leak between two flats."""
    assert "預付型交易之履約擔保" not in expansions(
        "樓上漏水滲到我家,我先自己找師傅修好,樓上住戶一直聯絡不上"
    )
    assert "預付型交易之履約擔保" in expansions("買了三萬元療程套票,店突然關門")


def test_plain_speech_is_not_a_registration_signal():
    """我完全不知道 (six characters) and 跑來說 outrank real signals while saying
    nothing about land registration."""
    assert "不動產物權經登記者，推定登記權利人適法有此權利" not in expansions(
        "我被法院選為爸爸的監護人,那些帳戶的事我完全不知道要怎麼處理"
    )
    assert "不動產物權經登記者，推定登記權利人適法有此權利" in expansions(
        "原屋主的兒子說當初過戶是被騙的、登記是錯的,我的房子會不會被拿回去"
    )


def test_the_mortgage_outlives_the_time_bar():
    """The window carried §880 — the article that kills the mortgage — and not
    §145, the one that lets the creditor take the house anyway."""
    assert (
        "以抵押權、質權或留置權擔保之請求權，雖經時效消滅，債權人仍得就其抵押物、質物或留置物取償"
        in expansions("十六年前拿我名下的房子設定抵押,現在他兒子拿他項權利證明書要拍賣我的房子")
    )                                                                    # §145


def test_the_funeral_bill_comes_off_the_estate_first():
    assert "關於遺產管理、分割及執行遺囑之費用，由遺產中支付之" in expansions(
        "喪葬費三十八萬我一個人先刷卡付的,他們說是我自願出的不能從遺產裡扣"
    )                                                                    # §1150


def test_an_object_is_not_a_disturbance():
    """冷氣/機器 on the 公寓大廈§16 row was the worst contaminator measured: one
    seat in five unrelated windows — a factory hand crushed by a 機器, a tenant's
    two 分離式冷氣, a 機器 bought to the wrong spec, a dismissal during treatment,
    and a branches-over-the-yard case."""
    for q in ["我在工廠操作機器時手指被夾斷",
              "我自己裝的兩台分離式冷氣,退租要拆走房東說不行",
              "訂的機器規格不對,還沒拆封想退"]:
        assert "發生喧囂、振動及其他與此相類之行為" not in expansions(q)
    assert "發生喧囂、振動及其他與此相類之行為" in expansions("冷氣機半夜低頻震動很吵,能要求改善嗎")


def test_a_privately_hired_carer_is_outside_the_labour_act():
    """The window was 勞基§11/§16/§17/§18/§20/§28 — notice and severance, all of
    which assume 勞動基準法 applies. §488 II is the rule that actually governs, and
    it lets EITHER side end it at any time."""
    out = expansions("我在一戶人家當看護,是家屬直接請我的,沒有透過公司也沒有簽任何合約")
    assert "僱傭未定期限，亦不能依勞務之性質或目的定其期限者，各當事人得隨時終止契約" in out  # §488 II
    assert "稱僱傭者，謂當事人約定，一方於一定或不定之期限內為他方服勞務，他方給付報酬之契約" in out  # §482


def test_knowing_the_other_side_could_not_sign_is_the_expensive_part():
    """「我知道他未成年」 is the most expensive sentence in his own account: §113
    puts restitution on the party who knew. The window had only the tort chapter."""
    out = expansions("我跟一個高中生買了他的重型機車,我知道他未成年,他媽媽說沒有同意過")
    assert "限制行為能力人未得法定代理人之允許，所訂立之契約，須經法定代理人之承認，始生效力" in out  # §79
    assert "無效法律行為之當事人，於行為當時知其無效，或可得而知者，應負回復原狀或損害賠償之責任" in out  # §113


def test_living_there_for_free_is_not_a_tenancy():
    """The window was the whole 繼承編 — who owns the flat, the question BEFORE
    this one. Free occupation is 使用借貸 and §470 II is the answer."""
    out = expansions("我媽答應讓我弟免費住她那間房子,沒有租約也沒收過一毛錢,住了五年多")
    assert "借貸未定期限，亦不能依借貸之目的而定其期限者，貸與人得隨時請求返還借用物" in out  # §470 II
    assert "稱使用借貸者，謂當事人一方以物交付他方，而約定他方於無償使用後返還其物之契約" in out  # §464


def test_the_classification_is_the_whole_fight():
    """「他說那是我自願給他的,是贈與不是借款」 — the window presupposed 消費借貸
    and never carried the article the other side is standing on."""
    out = expansions("我陸續轉了六十萬給他,分手後他說那是我自願給他的,是贈與不是借款")
    assert "稱贈與者，謂當事人約定，一方以自己之財產無償給與他方，他方允受之契約" in out  # §406
    assert "贈與物之權利未移轉前，贈與人得撤銷其贈與" in out                          # §408


def test_a_paid_car_park_may_be_holding_the_car_not_the_space():
    """A car park inside a building dragged in 公寓大廈條例§4/§7/§10/§23/§26/§33.
    Whether it is 場地租賃 or 寄託 is the entire case."""
    out = expansions("我在月租停車場停車,去牽車發現車門被刮花,合約寫本場所僅出租車位、車輛毀損概不負責")
    assert "受寄人保管寄託物，應與處理自己事務為同一之注意，其受有報酬者，應以善良管理人之注意為之" in out  # §590
    assert "稱寄託者，謂當事人一方以物交付他方，他方允為保管之契約" in out                                # §589


def test_putting_money_into_a_friends_shop_may_make_you_a_partner():
    """「我算股東還是債主」 is the question, and §681 is why he needs the answer
    before the creditors do — partners are jointly liable for the shortfall."""
    out = expansions("我拿一百五十萬給他當本錢,說好不用顧店,每個月分我兩成營業額")
    assert "稱合夥者，謂二人以上互約出資以經營共同事業之契約" in out                        # §667
    assert "合夥財產不足清償合夥之債務時，各合夥人對於不足之額，連帶負其責任" in out        # §681


def test_a_broker_earns_only_what_he_brought_about():
    """The window was 買賣瑕疵 plus §389/§588 and even §514-7 (旅遊) — nothing
    about when a broker is owed anything."""
    out = expansions("簽的是一般委託,後來我自己找到買方成交,仲介說買方是他之前帶看過的")
    assert "居間人，以契約因其報告或媒介而成立者為限，得請求報酬" in out    # §568
    assert "稱居間者，謂當事人約定，一方為他方報告訂約之機會或為訂約之媒介，他方給付報酬之契約" in out  # §565


def test_made_to_order_is_a_contract_for_work_not_a_sale():
    """「訂做的不能退不能換」 borrows the language of a sale to escape 承攬
    liability. §490 is the classification and §493 is the first rung."""
    out = expansions("我在工作室訂做一組實木餐桌椅,尺寸木種都是我指定的,桌面有裂痕")
    assert "稱承攬者，謂當事人約定，一方為他方完成一定之工作，他方俟工作完成，給付報酬之契約" in out  # §490
    assert "定作人得定相當期限，請求承攬人修補之" in out                                          # §493


def test_a_falling_tile_is_the_owners_problem_not_a_fault_question():
    """民法§191 was reachable all along and still never reached the window: every
    trigger on its row was two characters, and specificity sorts by LENGTH, so
    「管委會」 took the seats. §184 makes the asker prove the fault §191 presumes."""
    assert "由工作物之所有人負賠償責任" in expansions(
        "社區外牆的磁磚掉下來把我停在旁邊的車砸凹了,管委會說不關他們的事"
    )                                                                    # §191
    assert "由工作物之所有人負賠償責任" in expansions(
        "樓上鄰居出國,他家水管爆了一直漏到我家,我自己找水電修好花了兩萬八"
    )                                                                    # §191


def test_a_unit_repaired_four_times_reaches_the_warranty_articles():
    """Same shape, same fix: 瑕疵/故障/維修/退錢 are all two characters and lost the
    seats to 「換新的」."""
    out = expansions("去年裝的冷氣從第一個月就會漏水,叫廠商來修了四次還是一樣")
    assert "無滅失或減少其價值之瑕疵" in out                              # §354
    assert "買受人得解除其契約或請求減少其價金" in out                    # §359


def test_an_earnest_money_receipt_outranks_a_service_fee():
    """民法§248 sat at expansion position 10 in the one session written for it:
    「斡旋」 is two characters and lost every seat to 「手續費」 (three)."""
    out = expansions("我付了十萬斡旋金,有簽斡旋金收據,上面寫如果屋主不同意會全額退還,房仲說要扣手續費")
    assert out.index("由他方受有定金時，推定其契約成立") < 3          # §248 in a reserved seat


def test_the_contract_row_can_reach_when_the_balance_falls_due():
    """Seat arithmetic, not vocabulary: the 承攬 row won expansion positions 0-4 in
    「材料另外算要再加十二萬」 and still could not deliver §505, because §505 was its
    FIFTH phrase and only three seats exist with one article per phrase."""
    out = expansions("我請師傅修屋頂,講好工錢八萬,做完他說材料另外算要再加十二萬,報價單只寫一個總價")
    assert out.index("報酬應於工作交付時給付之") < 3                  # §505 in a reserved seat


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
