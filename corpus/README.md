# corpus/

The small, **human-verified** source material (spec §1.5) staged here before it
is parsed into the SQLite tables. **In use now**: `noise_routing_proposal.json`
holds the 命令 / 行政實務見解 sources that have been ingested into the DB. Legal
data is still hand-verified — never fetched, generated, or hardcoded.

## Build strategy (spec §1.5): small-and-accurate, single scenario first

Do **not** build the full corpus first. For the locked scenario #1 —
**住宅噪音糾紛 (residential noise disputes)** — manually scope only the relevant
sources, small enough to **human-verify every article's correctness and
timeliness**:

- [x] 民法 相鄰關係 — 第793條 loaded (＋第184/195條 for 侵權/人格權)
- [x] 噪音管制法 — 第3/6/9條 loaded
- [x] 社會秩序維護法 第72條 loaded
- [x] 公寓大廈管理條例 — 第16/47條 loaded
- [x] reference judgments — `judgments_v1.json`, 386 of them (see below)

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
python -m legal_agent.data.judgment_ingest -o corpus/judgments_v1.json
```

> The above is a **collection checklist**, not the data itself. Each item must be
> pulled from the official sources (法規 → law.moj.gov.tw; 判決 →
> opendata.judicial.gov.tw), verified by a human, and — crucially — captured
> **with its 生效日期 / 沿革** so the `statutes` time slices (§1.4) are correct.

## Honesty caveat to preserve (spec §1.3)

The statute DB is incomplete: local 自治條例 (some cities' own noise/pet rules)
may be missing. When a locality-specific rule might exist but isn't in the
corpus, the system must **say so** rather than pretend coverage is complete.
