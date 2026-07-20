"""The CLI must never exit with a traceback on input a user could plausibly type.

A traceback tells the user the tool is broken. An error message tells them what
to fix. Every case here is a realistic mistake -- a wrong path, the wrong file,
a directory that does not exist -- and each one must produce the second.
"""

from __future__ import annotations

import json

import pytest

from deckmaster.cli import main

VALID_SPEC = {
    "title": "CLI",
    "slides": [{"type": "title", "title": "A claim worth making"}],
}


@pytest.fixture
def spec(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(VALID_SPEC), encoding="utf-8")
    return path


class TestBuild:
    def test_happy_path(self, spec, tmp_path):
        out = tmp_path / "deck.pptx"
        assert main(["build", str(spec), "-o", str(out)]) == 0
        assert out.is_file()

    def test_missing_spec_file(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["build", str(tmp_path / "nope.json"), "-o", str(tmp_path / "d.pptx")])
        assert exc.value.code == 2
        assert "cannot read" in capsys.readouterr().err

    def test_output_directory_does_not_exist(self, spec, tmp_path, capsys):
        code = main(["build", str(spec), "-o", str(tmp_path / "missing" / "deck.pptx")])
        assert code == 2
        assert "cannot write" in capsys.readouterr().err

    def test_malformed_spec_names_the_field(self, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"title": "t", "slides": [{"type": "title"}]}), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(["build", str(path), "-o", str(tmp_path / "d.pptx")])
        assert "missing required key 'title'" in capsys.readouterr().err


class TestAudit:
    def test_clean_spec_reports_nothing_blocking(self, spec):
        assert main(["audit", str(spec)]) == 0

    def test_audit_writes_no_file(self, spec, tmp_path):
        main(["audit", str(spec)])
        assert not list(tmp_path.glob("*.pptx"))


class TestCheck:
    """`check` takes an arbitrary path, so it is the verb most exposed to slips."""

    def test_valid_package(self, built_pptx):
        assert main(["check", str(built_pptx)]) == 0

    def test_missing_file(self, tmp_path, capsys):
        assert main(["check", str(tmp_path / "nope.pptx")]) == 1
        assert "no such file" in capsys.readouterr().err

    def test_pointed_at_a_json_spec_by_mistake(self, spec, capsys):
        """The most likely slip: `check spec.json` instead of `check deck.pptx`."""
        assert main(["check", str(spec)]) == 1
        assert "not a ZIP container" in capsys.readouterr().err

    def test_pointed_at_a_directory(self, tmp_path, capsys):
        assert main(["check", str(tmp_path)]) == 1
        err = capsys.readouterr().err
        assert "directory" in err or "cannot be read" in err

    def test_truncated_package(self, built_pptx, tmp_path, capsys):
        broken = tmp_path / "truncated.pptx"
        broken.write_bytes(built_pptx.read_bytes()[:200])
        assert main(["check", str(broken)]) == 1
        assert capsys.readouterr().err


def test_deck_level_strings_are_validated(tmp_path, capsys):
    """Deck title and author reach document properties, so they need checking too."""
    path = tmp_path / "spec.json"
    path.write_text(
        json.dumps({"title": "Costs 5 €", "slides": [{"type": "title", "title": "Fine"}]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main(["build", str(path), "-o", str(tmp_path / "d.pptx")])
    assert "deck title" in capsys.readouterr().err
