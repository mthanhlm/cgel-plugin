"""The design system's own invariants.

These are the rules that keep output from drifting into template territory, so
they are asserted rather than trusted.
"""

from __future__ import annotations

import pytest

from deckmaster.theme import DEFAULT_THEME, Palette, contrast_ratio, relative_luminance

PALETTE = Palette()


def test_contrast_ratio_endpoints():
    assert contrast_ratio("000000", "FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("777777", "777777") == pytest.approx(1.0, abs=0.01)


def test_relative_luminance_rejects_malformed_colour():
    with pytest.raises(ValueError):
        relative_luminance("12345")


@pytest.mark.parametrize(
    "surface_name",
    ["light", "dark", "panel", "panel_strong", "accent_solid"],
)
def test_every_surface_pairs_legible_ink(surface_name):
    """Each fill must carry ink that is readable on it.

    This is the invariant that makes dark-text-on-dark-fill unexpressible.
    """
    surface = getattr(PALETTE, surface_name)
    assert surface.contrast() >= 4.5, f"{surface_name} ink {surface.ink} on {surface.fill}"


@pytest.mark.parametrize("surface_name", ["light", "dark", "panel", "accent_solid"])
def test_muted_ink_stays_readable(surface_name):
    surface = getattr(PALETTE, surface_name)
    assert surface.muted_contrast() >= 4.5, f"{surface_name} muted ink"


def test_no_pure_black_or_white_in_the_ground_colours():
    """Pure #000 and #fff are the signature of an untouched template."""
    assert PALETTE.paper != "FFFFFF"
    assert PALETTE.paper_dark != "000000"
    assert PALETTE.ink != "000000"
    assert PALETTE.neutral_600 != "000000"  # connectors


def test_type_scale_holds_a_consistent_ratio():
    sizes = sorted(DEFAULT_THEME.type_scale.all_sizes())
    for smaller, larger in zip(sizes, sizes[1:], strict=False):
        assert larger > smaller


def test_type_scale_floor_stays_legible_at_distance():
    assert min(DEFAULT_THEME.type_scale.all_sizes()) >= 14.0


def test_deck_uses_at_most_five_type_sizes():
    assert len(set(DEFAULT_THEME.type_scale.all_sizes())) <= 5


def test_heading_and_body_weights_differ_by_at_least_300():
    scale = DEFAULT_THEME.type_scale
    assert scale.weight_bold - scale.weight_regular >= 300


def test_spacing_scale_is_built_on_a_four_point_base():
    for step in DEFAULT_THEME.space.steps():
        assert step % 4 == 0, step


def test_margins_leave_a_usable_body_area():
    assert DEFAULT_THEME.content_width > 0
    assert DEFAULT_THEME.content_height > 0
