"""Shared immutable data models for processing and painting images."""

from dataclasses import dataclass, field
from math import isclose, isfinite
from numbers import Real
from typing import Optional, Tuple


@dataclass(frozen=True, order=True)
class Color:
    """An eight-bit RGB color."""

    red: int
    green: int
    blue: int

    def __post_init__(self) -> None:
        """Reject channel values outside the RGB range."""
        for channel in (self.red, self.green, self.blue):
            if not isinstance(channel, int) or isinstance(channel, bool):
                raise TypeError('RGB channels must be integers')
            if not 0 <= channel <= 255:
                raise ValueError('RGB channels must be between 0 and 255')

    @classmethod
    def from_tuple(cls, value: Tuple[int, int, int]) -> 'Color':
        """Build a color from a Pillow-style tuple."""
        return cls(*value)

    def as_tuple(self) -> Tuple[int, int, int]:
        """Return a Pillow-style RGB tuple."""
        return self.red, self.green, self.blue


PixelMatrix = Tuple[Tuple[Color, ...], ...]


@dataclass(frozen=True)
class CanvasBounds:
    """Inclusive safe drawing limits in turtlesim coordinates."""

    min_x: float = 1.0
    max_x: float = 10.0
    min_y: float = 1.0
    max_y: float = 10.0

    def __post_init__(self) -> None:
        """Require finite, increasing limits on both axes."""
        values = (self.min_x, self.max_x, self.min_y, self.max_y)
        if any(
            not isinstance(value, Real)
            or isinstance(value, bool)
            or not isfinite(value)
            for value in values
        ):
            raise ValueError('canvas bounds must be finite numbers')
        if self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError('canvas minimums must be less than maximums')


@dataclass(frozen=True)
class ProcessedImage:
    """A quantized image represented as rows of RGB pixels."""

    width: int
    height: int
    pixels: PixelMatrix
    palette: Tuple[Color, ...]
    background: Optional[Color] = None

    def __post_init__(self) -> None:
        """Ensure dimensions and palette agree with the pixel matrix."""
        if self.width <= 0 or self.height <= 0:
            raise ValueError('image dimensions must be positive')
        if len(self.pixels) != self.height:
            raise ValueError('pixel rows do not match image height')
        if any(len(row) != self.width for row in self.pixels):
            raise ValueError('pixel columns do not match image width')
        if not self.palette:
            raise ValueError('image palette must not be empty')
        palette_colors = set(self.palette)
        if len(palette_colors) != len(self.palette):
            raise ValueError('image palette must not contain duplicates')
        pixel_colors = {color for row in self.pixels for color in row}
        if pixel_colors != palette_colors:
            raise ValueError('image palette must exactly match its pixel colors')
        if self.background is not None and self.background not in palette_colors:
            raise ValueError('background must be present in the image palette')


@dataclass(frozen=True)
class Point:
    """A point in turtlesim canvas coordinates."""

    x: float
    y: float


@dataclass(frozen=True)
class Stroke:
    """One colored line segment in a painting plan."""

    start: Point
    end: Point
    color: Color


@dataclass(frozen=True)
class PaintingPlan:
    """An ordered collection of strokes generated for an image."""

    strokes: Tuple[Stroke, ...]
    width: int
    height: int
    background: Optional[Color] = None

    def __post_init__(self) -> None:
        """Reject nonpositive logical image dimensions."""
        if self.width <= 0 or self.height <= 0:
            raise ValueError('plan dimensions must be positive')


@dataclass(frozen=True)
class Progress:
    """Painting progress expressed as completed and total strokes."""

    completed: int
    total: int

    def __post_init__(self) -> None:
        """Validate progress counters."""
        if self.total < 0 or not 0 <= self.completed <= self.total:
            raise ValueError('progress must satisfy 0 <= completed <= total')

    @property
    def fraction(self) -> float:
        """Return completion in the inclusive range zero to one."""
        return self.completed / self.total if self.total else 1.0


@dataclass(frozen=True)
class Statistics:
    """Summary measurements for a generated or executed plan."""

    pixel_count: int = 0
    palette_size: int = 0
    stroke_count: int = 0
    skipped_pixels: int = 0
    elapsed_seconds: float = 0.0
    color_counts: Tuple[Tuple[Color, int], ...] = field(default_factory=tuple)
    paint_distance: float = 0.0
    travel_distance: float = 0.0
    total_distance: float = 0.0

    def __post_init__(self) -> None:
        """Reject negative measurements and color counts."""
        measurements = (
            self.pixel_count,
            self.palette_size,
            self.stroke_count,
            self.skipped_pixels,
            self.elapsed_seconds,
            self.paint_distance,
            self.travel_distance,
            self.total_distance,
        )
        if any(value < 0 or not isfinite(value) for value in measurements):
            raise ValueError(
                'statistics measurements must be finite and nonnegative')
        if any(count < 0 for _, count in self.color_counts):
            raise ValueError('color counts must not be negative')
        if not isclose(
            self.total_distance,
            self.paint_distance + self.travel_distance,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            raise ValueError('total distance must equal paint plus travel')


@dataclass(frozen=True)
class PlanResult:
    """A generated painting plan and its logical-pixel statistics."""

    plan: PaintingPlan
    statistics: Statistics


@dataclass(frozen=True)
class PipelineResult:
    """The products written by the complete image-to-plan pipeline."""

    processed_image: ProcessedImage
    plan_result: PlanResult
    plan_path: str
    preview_path: str
