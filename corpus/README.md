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
- [ ] ~dozens of relevant judgments (none loaded yet)

> The above is a **collection checklist**, not the data itself. Each item must be
> pulled from the official sources (法規 → law.moj.gov.tw; 判決 →
> opendata.judicial.gov.tw), verified by a human, and — crucially — captured
> **with its 生效日期 / 沿革** so the `statutes` time slices (§1.4) are correct.

## Honesty caveat to preserve (spec §1.3)

The statute DB is incomplete: local 自治條例 (some cities' own noise/pet rules)
may be missing. When a locality-specific rule might exist but isn't in the
corpus, the system must **say so** rather than pretend coverage is complete.
