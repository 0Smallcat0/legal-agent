# Do not read these files

Three stale artefacts, moved here on 2026-08-15 rather than deleted:

    legal_agent.db            2,562 statute rows
    dense_bgem3.npy           float32 embeddings
    dense_bgem3.keys.json     their keys

**No code path reaches them.** The live database is at
`legal_agent.config.DB_PATH` (under `LEGAL_AGENT_HOME`, the platform per-user
data dir by default), and `retrieval/dense.py` writes its index beside that
database — `Path(config.DB_PATH).parent / "dense_bgem3"` — not into the repo.

They are kept because they are evidence, not because they are useful.

**Why they existed.** `db/` was documented as the place the database is created
at runtime. It never was. Two agents each opened one of these files from a
throwaway script that hardcoded the path, and each computed a set of published
figures against it. Neither run carried any signal saying which corpus it had
read. That is trap 1 in `AGENTS.md`.

**What the 2,562 proves.** 2,560 (the bulk proposal) + 2 (the noise routing
proposal), with the 361-article gap batch missing. That is exactly the shape of
the `ensure_corpus` early-return defect fixed in `506943f`: proposals were only
loaded when the corpus was empty, so a database built before a proposal shipped
stayed on the old corpus forever, with nothing on screen to say so. These files
are that failure mode having actually happened — to a database nobody was using.

**Before you trust any number, print the corpus it came from:**

```bash
python -c "import legal_agent; print(legal_agent.corpus_fingerprint().render())"
```

Every harness prints that line now, and aborts rather than reporting a figure
when the corpus is below what the package ships.
