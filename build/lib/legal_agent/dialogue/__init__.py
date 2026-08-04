"""Dialogue layer (spec §3) — the four-stage "clinic-style" flow.

    Stage 1  Triage   -> triage.py     coarse-classify the problem   (NO retrieval)
    Stage 2  Intake   -> intake.py     walk the fact checklist       (NO retrieval)
    Stage 3  Classify -> (retrieval/ + anti_hallucination/)  retrieve ONCE + gates
    Stage 4  Solution -> solution.py   ranked low->high escalation ladder

flow.py is the orchestrator. CRITICAL invariant (spec §3.3): retrieval fires
exactly ONCE, in Stage 3, after facts are complete — "clinic-style" (full
history, then diagnose), not "chat-style" (query every turn, degrade).
STATUS: implemented — all four stages + the single-retrieval invariant
(test-enforced).
"""
