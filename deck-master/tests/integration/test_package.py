"""The gate for "PowerPoint opens it without repair".

Two complementary halves, in the order they appear below.

**Packaging rules**, checked by the engine's own stdlib-only validator: every
relationship resolves, every part is typed, identifiers are unique and in range.
These live *between* parts, so no XML schema can express them.

**Schema conformance**, checked against the published ISO-29500 schemas: element
order, cardinality and datatypes *inside* each part. These the specification
already states, so they are deferred to it rather than restated by hand.

Everything runs offline. One test wants a golden fixture -- a presentation
authored by a real tool -- because any rule that rejects such a file is a rule
that is wrong about OOXML, not one that found a defect. That fixture was
internal material and is not published here, so the test skips; see the README
for how to supply your own before tightening a validator rule.

One caveat worth stating plainly: conformance to the standard is not the same as
confirmation against PowerPoint, which has tolerances and strictnesses of its
own. This is the strongest offline proxy available, not proof.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from deckmaster.validate.opc import PackageInvalid, validate_package
from tests.conftest import REFERENCE_DECK


def test_generated_package_is_valid(built_pptx):
    report = validate_package(built_pptx)
    assert report.ok, "\n".join(report.errors)


def test_reference_deck_passes_the_same_rules():
    """Guards against false positives.

    A validator that rejects a package PowerPoint itself is happy with would
    block real work, and would be quietly ignored soon after.
    """
    if not REFERENCE_DECK.is_file():
        pytest.skip("reference deck not present")
    report = validate_package(REFERENCE_DECK)
    assert report.ok, "\n".join(report.errors)


def test_every_part_is_declared_in_content_types(built_pptx):
    with zipfile.ZipFile(built_pptx) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        content_types = archive.read("[Content_Types].xml").decode("utf-8")
    for name in names:
        if name == "[Content_Types].xml":
            continue
        extension = name.rsplit(".", 1)[-1]
        assert f'PartName="/{name}"' in content_types or f'Extension="{extension}"' in content_types, name


def test_required_parts_are_present(built_pptx):
    with zipfile.ZipFile(built_pptx) as archive:
        names = set(archive.namelist())
    for required in (
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
        "ppt/slideMasters/slideMaster1.xml",
        "ppt/slideLayouts/slideLayout1.xml",
        "ppt/theme/theme1.xml",
        "docProps/core.xml",
        "docProps/app.xml",
    ):
        assert required in names, required


class TestValidatorCatchesRealDefects:
    """The validator must fail on the defects PowerPoint actually rejects.

    Each case rewrites a valid package with one specific fault injected, so a
    passing result would mean the rule is not doing anything.
    """

    def _rebuild(self, source, target, transform):
        with zipfile.ZipFile(source) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        transform(parts)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in parts.items():
                archive.writestr(name, payload)
        return target

    def test_duplicate_shape_id_is_caught(self, built_pptx, tmp_path):
        def transform(parts):
            slide = parts["ppt/slides/slide1.xml"].decode("utf-8")
            parts["ppt/slides/slide1.xml"] = slide.replace('id="3"', 'id="2"', 1).encode("utf-8")

        broken = self._rebuild(built_pptx, tmp_path / "dup-id.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("unique within a slide" in e for e in report.errors)

    def test_slide_id_below_256_is_caught(self, built_pptx, tmp_path):
        def transform(parts):
            xml = parts["ppt/presentation.xml"].decode("utf-8")
            parts["ppt/presentation.xml"] = xml.replace('sldId id="256"', 'sldId id="12"').encode("utf-8")

        broken = self._rebuild(built_pptx, tmp_path / "low-id.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("256-2147483647" in e for e in report.errors)

    def test_dangling_relationship_is_caught(self, built_pptx, tmp_path):
        def transform(parts):
            rels = parts["ppt/_rels/presentation.xml.rels"].decode("utf-8")
            parts["ppt/_rels/presentation.xml.rels"] = rels.replace(
                "slides/slide1.xml", "slides/missing.xml"
            ).encode("utf-8")

        broken = self._rebuild(built_pptx, tmp_path / "dangling.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("not in the package" in e for e in report.errors)

    def test_wrong_element_order_is_caught(self, built_pptx, tmp_path):
        """A fill emitted after the line inside spPr -- legal elements, illegal order."""

        def transform(parts):
            slide = parts["ppt/slides/slide1.xml"].decode("utf-8")
            broken = slide.replace(
                '<a:solidFill><a:srgbClr val="1F5FA8"/></a:solidFill><a:ln><a:noFill/></a:ln>',
                '<a:ln><a:noFill/></a:ln><a:solidFill><a:srgbClr val="1F5FA8"/></a:solidFill>',
                1,
            )
            assert broken != slide, "fixture did not contain the expected fragment"
            parts["ppt/slides/slide1.xml"] = broken.encode("utf-8")

        broken = self._rebuild(built_pptx, tmp_path / "order.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("appears after" in e for e in report.errors)

    def test_malformed_xml_is_caught(self, built_pptx, tmp_path):
        def transform(parts):
            parts["ppt/slides/slide1.xml"] = b"<p:sld><unclosed>"

        broken = self._rebuild(built_pptx, tmp_path / "malformed.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("not well-formed" in e for e in report.errors)


def test_report_raises_with_every_problem_listed(built_pptx, tmp_path):
    with zipfile.ZipFile(built_pptx) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["ppt/presentation.xml"] = parts["ppt/presentation.xml"].decode("utf-8").replace(
        'sldId id="256"', 'sldId id="1"'
    ).encode("utf-8")
    target = tmp_path / "raises.pptx"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)

    with pytest.raises(PackageInvalid):
        validate_package(target).raise_if_invalid()


class TestValidatorNeverRaisesOnBadInput:
    """`check` is pointed at arbitrary files, so nothing may escape as a traceback."""

    def test_missing_file(self, tmp_path):
        report = validate_package(tmp_path / "nope.pptx")
        assert not report.ok
        assert any("no such file" in e for e in report.errors)

    def test_not_a_zip(self, tmp_path):
        path = tmp_path / "spec.json"
        path.write_text('{"title": "not a deck"}', encoding="utf-8")
        report = validate_package(path)
        assert not report.ok
        assert any("not a ZIP container" in e for e in report.errors)

    def test_directory(self, tmp_path):
        report = validate_package(tmp_path)
        assert not report.ok

    def test_zip_with_malformed_content_types(self, tmp_path):
        """A well-formed ZIP whose [Content_Types].xml will not parse."""
        path = tmp_path / "broken-ct.pptx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types><unclosed>")
        report = validate_package(path)
        assert not report.ok
        assert any("not well-formed" in e for e in report.errors)

    def test_zip_with_no_content_types(self, tmp_path):
        path = tmp_path / "empty.pptx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("something.xml", "<a/>")
        report = validate_package(path)
        assert not report.ok
        assert any("[Content_Types].xml" in e for e in report.errors)

    def test_corrupt_entry_is_reported_not_raised(self, built_pptx, tmp_path):
        """A stored entry whose bytes no longer match its CRC."""
        payload = bytearray(built_pptx.read_bytes())
        marker = payload.find(b"<?xml")
        assert marker > 0
        payload[marker : marker + 5] = b"XXXXX"
        path = tmp_path / "corrupt.pptx"
        path.write_bytes(bytes(payload))
        # Must return a report either way; the requirement is that it never raises.
        report = validate_package(path)
        assert isinstance(report.errors, list)


# ---------------------------------------------------------------------------
# Schema conformance
#
# The rules above are OPC packaging rules -- relationships resolve, parts are
# typed, identifiers are unique -- which no XML schema can express, so they are
# written by hand. The rules below are the ones *inside* a part, and those the
# specification already states, so they are deferred to it entirely.
#
# Keeping both in this file is deliberate: they answer the same question ("will
# this package open?") and the project's package-validate check runs this file.
# ---------------------------------------------------------------------------

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"

#: Parts this engine emits that PresentationML defines. `docProps` and the
#: relationship parts are governed by other schemas and are covered instead by
#: the packaging rules in test_package.py.
PRESENTATION_PARTS = (
    "ppt/presentation.xml",
    "ppt/slideMasters/slideMaster1.xml",
    "ppt/slideLayouts/slideLayout1.xml",
    # DrawingML rather than PresentationML, but pml.xsd imports dml-main so the
    # same schema object resolves it.
    "ppt/theme/theme1.xml",
)

#: Parts deliberately outside the schema check, each with its reason. All are
#: governed by OPC or document-property schemas that pml.xsd does not import,
#: so covering them would mean bundling further schema sets to check parts built
#: from fixed templates with escaped values.
#:
#: None of them is unchecked. `[Content_Types].xml` is the most heavily verified
#: part in the package by the packaging rules above -- every part typed, no
#: duplicate Default, no Override naming a part that is absent -- and all three
#: go through the well-formedness pass. Revisit if any becomes dynamic.
SCHEMA_EXEMPT = (
    "[Content_Types].xml",
    "docProps/core.xml",
    "docProps/app.xml",
)


@pytest.fixture(scope="session")
def lxml_etree():
    """Import lxml, skipping only the tests that need it.

    Deliberately a fixture rather than a module-level ``importorskip``. At module
    level a missing lxml skips this entire file -- including the packaging tests
    above, which are stdlib-only precisely so they run everywhere -- and the
    suite would report green with the whole package gate silently uncollected.
    A check that can vanish without saying so is worse than no check.
    """
    return pytest.importorskip(
        "lxml.etree",
        reason="lxml is a test-only extra; the engine itself never imports it",
    )


@pytest.fixture(scope="session")
def schema(lxml_etree):
    return lxml_etree.XMLSchema(lxml_etree.parse(str(SCHEMA_DIR / "pml.xsd")))


def _parts(pptx: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(pptx) as archive:
        names = [n for n in archive.namelist() if n.endswith(".xml")]
        return {n: archive.read(n) for n in names}


def _errors(lxml_etree, schema, payload: bytes) -> list[str]:
    document = lxml_etree.fromstring(payload)
    if schema.validate(document):
        return []
    return [str(e.message) for e in schema.error_log]


def test_every_slide_validates(lxml_etree, schema, built_pptx):
    parts = _parts(built_pptx)
    slides = sorted(n for n in parts if n.startswith("ppt/slides/slide"))
    assert slides, "the fixture deck produced no slides"
    for name in slides:
        errors = _errors(lxml_etree, schema, parts[name])
        assert not errors, f"{name} violates the schema:\n  " + "\n  ".join(errors[:5])


@pytest.mark.parametrize("part", PRESENTATION_PARTS)
def test_presentation_parts_validate(lxml_etree, schema, built_pptx, part):
    parts = _parts(built_pptx)
    assert part in parts, f"{part} missing from the package"
    errors = _errors(lxml_etree, schema, parts[part])
    assert not errors, f"{part} violates the schema:\n  " + "\n  ".join(errors[:5])


class TestTheSchemaCanActuallyFail:
    """Prove the check is capable of rejecting something.

    A validator that has only ever passed is indistinguishable from one that
    always passes. Each case injects one defect into a real generated slide and
    asserts the schema rejects it — and each defect is a documented cause of
    PowerPoint's repair prompt, not an invented one.
    """

    @pytest.fixture
    def slide(self, built_pptx) -> str:
        return _parts(built_pptx)["ppt/slides/slide1.xml"].decode("utf-8")

    def _reject(self, lxml_etree, schema, xml: str, original: str) -> list[str]:
        assert xml != original, "the fixture did not contain the fragment this test edits"
        return _errors(lxml_etree, schema, xml.encode("utf-8"))

    def test_text_body_with_no_paragraph(self, lxml_etree, schema, slide):
        """The most-reported repair cause: a:p is required, not optional."""
        broken = slide.replace(
            "<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>",
            "<p:txBody><a:bodyPr/><a:lstStyle/></p:txBody>",
            1,
        )
        assert self._reject(lxml_etree, schema, broken, slide)

    def test_elements_out_of_sequence(self, lxml_etree, schema, slide):
        """Both elements are legal inside spPr; this order is not."""
        broken = slide.replace(
            '<a:solidFill><a:srgbClr val="1F5FA8"/></a:solidFill><a:ln><a:noFill/></a:ln>',
            '<a:ln><a:noFill/></a:ln><a:solidFill><a:srgbClr val="1F5FA8"/></a:solidFill>',
            1,
        )
        assert self._reject(lxml_etree, schema, broken, slide)

    def test_non_integer_coordinate(self, lxml_etree, schema, slide):
        """Python 3 true division producing '914400.0' is a known repair cause."""
        broken = slide.replace('<a:off x="', '<a:off x="914400.5" y="0"/><a:off x="', 1)
        assert self._reject(lxml_etree, schema, broken, slide)

    def test_text_body_before_shape_properties(self, lxml_etree, schema, slide):
        broken = slide.replace(
            "<p:spPr>", "<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody><p:spPr>", 1
        )
        assert self._reject(lxml_etree, schema, broken, slide)

    def test_unknown_element(self, lxml_etree, schema, slide):
        broken = slide.replace("<p:spPr>", "<p:notAThing/><p:spPr>", 1)
        assert self._reject(lxml_etree, schema, broken, slide)


def test_schema_bundle_is_complete():
    """Every schemaLocation import resolves inside the bundle.

    A missing import makes lxml fail at load with a message about the schema
    rather than the document, which is a confusing way to discover that the
    fixture set was trimmed too far.
    """
    import re

    referenced: set[str] = set()
    for path in SCHEMA_DIR.glob("*.xsd"):
        referenced.update(re.findall(r'schemaLocation="([^"]+)"', path.read_text()))
    missing = {name for name in referenced if not (SCHEMA_DIR / name).is_file()}
    assert not missing, f"schema bundle is missing imports: {sorted(missing)}"


class TestPackageRulesNoSchemaCanExpress:
    """Repair causes that live between parts rather than inside one.

    An XML schema validates a part in isolation, so it can say nothing about
    relationship targets, identifier formatting, or content-type declarations.
    Those are OPC packaging rules and remain the hand-written validator's job --
    which is also why they must ship without a dependency.
    """

    def _rebuild(self, source, target, transform):
        with zipfile.ZipFile(source) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        transform(parts)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in parts.items():
                archive.writestr(name, payload)
        return target

    def test_unescaped_space_in_a_relationship_target(self, built_pptx, tmp_path):
        def transform(parts):
            key = "ppt/_rels/presentation.xml.rels"
            parts[key] = parts[key].decode().replace(
                "slides/slide1.xml", "slides/slide 1.xml"
            ).encode()

        broken = self._rebuild(built_pptx, tmp_path / "space.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("unescaped space" in e for e in report.errors)

    def test_malformed_relationship_id(self, built_pptx, tmp_path):
        """`rIdundefined` is a real bug that shipped in a mature library."""

        def transform(parts):
            key = "ppt/slides/_rels/slide1.xml.rels"
            parts[key] = parts[key].decode().replace('Id="rId1"', 'Id="rIdundefined"').encode()

        broken = self._rebuild(built_pptx, tmp_path / "badrid.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("failed string interpolation" in e for e in report.errors)

    def test_duplicate_relationship_id_within_one_part(self, built_pptx, tmp_path):
        def transform(parts):
            key = "ppt/_rels/presentation.xml.rels"
            parts[key] = parts[key].decode().replace('Id="rId2"', 'Id="rId1"').encode()

        broken = self._rebuild(built_pptx, tmp_path / "duprid.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("duplicate relationship id" in e for e in report.errors)

    def test_duplicate_content_type_default(self, built_pptx, tmp_path):
        def transform(parts):
            key = "[Content_Types].xml"
            parts[key] = parts[key].decode().replace(
                '<Default Extension="xml"',
                '<Default Extension="xml" ContentType="application/xml"/><Default Extension="xml"',
                1,
            ).encode()

        broken = self._rebuild(built_pptx, tmp_path / "dupct.pptx", transform)
        report = validate_package(broken)
        assert not report.ok
        assert any("declared more than once" in e for e in report.errors)


def test_no_xml_part_is_silently_outside_the_schema_check(built_pptx):
    """Every part is either schema-checked or listed as a deliberate exemption.

    Without this, adding a part is enough to quietly grow the unchecked surface:
    it would simply not appear in either list and nobody would notice.
    """
    parts = {n for n in _parts(built_pptx) if n.endswith(".xml")}
    slides = {n for n in parts if n.startswith("ppt/slides/slide")}
    accounted = slides | set(PRESENTATION_PARTS) | set(SCHEMA_EXEMPT)
    unaccounted = parts - accounted
    assert not unaccounted, (
        f"these parts are neither schema-checked nor exempt: {sorted(unaccounted)}. "
        "Add them to PRESENTATION_PARTS, or to SCHEMA_EXEMPT with the reason."
    )


class TestRelationshipIdRule:
    """The rule must reject the accident without rejecting ordinary names.

    `check` is pointed at third-party packages, so a false positive here means
    telling someone their working file is corrupt. Both directions are asserted.
    """

    @pytest.mark.parametrize(
        "rid", ["rIdundefined", "rIdNaN", "undefined", "null", "rIdnone", "relNaN"]
    )
    def test_failed_interpolation_is_rejected(self, rid):
        from deckmaster.validate.opc import _INTERPOLATION_ACCIDENT

        assert _INTERPOLATION_ACCIDENT.match(rid), rid

    @pytest.mark.parametrize(
        "rid",
        [
            "rId1",
            "rId42",
            "R1",  # OPC types the id as xsd:ID, so this is legal
            "rel1",
            "rIdFinance",  # contains "nan" as a substring
            "rel_maintenance",  # contains "nan" as a substring
            "noneOfYourBusiness",
            "nullable_target",
        ],
    )
    def test_ordinary_identifiers_are_accepted(self, rid):
        from deckmaster.validate.opc import _INTERPOLATION_ACCIDENT, _NCNAME

        assert _NCNAME.match(rid), f"{rid} should be a valid NCName"
        assert not _INTERPOLATION_ACCIDENT.match(rid), f"{rid} falsely flagged as an accident"


def test_unescaped_space_in_an_external_target_is_caught(built_pptx, tmp_path):
    """A hyperlink is the case the rule exists for, and it is external.

    Reading targets through the resolve-to-a-part helper would skip external
    relationships entirely, so this asserts the check sees them.
    """
    with zipfile.ZipFile(built_pptx) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}

    key = "ppt/slides/_rels/slide1.xml.rels"
    parts[key] = parts[key].decode().replace(
        "</Relationships>",
        '<Relationship Id="rId9" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.com/a b" TargetMode="External"/></Relationships>',
    ).encode()

    broken = tmp_path / "extspace.pptx"
    with zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)

    report = validate_package(broken)
    assert not report.ok
    assert any("unescaped space" in e for e in report.errors), report.errors


def test_a_valid_external_hyperlink_is_accepted(built_pptx, tmp_path):
    """The companion assertion: a properly encoded URL must not be flagged."""
    with zipfile.ZipFile(built_pptx) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}

    key = "ppt/slides/_rels/slide1.xml.rels"
    parts[key] = parts[key].decode().replace(
        "</Relationships>",
        '<Relationship Id="rId9" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
        'Target="https://example.com/a%20b?x=1" TargetMode="External"/></Relationships>',
    ).encode()

    fine = tmp_path / "extok.pptx"
    with zipfile.ZipFile(fine, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)

    report = validate_package(fine)
    assert report.ok, report.errors


def test_bundled_schemas_ship_their_notice():
    """Redistribution is conditional on the notice travelling with the files.

    Nothing about behaviour can catch a provenance error -- the schemas validate
    identically whatever their source -- so the condition is asserted directly.
    The previous copies were taken from a source whose terms forbade it, and the
    only thing that would have caught that is a check like this one.
    """
    notice = SCHEMA_DIR / "NOTICE"
    assert notice.is_file(), "tests/schemas/NOTICE is missing; redistribution requires it"
    text = notice.read_text(encoding="utf-8")
    for required in ("ECMA International", "ECMA-376", "WITHOUT MODIFICATION"):
        assert required in text, f"NOTICE must record {required!r}"


def test_every_bundled_schema_is_accounted_for_in_the_notice():
    """A file added here without a notice entry is a file with no stated origin."""
    notice = (SCHEMA_DIR / "NOTICE").read_text(encoding="utf-8")
    for schema_file in sorted(SCHEMA_DIR.glob("*.xsd")):
        assert schema_file.name in notice, (
            f"{schema_file.name} is bundled but not listed in NOTICE"
        )


def test_schemas_are_protected_from_line_ending_conversion():
    """Git must store the schema files verbatim, not normalised.

    The bundled schemas use CRLF line terminators. With `core.autocrlf` set to
    `input` or `true` -- common on Windows and WSL checkouts -- git rewrites
    them to LF on commit, so the stored blobs are no longer the published files
    while the working tree still looks correct. That silently breaks the
    unmodified condition the NOTICE depends on, and nothing else here would
    reveal it.
    """
    attributes = SCHEMA_DIR.parent.parent / ".gitattributes"
    assert attributes.is_file(), (
        ".gitattributes is missing; without it git may normalise the bundled schemas"
    )
    rules = attributes.read_text(encoding="utf-8")
    assert "tests/schemas/*.xsd" in rules and "-text" in rules, (
        "the rule disabling end-of-line conversion for tests/schemas/*.xsd is missing"
    )


def test_bundled_schemas_match_their_published_checksums():
    """Assert the licence condition directly: the files are unmodified.

    This is stronger than any proxy. An earlier version of this test checked for
    CRLF line endings, on the assumption that the distribution used them
    throughout -- it does not, some files ship with LF and some with CRLF, so
    that test failed on correct files. Checksums make no assumption about
    content and catch every kind of modification, including the line-ending
    conversion that prompted the check.

    SHA256SUMS was generated from the ECMA archive itself. If this fails, do not
    regenerate it: find out what changed the files.
    """
    import hashlib

    manifest = SCHEMA_DIR / "SHA256SUMS"
    assert manifest.is_file(), "tests/schemas/SHA256SUMS is missing"

    expected = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            expected[name.strip()] = digest

    present = {p.name for p in SCHEMA_DIR.glob("*.xsd")}
    assert present == set(expected), (
        f"schema set differs from the manifest: "
        f"unlisted={sorted(present - set(expected))}, missing={sorted(set(expected) - present)}"
    )

    for name, digest in sorted(expected.items()):
        actual = hashlib.sha256((SCHEMA_DIR / name).read_bytes()).hexdigest()
        assert actual == digest, (
            f"{name} does not match the published file. It must be redistributed "
            "unmodified; see tests/schemas/NOTICE."
        )


def test_the_golden_fixture_cannot_be_committed_by_accident():
    """A real presentation may be internal material, so it must stay untracked.

    It was published in this repository's history once, because a gitignore
    negation existed to keep it tracked. Removing the file without removing that
    negation would have let the next person re-add it silently.
    """
    import subprocess

    from tests.conftest import REFERENCE_DECK, REPO_ROOT

    result = subprocess.run(
        ["git", "check-ignore", "-v", REFERENCE_DECK.name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{REFERENCE_DECK.name} is not gitignored; a real presentation dropped in "
        "to run the golden-fixture test could be committed and published"
    )

    tracked = subprocess.run(
        ["git", "ls-files", REFERENCE_DECK.name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert not tracked.stdout.strip(), f"{REFERENCE_DECK.name} is tracked by git"
