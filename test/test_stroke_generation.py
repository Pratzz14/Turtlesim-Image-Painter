"""Tests for mapping processed pixels into bounded horizontal strokes."""

import pytest

from turtlesim_image_painter import (
    CanvasBounds,
    Color,
    Point,
    ProcessedImage,
    Stroke,
    StrokeGenerationError,
    StrokeGenerator,
)


RED = Color(255, 0, 0)
BLUE = Color(0, 0, 255)
WHITE = Color(255, 255, 255)


def make_image(rows, background=None):
    """Build a valid processed image from color rows."""
    pixels = tuple(tuple(row) for row in rows)
    palette = tuple(sorted({color for row in pixels for color in row}))
    return ProcessedImage(
        width=len(pixels[0]),
        height=len(pixels),
        pixels=pixels,
        palette=palette,
        background=background,
    )


def test_top_and_bottom_rows_map_to_inverted_cell_centers():
    """The first image row appears above the last image row."""
    image = make_image(((RED, RED), (BLUE, BLUE)))

    strokes = StrokeGenerator().generate(image).plan.strokes

    assert strokes[0].start == Point(1.0, 7.75)
    assert strokes[0].end == Point(10.0, 7.75)
    assert strokes[1].start == Point(1.0, 3.25)
    assert strokes[1].end == Point(10.0, 3.25)


@pytest.mark.parametrize(
    'rows,expected_edges',
    [
        (((RED, RED),) * 4, (3.25, 7.75, 1.0, 10.0)),
        (((RED,) * 4,), (1.0, 10.0, 4.375, 6.625)),
    ],
)
def test_portrait_and_landscape_images_are_centered(rows, expected_edges):
    """Unused space is divided equally across opposing canvas sides."""
    image = make_image(rows)
    strokes = StrokeGenerator().generate(image).plan.strokes

    left = min(stroke.start.x for stroke in strokes)
    right = max(stroke.end.x for stroke in strokes)
    scale = (right - left) / image.width
    bottom = min(stroke.start.y for stroke in strokes) - scale / 2.0
    top = max(stroke.start.y for stroke in strokes) + scale / 2.0

    assert (left, right, bottom, top) == pytest.approx(expected_edges)
    assert left - 1.0 == pytest.approx(10.0 - right)
    assert bottom - 1.0 == pytest.approx(10.0 - top)


@pytest.mark.parametrize('width,height', [(1, 1), (7, 2), (2, 7), (9, 9)])
def test_all_endpoints_stay_inside_canvas(width, height):
    """Varied image shapes produce only safe endpoints."""
    rows = tuple(
        tuple(RED if (x + y) % 2 else BLUE for x in range(width))
        for y in range(height)
    )
    bounds = CanvasBounds(0.5, 8.25, 2.0, 9.75)

    strokes = StrokeGenerator(bounds).generate(make_image(rows)).plan.strokes

    assert strokes
    for stroke in strokes:
        for point in (stroke.start, stroke.end):
            assert bounds.min_x <= point.x <= bounds.max_x
            assert bounds.min_y <= point.y <= bounds.max_y


def test_rounding_at_canvas_edge_is_snapped_inside_bounds():
    """Harmless floating-point drift does not reject a valid plan."""
    image = make_image(((RED,) * 15,))
    bounds = CanvasBounds(0.5, 8.25, 2.0, 9.75)

    stroke = StrokeGenerator(bounds).generate(image).plan.strokes[0]

    assert stroke.start.x == bounds.min_x
    assert stroke.end.x == bounds.max_x


def test_single_pixel_produces_nonzero_complete_cell_stroke():
    """A one-pixel image spans the full limiting canvas dimension."""
    stroke = StrokeGenerator().generate(make_image(((RED,),))).plan.strokes[0]

    assert stroke.start == Point(1.0, 5.5)
    assert stroke.end == Point(10.0, 5.5)
    assert stroke.end.x > stroke.start.x


def test_row_wise_runs_merge_only_consecutive_equal_pixels():
    """Runs split at color changes and never merge between rows."""
    image = make_image(((RED, RED, BLUE, RED), (RED, RED, BLUE, RED)))

    strokes = StrokeGenerator().generate(image).plan.strokes

    assert [stroke.color for stroke in strokes] == [
        RED, BLUE, RED, RED, BLUE, RED,
    ]
    lengths = [stroke.end.x - stroke.start.x for stroke in strokes]
    assert lengths == pytest.approx([4.5, 2.25, 2.25, 4.5, 2.25, 2.25])


def test_background_exclusion_can_produce_an_empty_plan():
    """Every detected background pixel is omitted and counted."""
    image = make_image(((WHITE, WHITE), (WHITE, WHITE)), background=WHITE)

    result = StrokeGenerator().generate(image)

    assert result.plan.strokes == ()
    assert result.plan.background == WHITE
    assert result.statistics.pixel_count == 4
    assert result.statistics.palette_size == 1
    assert result.statistics.stroke_count == 0
    assert result.statistics.skipped_pixels == 4
    assert result.statistics.color_counts == ((WHITE, 4),)


def test_background_is_drawn_when_exclusion_is_disabled():
    """Disabling exclusion emits background runs without skipped pixels."""
    image = make_image(((WHITE, WHITE),), background=WHITE)

    result = StrokeGenerator(exclude_background=False).generate(image)

    assert len(result.plan.strokes) == 1
    assert result.statistics.stroke_count == 1
    assert result.statistics.skipped_pixels == 0
    assert result.statistics.color_counts == ((WHITE, 2),)


def test_exclusion_without_detected_background_draws_every_color():
    """The exclusion flag has no effect when no background was detected."""
    image = make_image(((WHITE, WHITE, RED),))

    result = StrokeGenerator().generate(image)

    assert len(result.plan.strokes) == 2
    assert result.statistics.skipped_pixels == 0
    assert result.statistics.color_counts == ((RED, 1), (WHITE, 2))


def test_statistics_count_pixels_colors_and_emitted_runs():
    """Statistics distinguish source pixels, skipped pixels, and strokes."""
    image = make_image(
        ((WHITE, RED, RED, BLUE), (WHITE, RED, BLUE, BLUE)),
        background=WHITE,
    )

    result = StrokeGenerator().generate(image)

    assert result.statistics.pixel_count == 8
    assert result.statistics.palette_size == 3
    assert result.statistics.stroke_count == 4
    assert result.statistics.skipped_pixels == 2
    assert result.statistics.color_counts == ((BLUE, 3), (RED, 3), (WHITE, 2))
    assert result.statistics.elapsed_seconds == 0.0


def test_endpoint_validator_rejects_an_unsafe_stroke():
    """The generator rejects endpoints beyond its configured limits."""
    generator = StrokeGenerator()
    unsafe = Stroke(Point(0.99, 5.0), Point(2.0, 5.0), RED)

    with pytest.raises(StrokeGenerationError):
        generator._validate_stroke(unsafe)


@pytest.mark.parametrize('exclude_background', [0, None, 'yes'])
def test_generator_rejects_non_boolean_background_option(exclude_background):
    """Background exclusion accepts explicit booleans only."""
    with pytest.raises(TypeError):
        StrokeGenerator(exclude_background=exclude_background)
