# Deploy the demo to Hugging Face Spaces (free)

**Live**: https://huggingface.co/spaces/NoirOAO/legal-agent-demo

The Gradio demo (`app.py`) needs no GPU, no API key, and no Ollama. The corpus
is built at startup from the JSON files in `corpus/`, the 引用查核 and 檢索 tabs
are pure Python, and the 完整流程 tab falls back to a scripted checklist when no
model is reachable. (The one-click Ollama button reports "not available" there;
it works when running `python app.py` locally.)

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

Nothing in this project touches a GPU, so the deployment branch carries a
guarded shim — a decorated function nothing calls — rather than putting a fake
GPU dependency on `main`.

## The deployment branch

`hf-space` is an **orphan** branch: one commit, no history, no binaries. That
sidesteps the Xet requirement entirely instead of adding LFS for a 270 KB file.
It differs from `main` in exactly three ways:

1. `README.md` carries the Spaces YAML frontmatter (`main`'s README stays clean,
   since GitHub renders that block as noise).
2. `docs/demo_web.png` is deleted and the README `<img>` points at the GitHub
   raw URL, so the screenshot still renders on the Space page.
3. `app.py` carries the ZeroGPU shim.

The frontmatter pins the gradio the app is developed against — leaving
`sdk_version` off lets the Hub pick a different major:

```yaml
---
title: Legal Agent Demo
emoji: ⚖️
colorFrom: indigo
colorTo: gray
sdk: gradio
sdk_version: 6.20.0
app_file: app.py
pinned: false
license: mit
short_description: Legal RAG with a citation verifier graded at 11,904/11,904.
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

Then:

> The frontmatter's `short_description` and the README's tests badge both carry
> NUMBERS, so they go stale on their own schedule — check them against
> `evals/RESULTS.md` during the sync rather than copying the old block forward.
> Both were stale on 2026-08-06 (10,437/10,437 and 433 tests).
>
> **Do not guard the shim re-apply on the string `spaces.GPU`.** That phrase now
> appears in `main`'s own `app.py` docstring describing this requirement, so a
> "skip if already present" check written that way matches the docstring, skips
> the shim, and the branch ships without it — the Space then dies on
> `No @spaces.GPU function detected`. Guard on `_zerogpu_probe`, which exists
> only in the shim itself. This happened on 2026-08-04.

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

`RUNNING_BUILDING` → `RUNNING_APP_STARTING` → `RUNNING` is the healthy sequence
(about four minutes); anything ending in `_ERROR` carries its reason on the same
line.

## Résumé link

> Legal Agent — retrieval-first anti-hallucination pipeline
> (GitHub: github.com/0Smallcat0/legal-agent · Live demo:
> huggingface.co/spaces/NoirOAO/legal-agent-demo)

Reviewers can reproduce the README's hallucination-catch story in ~30 seconds via
the 引用查核 tab's pre-filled broken answer.
