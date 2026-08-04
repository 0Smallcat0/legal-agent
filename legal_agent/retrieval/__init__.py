"""Retrieval layer (spec §2.2 Mechanism 1 / build step 2).

Sits between the corpus (data/) and the reasoning model: it pulls the relevant
verbatim statutes/judgments that the model is then allowed to cite — and nothing
else. Fires exactly ONCE per conversation, in dialogue Stage 3 (spec §3.3).

STATUS: implemented — lexical BM25 (jieba + CJK bigrams). The point-in-time
time-slice filter runs BEFORE ranking, so a superseded version is never a
candidate.
"""
