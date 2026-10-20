"""The qualifier gate's own input scan must not pass on nothing."""
import pytest

from legal_agent.evaluation import qualifier_audit


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    evals, journal = tmp_path / "evals", tmp_path / "journal"
    evals.mkdir()
    journal.mkdir()
    monkeypatch.setattr(qualifier_audit, "EVALS_DIR", evals)
    monkeypatch.setattr(qualifier_audit, "JOURNAL_DIR", journal)
    return evals, journal


def test_the_shipped_inputs_are_scanned():
    labels = [label for label, _ in qualifier_audit._scan_sources()]
    assert any(x.startswith("evals/") for x in labels)
    assert any(x.startswith("journal/") for x in labels)


def test_empty_input_directories_fail_instead_of_scanning_only_the_corpus(dirs):
    # Corpus rows alone still supply citations, so this used to pass with
    # 2,923 of the 6,407 sources scanned.
    with pytest.raises(SystemExit):
        qualifier_audit._scan_sources()


def test_an_unparsable_eval_file_fails_instead_of_being_skipped(dirs):
    evals, journal = dirs
    (evals / "ok.json").write_text('{"a": "依民法第184條"}', encoding="utf-8")
    (evals / "broken.json").write_text("{", encoding="utf-8")
    (journal / "s.txt").write_text("依民法第184條", encoding="utf-8")
    with pytest.raises(SystemExit):
        qualifier_audit._scan_sources()
