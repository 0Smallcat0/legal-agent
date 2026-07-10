# Deploy the demo to Hugging Face Spaces (free)

The Gradio demo (`app.py`) is designed for the **free CPU tier**: the corpus is
built at startup, the 引用查核/檢索 tabs are pure Python (no model), and the
完整流程 tab uses the paste-back "manual" flow — no API key, no GPU, no Ollama
needed on the Space. (The one-click Ollama button simply reports "not
available" there; it works when running `python app.py` locally.)

## Steps (one-time, ~10 minutes)

1. Create a free account at https://huggingface.co → **New Space**
   - Space name: `legal-agent-demo` (anything works)
   - SDK: **Gradio** · Hardware: **CPU basic (free)** · Visibility: Public
2. Add Spaces metadata at the TOP of the Space's `README.md`
   (the Space UI creates this file; keep the repo's own README out of it):

   ```yaml
   ---
   title: Legal Agent — 防幻覺五閘門 Demo
   emoji: ⚖️
   colorFrom: indigo
   colorTo: gray
   sdk: gradio
   app_file: app.py
   pinned: false
   ---
   ```

3. Push this repository's files to the Space (either `git remote add space
   https://huggingface.co/spaces/<user>/legal-agent-demo` + `git push space
   main`, or drag-and-drop `app.py`, `requirements.txt`, `legal_agent/`,
   `corpus/`, `evals/` in the web UI).
4. The Space builds from `requirements.txt` and serves `app.py`. First build
   takes a few minutes.

## Résumé link

Put the Space URL next to the GitHub link, e.g.

> Legal Agent — retrieval-first anti-hallucination pipeline
> (GitHub: github.com/0Smallcat0/legal-agent · Live demo: huggingface.co/spaces/…)

Reviewers can reproduce the README's hallucination-catch story in ~30 seconds
via the 引用查核 tab's pre-filled broken answer.
