"""The intermediate document model.

Authors describe *what a slide means*; they never describe where anything sits.
A slide carries a message, a diagram carries ranks and edges, and the layout
engines turn that into geometry. Keeping coordinates out of the model is what
lets the same deck be re-laid-out, re-themed, or re-targeted at a second output
format without the author touching content.

Content limits are enforced here, at construction, rather than discovered later
by the audit. A 140-character slide title is not a layout problem to be solved
by shrinking type -- it is a writing problem, and the earliest, loudest place to
say so is the moment the slide is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .text.metrics import assert_supported
from .typography import normalize

# Content limits. These come from how slides are actually read -- at distance,
# in seconds -- not from what happens to fit.
MAX_TITLE_CHARS = 60
MAX_TITLE_WORDS = 9
MAX_LEAD_CHARS = 120
MAX_NODE_LABEL_CHARS = 28
MAX_NODE_LABEL_WORDS = 5
MAX_NODE_CAPTION_CHARS = 48
MAX_EDGE_LABEL_WORDS = 3
MAX_ENTRY_LABEL_CHARS = 34
MAX_ENTRY_BODY_CHARS = 160


class ContentTooLong(ValueError):
    """Raised when text exceeds the limit for its role."""


def _check(text: str, *, role: str, max_chars: int, max_words: int | None = None) -> str:
    text = normalize(text).strip()
    if not text:
        raise ValueError(f"{role} must not be empty")
    # Reject unmeasurable characters here, where the field is still named.
    # Deferring this to layout turns a clear content error into a traceback.
    assert_supported(text, role)
    if len(text) > max_chars:
        raise ContentTooLong(
            f"{role} is {len(text)} characters, over the {max_chars}-character limit: {text!r}. "
            "Shorten it -- a slide that needs more words needs fewer ideas."
        )
    if max_words is not None:
        words = len(text.split())
        if words > max_words:
            raise ContentTooLong(
                f"{role} is {words} words, over the {max_words}-word limit: {text!r}."
            )
    return text


# --------------------------------------------------------------------------
# Diagram model
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Node:
    """One box in a diagram.

    `emphasis` marks the single node under discussion. It changes fill and ink,
    never stroke weight -- thickening a stroke changes the node's outer bounds
    and pulls it out of alignment with its rank.
    """

    id: str
    label: str
    caption: str | None = None
    emphasis: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("node id must not be empty")
        object.__setattr__(
            self,
            "label",
            _check(self.label, role=f"node {self.id!r} label", max_chars=MAX_NODE_LABEL_CHARS, max_words=MAX_NODE_LABEL_WORDS),
        )
        if self.caption is not None:
            object.__setattr__(
                self,
                "caption",
                _check(self.caption, role=f"node {self.id!r} caption", max_chars=MAX_NODE_CAPTION_CHARS),
            )


@dataclass(frozen=True, slots=True)
class Rank:
    """A vertical column of nodes -- one stage of a left-to-right flow.

    When `boxed` is set the rank is drawn as a titled container, which is how a
    diagram shows that several nodes belong to one system. A rank is the only
    grouping device in this idiom: one containment layer, never a box inside a
    box inside a band.
    """

    nodes: tuple[Node, ...]
    label: str | None = None
    caption: str | None = None
    boxed: bool = False

    def __post_init__(self) -> None:
        if not self.nodes:
            raise ValueError("a rank must contain at least one node")
        if self.label is not None:
            object.__setattr__(
                self, "label", _check(self.label, role="rank label", max_chars=MAX_NODE_LABEL_CHARS, max_words=MAX_NODE_LABEL_WORDS)
            )
        if self.caption is not None:
            object.__setattr__(
                self, "caption", _check(self.caption, role="rank caption", max_chars=MAX_NODE_CAPTION_CHARS)
            )
        if self.boxed and self.label is None:
            raise ValueError("a boxed rank needs a label; an unlabelled container groups nothing")


@dataclass(frozen=True, slots=True)
class Edge:
    """A connector between two nodes.

    `dashed` carries meaning -- it distinguishes a secondary or asynchronous
    relationship from a primary one. It is never decoration.
    """

    source: str
    target: str
    label: str | None = None
    dashed: bool = False

    def __post_init__(self) -> None:
        if self.source == self.target:
            raise ValueError(f"edge cannot connect {self.source!r} to itself")
        if self.label is not None:
            object.__setattr__(
                self, "label", _check(self.label, role="edge label", max_chars=24, max_words=MAX_EDGE_LABEL_WORDS)
            )


@dataclass(frozen=True, slots=True)
class Flow:
    """A left-to-right layered diagram: ranks of nodes, connected by edges."""

    ranks: tuple[Rank, ...]
    edges: tuple[Edge, ...] = ()

    def __post_init__(self) -> None:
        if not self.ranks:
            raise ValueError("a flow needs at least one rank")
        ids = [node.id for rank in self.ranks for node in rank.nodes]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate node ids: {sorted(duplicates)}")
        known = set(ids)
        for edge in self.edges:
            for endpoint in (edge.source, edge.target):
                if endpoint not in known:
                    raise ValueError(
                        f"edge references unknown node {endpoint!r}; known ids: {sorted(known)}"
                    )

    def nodes(self) -> tuple[Node, ...]:
        return tuple(node for rank in self.ranks for node in rank.nodes)


# --------------------------------------------------------------------------
# Slides
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Entry:
    """One label-and-body pair in a key-value slide."""

    label: str
    body: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "label", _check(self.label, role="entry label", max_chars=MAX_ENTRY_LABEL_CHARS)
        )
        object.__setattr__(
            self, "body", _check(self.body, role="entry body", max_chars=MAX_ENTRY_BODY_CHARS)
        )


@dataclass(frozen=True, slots=True)
class Slide:
    """Base for every slide type. `title` is the slide's one message."""

    title: str

    def __post_init__(self) -> None:
        _set_title(self)


def _set_title(slide: "Slide") -> None:
    """Validate and normalise a slide title in place.

    Called directly rather than through ``super().__post_init__()``: with
    ``slots=True`` the dataclass decorator builds a replacement class, which
    leaves the zero-argument ``super()`` closure pointing at the discarded
    original. A plain helper sidesteps that entirely.
    """
    object.__setattr__(
        slide,
        "title",
        _check(slide.title, role="slide title", max_chars=MAX_TITLE_CHARS, max_words=MAX_TITLE_WORDS),
    )


@dataclass(frozen=True, slots=True)
class TitleSlide(Slide):
    """The cover. States the deck's claim, not just its name."""

    subtitle: str | None = None

    def __post_init__(self) -> None:
        _set_title(self)
        if self.subtitle is not None:
            object.__setattr__(
                self, "subtitle", _check(self.subtitle, role="title-slide subtitle", max_chars=MAX_LEAD_CHARS)
            )


@dataclass(frozen=True, slots=True)
class StatementSlide(Slide):
    """A single idea on a dark ground. Deliberately almost empty."""

    subtitle: str | None = None

    def __post_init__(self) -> None:
        _set_title(self)
        if self.subtitle is not None:
            object.__setattr__(
                self, "subtitle", _check(self.subtitle, role="statement subtitle", max_chars=MAX_LEAD_CHARS)
            )


@dataclass(frozen=True, slots=True)
class KeyValueSlide(Slide):
    """Two or three claims, each with one line of support.

    Rows are separated by hairline rules rather than drawn as cards: a rule
    costs one line of ink and does the same separating work that a bordered box
    does with far more.
    """

    entries: tuple[Entry, ...]
    subtitle: str | None = None
    dark: bool = False

    def __post_init__(self) -> None:
        _set_title(self)
        if not 2 <= len(self.entries) <= 4:
            raise ValueError(
                f"a key-value slide holds 2-4 entries, got {len(self.entries)}; "
                "more than four rows stops being a hierarchy and becomes a list"
            )
        if self.subtitle is not None:
            object.__setattr__(
                self, "subtitle", _check(self.subtitle, role="key-value subtitle", max_chars=MAX_LEAD_CHARS)
            )


@dataclass(frozen=True, slots=True)
class DiagramSlide(Slide):
    """A slide whose body is a diagram. The default slide type."""

    flow: Flow
    subtitle: str | None = None
    footnote: str | None = None

    def __post_init__(self) -> None:
        _set_title(self)
        if self.subtitle is not None:
            object.__setattr__(
                self, "subtitle", _check(self.subtitle, role="diagram subtitle", max_chars=MAX_LEAD_CHARS)
            )
        if self.footnote is not None:
            object.__setattr__(
                self, "footnote", _check(self.footnote, role="diagram footnote", max_chars=MAX_LEAD_CHARS)
            )


@dataclass(frozen=True, slots=True)
class Deck:
    """A complete presentation."""

    title: str
    slides: tuple[Slide, ...] = field(default_factory=tuple)
    author: str = ""

    def __post_init__(self) -> None:
        if not self.slides:
            raise ValueError("a deck needs at least one slide")
        # These two reach the package's document properties, so they are the
        # only strings that would otherwise arrive at XML emission unchecked.
        object.__setattr__(
            self, "title", _check(self.title, role="deck title", max_chars=MAX_LEAD_CHARS)
        )
        if self.author:
            object.__setattr__(
                self, "author", _check(self.author, role="deck author", max_chars=MAX_ENTRY_LABEL_CHARS)
            )
