"""Retrieval layer (spec §2.2 Mechanism 1 / build step 2).

Pulls the verbatim statutes the model may cite — and nothing else — once per
conversation, in dialogue Stage 3 (spec §3.3). Hybrid: BM25 (jieba + CJK
bigrams) with optional bge-m3 dense fusion (dense.py) and lexicon expansion.
The point-in-time filter runs BEFORE ranking, so a superseded version is never
a candidate. judgments.py attaches reference judgments beside the answer.
"""
