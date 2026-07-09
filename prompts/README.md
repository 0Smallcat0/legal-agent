# prompts/

System-prompt text files for the reasoning model would live here. **Currently
empty**: the live SYSTEM_PROMPT is authored inline in
`legal_agent/dialogue/stage3.py`. Split it out into the files below only if/when
externalizing the wording helps iterate without touching code.

Anticipated files (authored in later steps):

| File (planned)            | Purpose | Spec |
|---------------------------|---------|------|
| `system_retrieval_first.txt` | The hard rule: *"You may only cite the provisions I supply. If they are insufficient, say '現有資料不足'. Never supplement from memory."* | §2.2 |
| `system_anti_sycophancy.txt` | Correcting a wrong user premise takes priority over agreeing. | §2.6 |
| `system_answer_structure.txt`| Force the 法條依據 / 分析研判 two-section answer format. | §2.5 |
| `intake_noise.txt`           | Stage-2 intake checklist for 住宅噪音 (element-facts to collect). | §3.2 |

Kept out of the scaffold on purpose: these encode legal content/wording, which
is out of scope for step 1.
