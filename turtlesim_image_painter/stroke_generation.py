"""Convert processed pixels into bounded horizontal or vertical strokes."""

from collections import Counter
from dataclasses import dataclass
from itertools import product
from math import hypot, isfinite, ulp
from typing import Dict, Iterator, List, Sequence, Tuple

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


@dataclass(frozen=True)
class _Run:
    """A stroke with its logical source position and painted area."""

    line: int
    start_offset: int
    end_offset: int
    stroke: Stroke


class StrokeGenerator:
    """Generate centered, axis-aware strokes inside safe canvas bounds."""

    def __init__(
        self,
        bounds: CanvasBounds = CanvasBounds(),
        exclude_background: bool = True,
        color_order: str = 'largest_first',
        path_order: str = 'raster',
        stroke_orientation: str = 'auto',
    ) -> None:
        """Configure safe bounds and background exclusion."""
        if not isinstance(bounds, CanvasBounds):
            raise TypeError('bounds must be CanvasBounds')
        if not isinstance(exclude_background, bool):
            raise TypeError('exclude_background must be a boolean')
        if color_order != 'largest_first':
            raise StrokeGenerationError(
                'unsupported color order {!r}; supported values: '
                'largest_first'.format(color_order))
        if path_order not in ('raster', 'snake'):
            raise StrokeGenerationError(
                'unsupported path order {!r}; supported values: '
                'raster, snake'.format(path_order))
        if stroke_orientation not in ('auto', 'horizontal', 'vertical'):
            raise StrokeGenerationError(
                'unsupported stroke orientation {!r}; supported values: '
                'auto, horizontal, vertical'.format(stroke_orientation))
        self.bounds = bounds
        self.exclude_background = exclude_background
        self.color_order = color_order
        self.path_order = path_order
        self.stroke_orientation = stroke_orientation

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

    def _horizontal_runs(
        self,
        image: ProcessedImage,
        left: float,
        bottom: float,
        scale: float,
    ) -> Dict[Color, List[_Run]]:
        """Return horizontal candidates grouped by color."""
        grouped: Dict[Color, List[_Run]] = {}
        bounds = self.bounds
        for row_index, row in enumerate(image.pixels):
            y = self._bounded_coordinate(
                bottom + (image.height - row_index - 0.5) * scale,
                bounds.min_y,
                bounds.max_y,
            )
            for start, end, color in self._runs(row):
                if self._excluded(image, color):
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
                grouped.setdefault(color, []).append(_Run(
                    line=row_index,
                    start_offset=start,
                    end_offset=end,
                    stroke=stroke,
                ))
        return grouped

    def _vertical_runs(
        self,
        image: ProcessedImage,
        left: float,
        bottom: float,
        scale: float,
    ) -> Dict[Color, List[_Run]]:
        """Return vertical candidates grouped by color."""
        grouped: Dict[Color, List[_Run]] = {}
        bounds = self.bounds
        for column_index in range(image.width):
            column = tuple(
                image.pixels[row][column_index]
                for row in range(image.height)
            )
            x = self._bounded_coordinate(
                left + (column_index + 0.5) * scale,
                bounds.min_x,
                bounds.max_x,
            )
            for start, end, color in self._runs(column):
                if self._excluded(image, color):
                    continue
                stroke = Stroke(
                    start=Point(
                        x,
                        self._bounded_coordinate(
                            bottom + (image.height - start) * scale,
                            bounds.min_y,
                            bounds.max_y,
                        ),
                    ),
                    end=Point(
                        x,
                        self._bounded_coordinate(
                            bottom + (image.height - end) * scale,
                            bounds.min_y,
                            bounds.max_y,
                        ),
                    ),
                    color=color,
                )
                self._validate_stroke(stroke)
                grouped.setdefault(color, []).append(_Run(
                    line=column_index,
                    start_offset=start,
                    end_offset=end,
                    stroke=stroke,
                ))
        return grouped

    def _excluded(self, image: ProcessedImage, color: Color) -> bool:
        """Return whether a detected background color should be omitted."""
        return (
            self.exclude_background
            and image.background is not None
            and color == image.background
        )

    def _ordered_strokes(self, runs: List[_Run]) -> Tuple[Stroke, ...]:
        """Order one axis candidate using raster or snake traversal."""
        if self.path_order == 'raster':
            ordered_runs = sorted(
                runs,
                key=lambda run: (run.line, run.start_offset),
            )
        else:
            ordered_runs = sorted(
                runs,
                key=lambda run: (
                    run.line,
                    run.start_offset if run.line % 2 == 0
                    else -run.end_offset,
                ),
            )
        strokes = []
        for run in ordered_runs:
            stroke = run.stroke
            if self.path_order == 'snake' and run.line % 2 == 1:
                stroke = Stroke(stroke.end, stroke.start, stroke.color)
            strokes.append(stroke)
        return tuple(strokes)

    @staticmethod
    def _travel_distance(strokes: Sequence[Stroke]) -> float:
        """Return pen-up distance between consecutive strokes."""
        return sum(
            hypot(
                current.start.x - previous.end.x,
                current.start.y - previous.end.y,
            )
            for previous, current in zip(strokes, strokes[1:])
        )

    def _select_layers(
        self,
        colors: Sequence[Color],
        horizontal: Dict[Color, Tuple[Stroke, ...]],
        vertical: Dict[Color, Tuple[Stroke, ...]],
    ) -> Tuple[Stroke, ...]:
        """Choose per-color orientations by stroke count, then travel."""
        if self.stroke_orientation == 'horizontal':
            return tuple(
                stroke for color in colors for stroke in horizontal[color])
        if self.stroke_orientation == 'vertical':
            return tuple(
                stroke for color in colors for stroke in vertical[color])

        layer_options = []
        for color in colors:
            candidates = (
                ('horizontal', horizontal[color]),
                ('vertical', vertical[color]),
            )
            minimum_count = min(len(strokes) for _, strokes in candidates)
            layer_options.append(tuple(
                candidate for candidate in candidates
                if len(candidate[1]) == minimum_count
            ))

        best_strokes: Tuple[Stroke, ...] = ()
        best_key = None
        for selection in product(*layer_options):
            strokes = tuple(
                stroke
                for _, layer_strokes in selection
                for stroke in layer_strokes
            )
            orientation_key = tuple(
                orientation == 'vertical'
                for orientation, _ in selection
            )
            key = (self._travel_distance(strokes), orientation_key)
            if best_key is None or key < best_key:
                best_key = key
                best_strokes = strokes
        return best_strokes

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

        counts = Counter(color for row in image.pixels for color in row)
        skipped_pixels = 0
        if (
            self.exclude_background
            and image.background is not None
        ):
            skipped_pixels = counts[image.background]
        painted_counts = Counter({
            color: count
            for color, count in counts.items()
            if not self._excluded(image, color)
        })

        horizontal_runs = self._horizontal_runs(image, left, bottom, scale)
        vertical_runs = self._vertical_runs(image, left, bottom, scale)
        horizontal = {
            color: self._ordered_strokes(runs)
            for color, runs in horizontal_runs.items()
        }
        vertical = {
            color: self._ordered_strokes(runs)
            for color, runs in vertical_runs.items()
        }

        colors = sorted(
            painted_counts,
            key=lambda color: (
                -painted_counts[color],
                color.red,
                color.green,
                color.blue,
            ),
        )
        strokes = self._select_layers(colors, horizontal, vertical)

        paint_distance = sum(
            hypot(
                stroke.end.x - stroke.start.x,
                stroke.end.y - stroke.start.y,
            )
            for stroke in strokes
        )
        travel_distance = self._travel_distance(strokes)

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
            paint_distance=paint_distance,
            travel_distance=travel_distance,
            total_distance=paint_distance + travel_distance,
        )
        return PlanResult(plan=plan, statistics=statistics)
