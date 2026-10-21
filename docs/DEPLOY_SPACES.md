# Deploy the demo to Hugging Face Spaces (free)

**Live**: https://huggingface.co/spaces/NoirOAO/legal-agent-demo

The Gradio demo (`app.py`) needs no API key and no Ollama. The corpus is built
at startup from the JSON files in `legal_agent/corpus/`, the 引用查核 and 檢索
tabs are pure Python, and the consultation's interview is the scripted
checklist. **The 分析研判 is written by `Qwen/Qwen2.5-7B-Instruct` on ZeroGPU**
(`legal_agent/dialogue/hf_llm.py`), and retrieval's dense half embeds with
`BAAI/bge-m3` through sentence-transformers on CPU. Both switch on by
themselves: ZeroGPU sets `SPACES_ZERO_GPU`, and `config.py` reads it — no Space
variable or secret to set. Every gate (citation check, honesty tier, ladder)
still runs in code after the model; RESULTS.md §10 has what the model and the
embedding measured locally.

A visitor's GPU quota is daily: about **2 minutes unauthenticated, 5 with a free
account**, and a call is admitted against `hf_llm.GPU_SECONDS`, not against the
time it ends up using. When the quota is spent the page renders exactly as it
does with no model, with the reason in the 分析研判 box. Each call logs
`hf_llm: N tokens in Ss` to the container log; the first few after a deploy are
the Space's real speed, which is what `GPU_SECONDS` should be checked against.

## Two things that make this not a plain `git push`

Both were hit in practice, and both are why this page is longer than "push the
repo".

**1. The Hub rejects committed binaries.** `docs/demo_web.png` (270 KB) sits in
five commits of this repository's history, and the Hub's pre-receive hook
refuses it, pointing at [Xet storage](https://huggingface.co/docs/hub/xet).
Deleting the current copy does not help — it is the history that is checked.

**2. The free Gradio tier is ZeroGPU, not CPU basic.** cpu-basic is now behind
PRO. ZeroGPU refuses to start a Space that declares no `@spaces.GPU` function:

```
RUNTIME_ERROR | No @spaces.GPU function detected during startup
```

That check is now met by real work: `hf_llm._generate` is the `@spaces.GPU`
function, defined when `app.py` imports the backend at startup.

**No torch op may run in the main process.** One sentence-transformers forward
there — on CPU — and every GPU call after it fails with `RuntimeError: No CUDA
GPUs are available` from `spaces/zero/wrappers.py` `worker_init`, which the page
used to show only as 「('RuntimeError')」 (2026-10-21; RESULTS.md §10). That is
why the embedding runs in `retrieval/st_worker.py`'s own process. A GPU error
now reaches the 分析研判 box with its message, so this one would read in full. The old
`_zerogpu_probe` shim — a decorated function nothing called — is gone, and
`git checkout main -- .` removes it from `hf-space` on the next sync.

## The deployment branch

`hf-space` is an **orphan** branch: one commit, no history, no binaries. That
sidesteps the Xet requirement entirely instead of adding LFS for a 270 KB file.
It differs from `main` in exactly three ways:

1. `README.md` carries the Spaces YAML frontmatter (`main`'s README stays clean,
   since GitHub renders that block as noise).
2. `docs/demo_web.png` is deleted and the README `<img>` points at the GitHub
   raw URL, so the screenshot still renders on the Space page.
3. `requirements.txt` has the model stack appended — on `main` it stays the
   no-GPU demo set, because a local `pip install -r requirements.txt` should
   not pull 2 GB of torch:

   ```
   torch==2.8.0
   transformers==5.20.2
   accelerate==1.15.0
   sentence-transformers==6.1.0
   ```

   These are the versions RESULTS.md §10 was measured with (`pip install
   .[space]` gives the same set locally); ZeroGPU supports torch 2.8.0 and up.

The frontmatter pins the gradio the app is developed against — leaving
`sdk_version` off lets the Hub pick a different major. `preload_from_hub`
downloads both models at BUILD time, so startup does not spend its timeout on
~19 GB of weights. Startup still reads the 7B weights into memory; the corpus
embedding runs in a thread after that (578 s on CPU locally, the Space's CPU is
unmeasured), and retrieval is BM25 alone until it finishes — the container log
prints `dense index ready, retrieval is hybrid` when it has:

```yaml
---
title: Legal Agent Demo
emoji: ⚖️
colorFrom: indigo
colorTo: gray
sdk: gradio
sdk_version: 6.20.0
python_version: "3.12"
app_file: app.py
pinned: false
license: mit
short_description: Legal RAG with a citation verifier graded on 24 error kinds
startup_duration_timeout: 1h
preload_from_hub:
  - Qwen/Qwen2.5-7B-Instruct
  - BAAI/bge-m3
---
```

## Setting up the remote, once

```bash
git remote add space https://huggingface.co/spaces/<user>/<space-name>
```

Pushing needs a **write token** from https://huggingface.co/settings/tokens,
entered as the *password*. Hugging Face
[stopped accepting account passwords over git](https://huggingface.co/blog/password-git-deprecation),
and the resulting error is easy to misread as a wrong password rather than as
the wrong *kind* of credential.

## Updating the Space after a change to `main`

```bash
git checkout hf-space
git checkout main -- .
git rm --cached docs/demo_web.png && rm -f docs/demo_web.png
```

Re-apply the three differences above where `git checkout main -- .` overwrote
them. **Pull `README.md` like everything else and re-apply its two transforms** —
prepend the frontmatter block, and rewrite the `<img src>` to the GitHub raw
URL. Skipping the pull to protect the frontmatter is the obvious shortcut and it
silently drops every README CONTENT change: on 2026-08-06 the Space page was
missing a whole published row (the reference-judgment relevance figure), its
harness command, and a design note, none of which anything would have caught,
because the file looked deliberately different rather than stale.

```bash
git checkout main -- README.md
python - <<'PY'
from pathlib import Path
p = Path("README.md"); t = p.read_text(encoding="utf-8")
t = t.replace('src="docs/demo_web.png"',
              'src="https://raw.githubusercontent.com/0Smallcat0/legal-agent/main/docs/demo_web.png"')
p.write_text(FRONTMATTER + "\n" + t, encoding="utf-8", newline="\n")
PY                                                       # FRONTMATTER = the block above
```

`newline="\n"` is not cosmetic. On Windows `write_text` translates every `\n` to
`\r\n`, and the result diffs as 160 changed lines instead of 2 — which destroys
the one cheap check that this file is right:

```bash
diff <(git show main:README.md) README.md   # must show ONLY the frontmatter + the img src
```

**And check the whole tree, not just that file.** `git checkout main -- .` copies
what main HAS; it never removes what main deleted, so the branch accumulates
files forever. On 2026-08-06 it was still publicly shipping a stale duplicate of
the corpus at the pre-`pip install` path (`corpus/`, ~30k lines, relocated to
`legal_agent/corpus` long before) and `legal_agent/data/noise_seed.py`, which
main had deleted for having no caller. Nothing flagged it, because an extra file
is invisible to a procedure that only ever adds. After every sync:

```bash
git diff --stat main hf-space   # exactly README.md, requirements.txt, docs/demo_web.png
```

Anything else in that list is either a difference nobody decided on, or a
deletion that never crossed. `git rm` it.

Then:

> The frontmatter's `short_description` carries a NUMBER, so it goes stale on its
> own schedule — check it against `evals/RESULTS.md` during the sync rather than
> copying the old block forward. It was stale on 2026-08-06 (10,437/10,437).
>
> **`No @spaces.GPU function detected` now means the model backend did not
> load**, not a missing shim: `app.py` imports `hf_llm` only when
> `config.LLM_PROVIDER == "hf"`, which follows `SPACES_ZERO_GPU`. If a Space
> variable sets `LEGAL_AGENT_PROVIDER` to anything else, the decorated function
> is never defined and the Space refuses to start. (The old failure — a
> re-apply guarded on the string `spaces.GPU`, which matched a docstring and
> skipped the shim, 2026-08-04 — cannot recur: there is no shim to re-apply.)

```bash
git add -A && git commit -m "sync with main"
git push space hf-space:main
```

`--force` is needed only for the very first push, which replaces the stub commit
the Space wizard creates.

## Verifying a deploy without opening a browser

```bash
curl -sL https://huggingface.co/api/spaces/<user>/<space-name> | python -c "import json,sys; d=json.load(sys.stdin); print(d['runtime']['stage'], d['sha'][:7], d['runtime'].get('errorMessage') or '')"
```

`-L` is not optional: the API redirects, and plain `curl -s` returns an empty
body that blows up in `json.load` with `Expecting value: line 1 column 1`, which
reads like an outage rather than a missing flag. Printing the `sha` alongside the
stage is what proves the RUNNING Space is running YOUR commit.

`RUNNING_BUILDING` → `RUNNING_APP_STARTING` → `RUNNING` is the healthy sequence;
anything ending in `_ERROR` carries its reason on the same line.

**Budget 30–40 minutes, not four.** Two deploys on 2026-08-15 each sat in
`RUNNING_APP_STARTING` for roughly half an hour with an empty `errorMessage`
before reaching `RUNNING`. The old 「about four minutes」 here is what made a
healthy deploy read as a hung one.

**A 200 from the Space URL is NOT proof your commit is live.** The previous
container keeps serving throughout the build, so
`curl -o /dev/null -w "%{http_code}"` answers 200 the whole time — and `sha` in
the API is the commit being DEPLOYED, not the one running. Ask the app what it
is instead, by grepping for a string your commit changed:

```bash
curl -sL https://<space-subdomain>.hf.space/config | grep -o "<text only the new build renders>"
```

Gradio renders the hero client-side, so the page HTML does not carry it —
`/config` does. That check separates 「still starting」 from 「started, still
serving the old build」, and both from a real failure. Without it, a stale build
is indistinguishable from a fresh one.

## Résumé link

> Legal Agent — retrieval-first anti-hallucination pipeline
> (GitHub: github.com/0Smallcat0/legal-agent · Live demo:
> huggingface.co/spaces/NoirOAO/legal-agent-demo)

Reviewers can reproduce the README's hallucination-catch story in ~30 seconds via
the 引用查核 tab's pre-filled broken answer.
