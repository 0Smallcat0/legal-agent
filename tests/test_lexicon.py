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
