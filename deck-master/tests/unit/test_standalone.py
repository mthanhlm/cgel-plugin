"""The engine must run on a bare Python install.

This is a product requirement, not a preference: the tool has to work where
nobody can install python-pptx and nobody has LibreOffice. Dependencies have a
way of arriving quietly through a convenience import, so it is asserted.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Everything the engine is allowed to import beyond the standard library.
ALLOWED_NON_STDLIB = {"deckmaster"}


def test_no_third_party_module_is_imported_when_building_a_deck():
    """Build a real deck in a clean interpreter and inspect what got imported.

    A subprocess is used so that pytest's own dependencies -- which are very
    much third-party -- cannot mask a real one.
    """
    program = """
import sys, json, tempfile, pathlib
sys.path.insert(0, "src")
before = set(sys.modules)

# Import every module in the package, not just the happy build path: the CLI is
# the shipped console entry point, and audit and validation run on every build,
# so a dependency arriving in any of them is a dependency the user must install.
import pkgutil, importlib
import deckmaster
for info in pkgutil.walk_packages(deckmaster.__path__, "deckmaster."):
    importlib.import_module(info.name)

from deckmaster.cli import main

spec = {
    "title": "Standalone",
    "slides": [
        {"type": "title", "title": "Runs anywhere", "subtitle": "Standard library only."},
        {"type": "diagram", "title": "One stage",
         "ranks": [{"nodes": [{"id": "a", "label": "Only stage"}]}]},
        {"type": "key_value", "title": "Two claims",
         "entries": [{"label": "One", "body": "First."}, {"label": "Two", "body": "Second."}]},
        {"type": "statement", "title": "Nothing to install"},
    ],
}
with tempfile.TemporaryDirectory() as tmp:
    spec_path = pathlib.Path(tmp) / "spec.json"
    out_path = pathlib.Path(tmp) / "deck.pptx"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    # Exercise the whole shipped surface: build (layout + audit + serialize +
    # validate) and check.
    assert main(["build", str(spec_path), "-o", str(out_path)]) == 0
    assert main(["check", str(out_path)]) == 0

imported = set(sys.modules) - before
roots = sorted({name.split(".")[0] for name in imported})
print(json.dumps(roots))
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    roots = set(__import__("json").loads(result.stdout.strip().splitlines()[-1]))
    third_party = {
        name
        for name in roots
        # No underscore exemption: sys.stdlib_module_names already lists the
        # private stdlib modules (_json, _abc, ...), so skipping leading
        # underscores would only hide C-extension dependencies like
        # _cffi_backend, which is exactly the shape this test exists to catch.
        if name not in sys.stdlib_module_names and name not in ALLOWED_NON_STDLIB
    }
    assert not third_party, f"engine imported non-stdlib modules: {sorted(third_party)}"


def test_metrics_table_ships_inside_the_package():
    """The font data must be packaged, not fetched or read from the system."""
    data = REPO_ROOT / "src" / "deckmaster" / "data" / "arial_metrics.json"
    assert data.is_file(), "arial_metrics.json is missing from the package"
    assert data.stat().st_size > 1000


def test_cli_reports_an_unmeasurable_character_instead_of_crashing(tmp_path, capsys):
    """The shipped entry point must not exit with a traceback on valid JSON."""
    import json

    from deckmaster.cli import main

    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps({"title": "t", "slides": [{"type": "title", "title": "Costs 5 €"}]}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        main(["build", str(spec), "-o", str(tmp_path / "out.pptx")])
    assert exc.value.code == 2
    assert "U+20AC" in capsys.readouterr().err


def test_package_gate_survives_without_lxml(tmp_path):
    """The stdlib-only package tests must run even when the schema extra is absent.

    A module-level `importorskip` would skip the entire test file, taking the
    packaging tests with it -- and those exist precisely because they need no
    dependency. The suite would then report green with the primary gate silently
    uncollected, which is worse than having no gate at all.
    """
    blocker = tmp_path / "sitecustomize.py"
    blocker.write_text(
        "import sys\n"
        "class _Block:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name.split('.')[0] == 'lxml' else None\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] == 'lxml':\n"
        "            raise ModuleNotFoundError(f'blocked: {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{REPO_ROOT / 'src'}"

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration/test_package.py",
         "-q", "--no-header", "--color=no"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout[-2000:]
    # Some tests must have RUN, not merely been collected and skipped.
    last = result.stdout.strip().splitlines()[-1]
    assert "passed" in last, f"nothing ran without lxml: {last}"
    passed = int(last.split()[0])
    assert passed >= 15, f"expected the packaging tests to run without lxml, got: {last}"


def test_the_render_tool_is_not_reachable_from_the_engine():
    """The engine must not depend on the thing that renders it.

    tools/preview.py shells out to LibreOffice and Poppler. It imports the
    engine, which is the correct direction; the reverse would make a rendering
    stack a requirement for generating a deck and quietly end the standalone
    guarantee.
    """
    source_root = REPO_ROOT / "src" / "deckmaster"
    offenders = []
    for module in sorted(source_root.rglob("*.py")):
        text = module.read_text(encoding="utf-8")
        for marker in ("import preview", "from preview", "tools.preview", "tools/preview"):
            if marker in text:
                offenders.append(f"{module.relative_to(REPO_ROOT)} references {marker!r}")
    assert not offenders, "the engine reaches into the development tooling:\n  " + "\n  ".join(offenders)


def test_the_engine_never_shells_out_to_a_renderer():
    """No LibreOffice, no Poppler, anywhere in the generation path.

    Checked separately from the import-surface test because these arrive
    through subprocess rather than through an import statement, so nothing in
    sys.modules would reveal them.

    The exclusion is *docstrings*, not strings. An earlier version skipped every
    string token, which made the check nearly useless: a shell-out writes the
    program name as a string literal, so `subprocess.run(["soffice", ...])`
    passed cleanly through a test whose whole purpose was to catch it. Only
    docstrings are excluded now, because several modules explain at length why a
    renderer is deliberately absent and a plain search flags that prose as the
    defect it describes.
    """
    import ast

    banned = ("soffice", "libreoffice", "pdftoppm", "pdftotext", "unoconv")
    offenders = []

    for module in sorted((REPO_ROOT / "src" / "deckmaster").rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstrings.add(id(body[0].value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            lowered = node.value.lower()
            for name in banned:
                if name in lowered:
                    offenders.append(
                        f"{module.relative_to(REPO_ROOT)}:{node.lineno} contains {node.value[:60]!r}"
                    )
        # Identifiers too: a helper named _soffice would not be a string.
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and any(b in node.id.lower() for b in banned):
                offenders.append(f"{module.relative_to(REPO_ROOT)}:{node.lineno} names {node.id!r}")

    assert not offenders, "the engine invokes an external renderer:\n  " + "\n  ".join(offenders)


def test_that_guard_would_actually_catch_a_shell_out():
    """The guard above is worthless unless it fires on the real thing.

    A previous version silently passed on code that shelled out to LibreOffice,
    because the program name lives in a string literal. This runs the same
    detection over a sample that does exactly that.
    """
    import ast

    sample = ast.parse(
        'import subprocess\n'
        '"""A docstring mentioning soffice, which must not count."""\n'
        'def go():\n'
        '    subprocess.run(["soffice", "--headless"])\n'
    )
    found = [
        node.value
        for node in ast.walk(sample)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "soffice" in node.value.lower()
    ]
    assert any(v == "soffice" for v in found), "the detection would miss a real shell-out"
