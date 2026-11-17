"""jev_measure: the billing guard and the offline table, with no network."""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from legal_agent.evaluation import jev_measure as jm


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b


def _reply(billing="free", cost=0, p=0.25):
    return {"answers": {"q": {"noul": p}},
            "usage": {"cost": cost, "opencode": {"billing_source": billing}}}


def test_a_free_reply_returns_the_probability(monkeypatch):
    monkeypatch.setattr(jm.urllib.request, "urlopen", lambda *a, **k: _Resp(_reply()))
    assert jm.ask("s", "q") == 0.25


@pytest.mark.parametrize("payload", [_reply(billing="balance"), _reply(cost=0.001)])
def test_a_reply_that_is_not_free_stops_the_run(monkeypatch, payload):
    monkeypatch.setattr(jm.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    with pytest.raises(jm.PaidError):
        jm.ask("s", "q")


@pytest.mark.parametrize("code", [401, 402, 403, 404])
def test_billing_statuses_stop_the_run(monkeypatch, code):
    def boom(*a, **k):
        raise urllib.error.HTTPError(jm.URL, code, "x", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(jm.urllib.request, "urlopen", boom)
    with pytest.raises(jm.PaidError):
        jm.ask("s", "q")


def test_a_long_retry_after_is_a_quota_stop_not_a_wait(monkeypatch):
    def limited(*a, **k):
        raise urllib.error.HTTPError(
            jm.URL, 429, "Too Many Requests", {"Retry-After": "53469"},
            io.BytesIO(b'{"error":{"type":"FreeUsageLimitError"}}'))

    monkeypatch.setattr(jm.urllib.request, "urlopen", limited)
    with pytest.raises(jm.QuotaExhausted, match="FreeUsageLimitError"):
        jm._ask_retry("s", "q")


def test_semantic_table_counts_only_the_pairs_that_were_asked():
    kinds = {"a": "swap", "b": "swap", "c": "control", "d": "control", "e": "control"}
    probs = {"a": 0.9, "b": 0.2, "c": 0.6, "d": 0.1}          # "e" never asked
    assert jm.semantic_table(probs, kinds, 0.5) == (1, 2, 1, 2)
    assert jm.semantic_table(probs, kinds, 0.05) == (2, 2, 2, 2)
