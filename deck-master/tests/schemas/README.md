# ISO/IEC 29500-4:2016 schemas

The published XML schemas for Office Open XML, used by the schema-conformance
tests in `tests/integration/test_package.py` to validate generated parts against
the standard itself rather than against rules written by hand.

**Provenance and terms are in `NOTICE`, alongside these files. Read it before
touching anything here — redistribution depends on the files staying
unmodified.**

## What is covered

Every slide, plus `presentation.xml`, `slideMaster1.xml`, `slideLayout1.xml` and
`theme1.xml`.

Not covered: `[Content_Types].xml` and `docProps/*`, which answer to OPC and
document-property schemas that `pml.xsd` does not import. Those are listed in
`SCHEMA_EXEMPT` with their reasons, and a test fails if a part ever ends up in
neither list — so the unchecked surface cannot grow quietly.

## Why these are here

The alternative was to encode the element-order and cardinality rules manually,
which is what `validate/opc.py` does for the handful of elements this engine
emits. That approach reimplements, by hand and incompletely, a specification
that already exists in machine-readable form — and a hand-maintained table
drifts, while the schema is authoritative by construction.

Tests confirm these schemas reject the defects that matter rather than passing
vacuously. Each of these is injected into a real generated slide and asserted to
fail: a text body containing no paragraph (the most-reported cause of
PowerPoint's repair prompt), an element emitted out of sequence, a text body
placed before shape properties, a non-integer value in an integer-typed
attribute, and an element the specification does not define.

## Why they are under `tests/` and not `src/`

Validating against them requires `lxml`, and this project's defining constraint
is that the generation path runs on the standard library alone. Keeping the
schemas and their validator in the test suite means the dependency is a
development tool, exactly as `pytest` is, and nothing a user installs changes.

Two tests guard that boundary: `test_no_third_party_module_is_imported_when_building_a_deck`
builds a deck in a clean subprocess and fails on any third-party import, and
`test_package_gate_survives_without_lxml` runs the package tests with `lxml`
blocked to prove the dependency-free gate still runs without it.

## What this does not prove

Conformance to the standard is not the same as confirmation against PowerPoint,
which has tolerances and strictnesses of its own — it accepts some things the
schema rejects, and rejects some things the schema accepts. This is the
strongest offline proxy available here, not proof.
