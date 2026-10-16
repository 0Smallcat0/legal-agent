# legal_agent/corpus/ — the shipped corpus

These four files ARE the corpus. `legal_agent/data/bootstrap.py` loads them, in
this order (`PROPOSALS`, then the judgments), into the SQLite database on first
call; the database itself lives outside the repo at `LEGAL_AGENT_HOME`. Nothing
here is fetched at runtime, generated, or typed in by hand.

| file | rows | what it is |
|---|---|---|
| `moj_bulk_v1_proposal.json` | 2,560 | 11 statutes from the official 全國法規資料庫 bulk XML: 民法, 中華民國刑法, 消費者保護法, 勞動基準法, 道路交通管理處罰條例, 公寓大廈管理條例, 噪音管制法, 社會秩序維護法, 違反社會秩序維護法案件處理辦法, 租賃住宅市場發展及管理條例, 家庭暴力防治法 |
| `moj_gap_v1_proposal.json` | 361 | 5 more from the same XML, added to close gaps the action ladder had exposed: 強制汽車責任保險法, 勞工保險條例, 就業服務法, 性別平等工作法, 個人資料保護法 |
| `noise_routing_proposal.json` | 2 | the 新北市 police noise-handling principle (`hierarchy_level` 行政實務見解, counted separately from the statutes) and one repealed historical version of 違反社會秩序維護法案件處理辦法§11 |
| `judgments_v1.json` | 386 | reference judgments, redacted to header + 主文 (below) |

So the corpus is **16 statutes, 2,921 articles in force, plus one historical
version and the police routing note** — 2,923 statute rows in all.
`tests/test_published_numbers.py` derives the first two counts from the built
database and fails when the prose disagrees.

## How the statute files are made

`legal_agent/data/moj_xml.py` parses the official bulk download into the
proposal-JSON shape, and `legal_agent/data/source_ingest.py` validates and
persists it — including the rule that refuses two open (in-force) versions of
the same article. The nine 住宅噪音 articles originally typed in by hand were
kept as a golden sample and match the XML character for character; they now
live only as a test fixture (`tests/fixtures/noise_corpus.json`).

```bash
python -m legal_agent.data.moj_xml FalVMingLing.xml -o proposals.json --include 噪音管制法
python -m legal_agent.data.source_ingest proposals.json
```

## `judgments_v1.json` — reference judgments, redacted to what the page shows

Harvested from 司法院 opendata by `data/judicial_api.py` and exported by
`data/judgment_ingest.py`. Shipped because the harvester cannot practically
rebuild them: the API serves only 00:00–06:00 and returns one day at a time,
seven days late, so the 1,367-judgment harvest took weeks of nightly runs — and
without them a fresh clone could not reproduce the README's screenshot.

**386, not 1,367** — `retrieval/judgments.py` surfaces a judgment only through a
deterministic JOIN on its `cited_articles`, so one citing no corpus statute is
unreachable by construction. The shipped set is the whole reachable set, not a
sample.

**Two slices, not the document.** Only the header (court + 案號) and the 主文
are kept: those are the only parts `citation()` and `awards()` read, and the
redaction is measured lossless — both return identical values on all 386. The
party block and 事實及理由 are dropped, which is also what takes the file from
5.9 MB to 0.27 MB.

**No party names.** 31 of the 386 name a party inside a 主文 sentence; those
ship with their header alone. Masking was rejected because it would make the
主文 no longer verbatim; dropping the whole judgment was rejected because it
costs 19 of the 239 covered articles. `tests/test_judgment_ingest.py` asserts
the shipped file itself carries no name, not merely that the exporter strips
them.

Rebuild from a harvested DB with:

```bash
python -m legal_agent.data.judgment_ingest -o legal_agent/corpus/judgments_v1.json
```

## Honesty caveat to preserve (spec §1.3)

The statute DB is incomplete: local 自治條例 (some cities' own noise/pet rules)
may be missing. When a locality-specific rule might exist but isn't in the
corpus, the system must **say so** rather than pretend coverage is complete.
