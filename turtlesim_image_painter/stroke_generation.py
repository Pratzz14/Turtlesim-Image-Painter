"""Convert processed pixel rows into bounded horizontal strokes."""

from collections import Counter
from math import isfinite, ulp
from typing import Iterator, Tuple

from .models import (
    CanvasBounds,
    Color,
    PaintingPlan,
    PlanResult,
    Point,
    ProcessedImage,
    Statistics,
    Stroke,
)


class StrokeGenerationError(ValueError):
    """Raised when a safe painting plan cannot be generated."""


class StrokeGenerator:
    """Generate centered, row-wise strokes inside safe canvas bounds."""

    def __init__(
        self,
        bounds: CanvasBounds = CanvasBounds(),
        exclude_background: bool = True,
    ) -> None:
        """Configure safe bounds and background exclusion."""
        if not isinstance(bounds, CanvasBounds):
            raise TypeError('bounds must be CanvasBounds')
        if not isinstance(exclude_background, bool):
            raise TypeError('exclude_background must be a boolean')
        self.bounds = bounds
        self.exclude_background = exclude_background

    @staticmethod
    def _runs(row: Tuple[Color, ...]) -> Iterator[Tuple[int, int, Color]]:
        """Yield maximal same-color runs as half-open column ranges."""
        start = 0
        color = row[0]
        for column in range(1, len(row)):
            if row[column] != color:
                yield start, column, color
                start = column
                color = row[column]
        yield start, len(row), color

    def _validate_stroke(self, stroke: Stroke) -> None:
        """Reject non-finite endpoints outside the configured bounds."""
        bounds = self.bounds
        for point in (stroke.start, stroke.end):
            if not isfinite(point.x) or not isfinite(point.y):
                raise StrokeGenerationError('stroke endpoint must be finite')
            if not (
                bounds.min_x <= point.x <= bounds.max_x
                and bounds.min_y <= point.y <= bounds.max_y
            ):
                raise StrokeGenerationError(
                    'stroke endpoint lies outside canvas bounds')

    @staticmethod
    def _bounded_coordinate(value: float, minimum: float, maximum: float) -> float:
        """Snap rounding noise at a boundary and reject unsafe values."""
        if not isfinite(value):
            raise StrokeGenerationError('stroke endpoint must be finite')
        if value < minimum:
            tolerance = 8 * max(ulp(value), ulp(minimum))
            if minimum - value <= tolerance:
                return minimum
            raise StrokeGenerationError(
                'stroke endpoint lies outside canvas bounds')
        if value > maximum:
            tolerance = 8 * max(ulp(value), ulp(maximum))
            if value - maximum <= tolerance:
                return maximum
            raise StrokeGenerationError(
                'stroke endpoint lies outside canvas bounds')
        return value

    def generate(self, image: ProcessedImage) -> PlanResult:
        """Convert a processed image into an ordered painting plan."""
        if not isinstance(image, ProcessedImage):
            raise TypeError('image must be ProcessedImage')

        bounds = self.bounds
        canvas_width = bounds.max_x - bounds.min_x
        canvas_height = bounds.max_y - bounds.min_y
        scale = min(
            canvas_width / image.width,
            canvas_height / image.height,
        )
        painted_width = image.width * scale
        painted_height = image.height * scale
        left = bounds.min_x + (canvas_width - painted_width) / 2.0
        bottom = bounds.min_y + (canvas_height - painted_height) / 2.0

        strokes = []
        skipped_pixels = 0
        for row_index, row in enumerate(image.pixels):
            y = self._bounded_coordinate(
                bottom + (image.height - row_index - 0.5) * scale,
                bounds.min_y,
                bounds.max_y,
            )
            for start, end, color in self._runs(row):
                run_length = end - start
                if (
                    self.exclude_background
                    and image.background is not None
                    and color == image.background
                ):
                    skipped_pixels += run_length
                    continue
                stroke = Stroke(
                    start=Point(
                        self._bounded_coordinate(
                            left + start * scale,
                            bounds.min_x,
                            bounds.max_x,
                        ),
                        y,
                    ),
                    end=Point(
                        self._bounded_coordinate(
                            left + end * scale,
                            bounds.min_x,
                            bounds.max_x,
                        ),
                        y,
                    ),
                    color=color,
                )
                self._validate_stroke(stroke)
                strokes.append(stroke)

        counts = Counter(color for row in image.pixels for color in row)
        plan = PaintingPlan(
            strokes=tuple(strokes),
            width=image.width,
            height=image.height,
            background=image.background,
        )
        statistics = Statistics(
            pixel_count=image.width * image.height,
            palette_size=len(image.palette),
            stroke_count=len(strokes),
            skipped_pixels=skipped_pixels,
            color_counts=tuple(
                (color, counts[color]) for color in image.palette
            ),
        )
        return PlanResult(plan=plan, statistics=statistics)
