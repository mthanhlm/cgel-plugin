"""Offline validation of an OOXML package.

This is the gate that decides whether PowerPoint will open a file or offer to
repair it. It exists because the obvious oracle -- open the file in a viewer --
is the wrong one: LibreOffice, Keynote and Google Slides are all permissive
exactly where PowerPoint is strict. They render a package with mis-ordered child
elements, a duplicate shape id, or a dangling relationship without complaint,
so a deck can pass every render check and still greet the user with "PowerPoint
found a problem with content".

So the rules are checked directly, against the package, with no renderer
involved. That also means the check runs anywhere, offline, in milliseconds, and
gives the same answer every time.

Four families of rule:

1. **Package integrity** -- every part declared, every relationship resolving.
2. **Identifier rules** -- shape ids unique and non-zero, slide ids >= 256.
3. **Element sequence order** -- OOXML complex types mix XSD ``sequence`` with
   ``choice``. An element that is legal inside its parent is still invalid in
   the wrong position, and this is the failure that most often survives every
   viewer except the one that matters. The check distinguishes the two: it was
   built against the reference deck as a golden fixture, which immediately
   caught it treating an unbounded choice as an ordered sequence.
4. **Well-formedness** -- every part parses.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree

NS = {
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

#: Required child order for every element type this serializer emits.
#:
#: Each value is a tuple of *rank groups*. Children must appear in
#: non-decreasing rank order; children sharing a rank may appear in any order
#: and may repeat. That distinction is the whole point: OOXML mixes XSD
#: ``sequence`` (ordered) with ``choice`` (unordered, often unbounded), and
#: modelling a choice as a sequence produces confident false positives -- the
#: shape children of ``p:spTree`` are an unbounded choice, so a deck that puts a
#: ``p:grpSp`` before a ``p:sp`` is perfectly valid.
#:
#: An element missing from this table is not order-checked. The table is a
#: whitelist of what this serializer actually writes plus what real-world decks
#: contain, not an attempt to encode all of ECMA-376.
CHILD_ORDER: dict[str, tuple[tuple[str, ...], ...]] = {
    "p:presentation": (
        ("p:sldMasterIdLst",), ("p:notesMasterIdLst",), ("p:handoutMasterIdLst",),
        ("p:sldIdLst",), ("p:sldSz",), ("p:notesSz",), ("p:smartTags",),
        ("p:embeddedFontLst",), ("p:custShowLst",), ("p:photoAlbum",), ("p:custDataLst",),
        ("p:kinsoku",), ("p:defaultTextStyle",), ("p:extLst",),
    ),
    "p:sld": (("p:cSld",), ("p:clrMapOvr",), ("p:transition",), ("p:timing",), ("p:extLst",)),
    "p:sldLayout": (("p:cSld",), ("p:clrMapOvr",), ("p:transition",), ("p:timing",), ("p:hf",), ("p:extLst",)),
    "p:sldMaster": (
        ("p:cSld",), ("p:clrMap",), ("p:sldLayoutIdLst",), ("p:transition",),
        ("p:timing",), ("p:hf",), ("p:txStyles",), ("p:extLst",),
    ),
    "p:cSld": (("p:bg",), ("p:spTree",), ("p:custDataLst",), ("p:controls",), ("p:extLst",)),
    # nvGrpSpPr and grpSpPr are ordered; the shape children are an unbounded choice.
    "p:spTree": (
        ("p:nvGrpSpPr",), ("p:grpSpPr",),
        ("p:sp", "p:grpSp", "p:graphicFrame", "p:cxnSp", "p:pic", "p:contentPart"),
        ("p:extLst",),
    ),
    "p:sp": (("p:nvSpPr",), ("p:spPr",), ("p:style",), ("p:txBody",), ("p:extLst",)),
    "p:cxnSp": (("p:nvCxnSpPr",), ("p:spPr",), ("p:style",), ("p:extLst",)),
    "p:nvSpPr": (("p:cNvPr",), ("p:cNvSpPr",), ("p:nvPr",)),
    "p:nvGrpSpPr": (("p:cNvPr",), ("p:cNvGrpSpPr",), ("p:nvPr",)),
    "p:nvCxnSpPr": (("p:cNvPr",), ("p:cNvCxnSpPr",), ("p:nvPr",)),
    "p:spPr": (
        ("a:xfrm",), ("a:custGeom", "a:prstGeom"),
        ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"),
        ("a:ln",), ("a:effectLst", "a:effectDag"), ("a:scene3d",), ("a:sp3d",), ("a:extLst",),
    ),
    "p:grpSpPr": (
        ("a:xfrm",),
        ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"),
        ("a:effectLst", "a:effectDag"), ("a:scene3d",), ("a:extLst",),
    ),
    "p:txBody": (("a:bodyPr",), ("a:lstStyle",), ("a:p",)),
    "p:bgPr": (
        ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"),
        ("a:effectLst", "a:effectDag"), ("a:extLst",),
    ),
    "a:xfrm": (("a:off",), ("a:ext",), ("a:chOff",), ("a:chExt",)),
    "a:ln": (
        ("a:noFill", "a:solidFill", "a:gradFill", "a:pattFill"),
        ("a:prstDash", "a:custDash"), ("a:round", "a:bevel", "a:miter"),
        ("a:headEnd",), ("a:tailEnd",), ("a:extLst",),
    ),
    # Runs, breaks and fields interleave freely; endParaRPr must come last.
    "a:p": (("a:pPr",), ("a:r", "a:br", "a:fld"), ("a:endParaRPr",)),
    "a:pPr": (
        ("a:lnSpc",), ("a:spcBef",), ("a:spcAft",), ("a:buClrTx", "a:buClr"),
        ("a:buSzTx", "a:buSzPct", "a:buSzPts"), ("a:buFontTx", "a:buFont"),
        ("a:buNone", "a:buAutoNum", "a:buChar"), ("a:tabLst",), ("a:defRPr",), ("a:extLst",),
    ),
    "a:r": (("a:rPr",), ("a:t",)),
    "a:rPr": (
        ("a:ln",),
        ("a:noFill", "a:solidFill", "a:gradFill", "a:blipFill", "a:pattFill", "a:grpFill"),
        ("a:effectLst", "a:effectDag"), ("a:highlight",), ("a:uLnTx", "a:uLn"),
        ("a:uFillTx", "a:uFill"), ("a:latin",), ("a:ea",), ("a:cs",), ("a:sym",),
        ("a:hlinkClick",), ("a:hlinkMouseOver",), ("a:rtl",), ("a:extLst",),
    ),
    "a:bodyPr": (
        ("a:prstTxWarp",), ("a:noAutofit", "a:normAutofit", "a:spAutoFit"),
        ("a:scene3d",), ("a:sp3d", "a:flatTx"), ("a:extLst",),
    ),
    "a:theme": (("a:themeElements",), ("a:objectDefaults",), ("a:extraClrSchemeLst",), ("a:custClrLst",), ("a:extLst",)),
    "a:themeElements": (("a:clrScheme",), ("a:fontScheme",), ("a:fmtScheme",), ("a:extLst",)),
    "a:fmtScheme": (("a:fillStyleLst",), ("a:lnStyleLst",), ("a:effectStyleLst",), ("a:bgFillStyleLst",)),
    "a:clrScheme": (
        ("a:dk1",), ("a:lt1",), ("a:dk2",), ("a:lt2",), ("a:accent1",), ("a:accent2",),
        ("a:accent3",), ("a:accent4",), ("a:accent5",), ("a:accent6",), ("a:hlink",),
        ("a:folHlink",), ("a:extLst",),
    ),
    "a:fontScheme": (("a:majorFont",), ("a:minorFont",), ("a:extLst",)),
}

_TAG = re.compile(r"^\{([^}]+)\}(.+)$")
_URI_TO_PREFIX = {uri: prefix for prefix, uri in NS.items()}


class PackageInvalid(Exception):
    """Raised when a package would not open cleanly."""


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if self.errors:
            listed = "\n  - ".join(self.errors)
            raise PackageInvalid(f"{len(self.errors)} package error(s):\n  - {listed}")


def _qname(tag: str) -> str:
    """Turn ``{uri}local`` into ``prefix:local`` for the known namespaces."""
    match = _TAG.match(tag)
    if not match:
        return tag
    uri, local = match.groups()
    return f"{_URI_TO_PREFIX.get(uri, uri)}:{local}"


def _check_order(element: ElementTree.Element, part: str, errors: list[str]) -> None:
    name = _qname(element.tag)
    groups = CHILD_ORDER.get(name)
    if groups:
        rank = {child: i for i, group in enumerate(groups) for child in group}
        seen = -1
        previous = ""
        for child in element:
            child_name = _qname(child.tag)
            position = rank.get(child_name)
            if position is None:
                continue
            # Equal ranks are fine: those children are an XSD choice, so their
            # relative order carries no meaning and they may repeat.
            if position < seen:
                expected = " < ".join("|".join(g) for g in groups)
                errors.append(
                    f"{part}: <{child_name}> appears after <{previous}> inside <{name}>, "
                    f"but the schema requires the order {expected}"
                )
            else:
                seen, previous = position, child_name
    for child in element:
        _check_order(child, part, errors)


def _read(archive: zipfile.ZipFile, name: str, errors: list[str]) -> bytes | None:
    """Read one part, recording rather than raising on a damaged entry.

    A stored entry can still fail its CRC, and a truncated archive can list a
    part it cannot produce. Both surface here as `BadZipFile`, and this function
    is on the path `deckmaster check` takes over arbitrary user files, so
    neither may escape as a traceback.
    """
    try:
        return archive.read(name)
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        errors.append(f"{name}: cannot be extracted ({type(exc).__name__}: {exc})")
        return None


def _parse(archive: zipfile.ZipFile, name: str, errors: list[str]) -> ElementTree.Element | None:
    """Read and parse one XML part, recording any failure."""
    payload = _read(archive, name, errors)
    if payload is None:
        return None
    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        errors.append(f"{name}: not well-formed XML ({exc})")
        return None


#: OPC types a relationship id as `xsd:ID`, which is an NCName -- so `rId1`,
#: `R1` and `rel1` are all legal, and a rule demanding `rId` followed by digits
#: would reject perfectly good third-party packages. Since `check` is pointed at
#: arbitrary files, this matches the actual type rather than the convention.
_NCNAME = re.compile(r"^[A-Za-z_][\w.\-]*$")

#: What a failed string interpolation leaves behind, matched against the *whole*
#: identifier rather than as a substring. `rIdundefined` is a real shipped bug:
#: it is a valid NCName, so the type check passes, but it can never resolve and
#: the reference it belongs to is silently broken.
#:
#: The anchoring matters. A substring test would reject `rIdFinance` and
#: `rel_maintenance`, both of which contain "nan" and both of which are perfectly
#: ordinary identifiers -- and this validator is pointed at third-party packages,
#: which is exactly where such names appear.
_INTERPOLATION_ACCIDENT = re.compile(
    r"^(?:rId|rel|r)?(?:undefined|nan|null|none)$", re.IGNORECASE
)


def _check_relationships(archive: zipfile.ZipFile, rels_part: str, errors: list[str]) -> None:
    """Check ids and target hygiene for every relationship in one part.

    Ids are scoped per part, so two slides may both use `rId1`; a duplicate
    inside one file is what breaks.

    Targets are checked here rather than alongside the resolve-to-a-part check
    because that one reads through `_rel_targets`, which necessarily skips
    external relationships -- a URL has no part to resolve to. External targets
    are precisely where an unencoded space appears, so checking only internal
    ones would miss the case entirely.
    """
    try:
        root = ElementTree.fromstring(archive.read(rels_part))
    except (ElementTree.ParseError, zipfile.BadZipFile, OSError, KeyError):
        return  # already reported by the well-formedness pass

    seen: set[str] = set()
    for rel in root.findall("rel:Relationship", NS):
        rid = rel.get("Id", "")
        if not _NCNAME.match(rid):
            errors.append(
                f"{rels_part}: relationship id {rid!r} is not a valid XML name, "
                "so the references pointing at it cannot resolve"
            )
        elif _INTERPOLATION_ACCIDENT.match(rid):
            errors.append(
                f"{rels_part}: relationship id {rid!r} looks like a failed string interpolation "
                "rather than an identifier"
            )
        if rid in seen:
            errors.append(f"{rels_part}: duplicate relationship id {rid!r}")
        seen.add(rid)

        target = rel.get("Target", "")
        if " " in target:
            # A documented cause of PowerPoint declaring the presentation
            # corrupt. It arises whenever a URL or filename is written through
            # without percent-encoding.
            errors.append(
                f"{rels_part}: relationship {rid} target {target!r} contains an unescaped space; "
                "percent-encode it"
            )


def _rel_targets(archive: zipfile.ZipFile, rels_part: str) -> dict[str, str]:
    """Relationship id -> resolved part name, for one .rels part.

    Failures are swallowed here rather than recorded: every part goes through
    the well-formedness pass first, so a broken .rels has already been reported
    and recording it again would double-count one fault.
    """
    if rels_part not in archive.namelist():
        return {}
    try:
        root = ElementTree.fromstring(archive.read(rels_part))
    except (ElementTree.ParseError, zipfile.BadZipFile, OSError, KeyError):
        return {}
    base = posixpath.dirname(posixpath.dirname(rels_part))
    targets: dict[str, str] = {}
    for rel in root.findall("rel:Relationship", NS):
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        resolved = posixpath.normpath(posixpath.join(base, target)).lstrip("/")
        targets[rid] = resolved
    return targets


def validate_package(path) -> ValidationReport:
    """Check a .pptx package against the rules that decide whether it opens.

    Anything wrong with the file is reported as an error, never raised. This
    function is pointed at arbitrary user-supplied paths -- including, routinely,
    the wrong file -- and a validator that crashes on input it was built to
    reject would be a poor validator.
    """
    report = ValidationReport()
    errors = report.errors

    try:
        archive = zipfile.ZipFile(path)
    except FileNotFoundError:
        errors.append(f"{path}: no such file")
        return report
    except IsADirectoryError:
        errors.append(f"{path}: is a directory, not a .pptx file")
        return report
    except OSError as exc:
        errors.append(f"{path}: cannot be read ({exc})")
        return report
    except zipfile.BadZipFile:
        # The usual cause is pointing `check` at the JSON spec rather than the
        # built deck, so the message names that possibility.
        errors.append(f"{path}: not a ZIP container, so not a .pptx package")
        return report

    with archive:
        names = set(archive.namelist())

        # --- 1. Content types ---------------------------------------------
        if "[Content_Types].xml" not in names:
            errors.append("missing [Content_Types].xml")
            return report

        types_root = _parse(archive, "[Content_Types].xml", errors)
        if types_root is None:
            return report
        declared_defaults = [d.get("Extension", "").lower() for d in types_root.findall("ct:Default", NS)]
        defaults = set(declared_defaults)
        overrides = {o.get("PartName", "").lstrip("/") for o in types_root.findall("ct:Override", NS)}

        # A repeated Default is an OPC violation in its own right, and the
        # usual cause is a writer appending one per part instead of per
        # extension. Harmless-looking, and PowerPoint rejects it.
        for extension in sorted({e for e in declared_defaults if declared_defaults.count(e) > 1}):
            errors.append(
                f"[Content_Types].xml: Extension {extension!r} is declared more than once; "
                "each extension takes exactly one Default"
            )

        for name in sorted(names):
            if name.endswith("/"):
                continue
            extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if name in overrides or extension in defaults:
                continue
            errors.append(f"part {name!r} has no content type (no Override and no Default for .{extension})")

        for declared in sorted(overrides):
            if declared not in names:
                errors.append(f"[Content_Types].xml declares {declared!r}, which is not in the package")

        # --- 2. Well-formedness and element order -------------------------
        parsed: dict[str, ElementTree.Element] = {}
        for name in sorted(names):
            if not name.endswith(".xml") and not name.endswith(".rels"):
                continue
            root = _parse(archive, name, errors)
            if root is None:
                continue
            parsed[name] = root
            _check_order(root, name, errors)

        # --- 3. Relationships ---------------------------------------------
        for name in sorted(names):
            if not name.endswith(".rels"):
                continue
            for rid, target in _rel_targets(archive, name).items():
                if target not in names:
                    errors.append(f"{name}: relationship {rid} targets {target!r}, which is not in the package")
            _check_relationships(archive, name, errors)

        # Every r:id referenced by a part must exist in that part's .rels.
        for name, root in sorted(parsed.items()):
            if name.endswith(".rels"):
                continue
            rels_part = f"{posixpath.dirname(name)}/_rels/{posixpath.basename(name)}.rels"
            available = set(_rel_targets(archive, rels_part))
            r_attr = f"{{{NS['r']}}}id"
            for element in root.iter():
                rid = element.get(r_attr)
                if rid and rid not in available:
                    errors.append(
                        f"{name}: <{_qname(element.tag)}> references {rid}, "
                        f"which {rels_part} does not declare"
                    )

        # --- 4. Identifier rules ------------------------------------------
        presentation = parsed.get("ppt/presentation.xml")
        if presentation is None:
            errors.append("missing ppt/presentation.xml")
        else:
            id_lst = presentation.find("p:sldIdLst", NS)
            if id_lst is None or not list(id_lst):
                errors.append("ppt/presentation.xml declares no slides")
            else:
                seen_ids: set[int] = set()
                for slide_id in id_lst.findall("p:sldId", NS):
                    raw = slide_id.get("id", "")
                    value = int(raw) if raw.isdigit() else -1
                    # PowerPoint rejects slide ids below 256 outright.
                    if not 256 <= value <= 2147483647:
                        errors.append(f"ppt/presentation.xml: sldId id={raw!r} is outside the valid range 256-2147483647")
                    if value in seen_ids:
                        errors.append(f"ppt/presentation.xml: duplicate sldId id={raw!r}")
                    seen_ids.add(value)

        for name, root in sorted(parsed.items()):
            if not re.match(r"ppt/(slides|slideLayouts|slideMasters)/[^/]+\.xml$", name):
                continue
            shape_ids: dict[int, str] = {}
            for cnv in root.iter(f"{{{NS['p']}}}cNvPr"):
                raw = cnv.get("id", "")
                value = int(raw) if raw.isdigit() else -1
                shape_name = cnv.get("name", "")
                if value <= 0:
                    errors.append(f"{name}: shape {shape_name!r} has invalid cNvPr id={raw!r} (must be a positive integer)")
                elif value in shape_ids:
                    errors.append(
                        f"{name}: cNvPr id={value} is used by both {shape_ids[value]!r} and {shape_name!r}; "
                        "ids must be unique within a slide"
                    )
                else:
                    shape_ids[value] = shape_name

    return report
