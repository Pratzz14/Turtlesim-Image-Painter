# Copyright 2026 Pratik Mahankal
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""Tests for core image and painting data models."""

import pytest

from turtlesim_image_painter import (
    CanvasBounds,
    Color,
    PaintingPlan,
    PipelineResult,
    ProcessedImage,
    Statistics,
)


RED = Color(255, 0, 0)
BLUE = Color(0, 0, 255)


def test_processed_image_accepts_matching_palette():
    """A palette containing exactly the matrix colors is valid."""
    image = ProcessedImage(
        width=2,
        height=1,
        pixels=((RED, BLUE),),
        palette=(RED, BLUE),
        background=BLUE,
    )
    assert image.palette == (RED, BLUE)


@pytest.mark.parametrize(
    'palette',
    [
        (),
        (RED, RED),
        (RED,),
        (RED, BLUE, Color(0, 255, 0)),
    ],
)
def test_processed_image_rejects_inconsistent_palette(palette):
    """Empty, duplicate, missing, and unused colors are rejected."""
    with pytest.raises(ValueError):
        ProcessedImage(
            width=2,
            height=1,
            pixels=((RED, BLUE),),
            palette=palette,
        )


def test_processed_image_rejects_background_outside_palette():
    """A detected background must be a color used by the image."""
    with pytest.raises(ValueError):
        ProcessedImage(
            width=1,
            height=1,
            pixels=((RED,),),
            palette=(RED,),
            background=BLUE,
        )


@pytest.mark.parametrize('width,height', [(0, 1), (1, 0), (-1, 1)])
def test_painting_plan_rejects_nonpositive_dimensions(width, height):
    """Painting plans require a positive canvas in both dimensions."""
    with pytest.raises(ValueError):
        PaintingPlan(strokes=(), width=width, height=height)


def test_statistics_rejects_negative_measurements():
    """Statistics cannot contain negative aggregate values."""
    with pytest.raises(ValueError):
        Statistics(stroke_count=-1)


def test_statistics_requires_consistent_total_distance():
    """Stored aggregate distance agrees with its two components."""
    with pytest.raises(ValueError):
        Statistics(
            paint_distance=2.0,
            travel_distance=3.0,
            total_distance=4.0,
        )


def test_statistics_rejects_negative_color_counts():
    """Per-color statistics cannot contain a negative count."""
    with pytest.raises(ValueError):
        Statistics(color_counts=((RED, -1),))


@pytest.mark.parametrize('width,height', [(0, 1), (1, 0), (-1, 1)])
def test_pipeline_result_rejects_invalid_original_resolution(width, height):
    """Pipeline metadata requires positive original image dimensions."""
    with pytest.raises(ValueError, match='original image dimensions'):
        PipelineResult(
            original_width=width,
            original_height=height,
            processed_image=None,
            plan_result=None,
            plan_path='plan.json',
            preview_path='preview.png',
        )


@pytest.mark.parametrize(
    'values',
    [
        (1.0, 1.0, 1.0, 10.0),
        (2.0, 1.0, 1.0, 10.0),
        (1.0, 10.0, 4.0, 4.0),
        (1.0, 10.0, 5.0, 4.0),
        (float('nan'), 10.0, 1.0, 10.0),
        (1.0, float('inf'), 1.0, 10.0),
        (True, 10.0, 1.0, 10.0),
    ],
)
def test_canvas_bounds_reject_invalid_limits(values):
    """Canvas limits must be finite numbers in increasing order."""
    with pytest.raises(ValueError):
        CanvasBounds(*values)
