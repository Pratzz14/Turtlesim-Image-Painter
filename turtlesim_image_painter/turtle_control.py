"""Pure configuration and feedback-control helpers for turtlesim."""

from dataclasses import dataclass
from math import atan2, hypot, isfinite, pi
from numbers import Real
from typing import Mapping, Tuple

from .models import CanvasBounds, Point


@dataclass(frozen=True)
class VelocityCommand:
    """A planar velocity command independent of ROS message types."""

    linear: float = 0.0
    angular: float = 0.0


@dataclass(frozen=True)
class PainterConfig:
    """Validated image-planning and turtlesim execution configuration."""

    image_path: str = ''
    plan_output: str = ''
    preview_output: str = ''
    max_width: int = 80
    max_height: int = 80
    palette_size: int = 4
    transparency_color: Tuple[int, int, int] = (255, 255, 255)
    background_threshold: float = 0.5
    allow_upscale: bool = False
    exclude_background: bool = True
    color_order: str = 'largest_first'
    path_order: str = 'raster'
    pen_width: int = 6
    background_r: int = 255
    background_g: int = 255
    background_b: int = 255
    canvas_min_x: float = 1.0
    canvas_max_x: float = 10.0
    canvas_min_y: float = 1.0
    canvas_max_y: float = 10.0
    control_rate_hz: float = 20.0
    linear_gain: float = 3.0
    angular_gain: float = 12.0
    max_linear_speed: float = 4.0
    max_angular_speed: float = 8.0
    position_tolerance: float = 0.05
    angle_tolerance: float = 0.02
    service_timeout_sec: float = 5.0
    pose_timeout_sec: float = 2.0
    movement_timeout_sec: float = 30.0
    color_change_pause_sec: float = 1.0
    dry_run: bool = False
    stroke_orientation: str = 'auto'
    parking_x: float = 0.5
    parking_y: float = 0.5
    background_tolerance: int = 24

    def __post_init__(self) -> None:
        """Reject unsafe pipeline, geometry, and controller settings."""
        CanvasBounds(
            self.canvas_min_x,
            self.canvas_max_x,
            self.canvas_min_y,
            self.canvas_max_y,
        )

        for name in ('image_path', 'plan_output', 'preview_output'):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f'{name} must be a string')
        if not isinstance(self.color_order, str):
            raise TypeError('color_order must be a string')
        if self.color_order != 'largest_first':
            raise ValueError('color_order must be largest_first')
        if not isinstance(self.path_order, str):
            raise TypeError('path_order must be a string')
        if self.path_order not in ('raster', 'snake'):
            raise ValueError('path_order must be raster or snake')
        if not isinstance(self.stroke_orientation, str):
            raise TypeError('stroke_orientation must be a string')
        if self.stroke_orientation not in ('auto', 'horizontal', 'vertical'):
            raise ValueError(
                'stroke_orientation must be auto, horizontal, or vertical')

        for name in ('max_width', 'max_height'):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f'{name} must be a positive integer')
        if (
            not isinstance(self.palette_size, int)
            or isinstance(self.palette_size, bool)
            or not 2 <= self.palette_size <= 8
        ):
            raise ValueError('palette_size must be an integer from 2 to 8')

        if len(self.transparency_color) != 3:
            raise ValueError('transparency_color must have three channels')
        if (
            not isinstance(self.background_tolerance, int)
            or isinstance(self.background_tolerance, bool)
            or not 0 <= self.background_tolerance <= 255
        ):
            raise ValueError(
                'background_tolerance must be an integer from 0 to 255')

        for name in (
            'background_r', 'background_g', 'background_b',
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 255
            ):
                raise ValueError(f'{name} must be an integer from 0 to 255')
        for channel in self.transparency_color:
            if (
                not isinstance(channel, int)
                or isinstance(channel, bool)
                or not 0 <= channel <= 255
            ):
                raise ValueError(
                    'transparency_color channels must be integers from 0 to 255')
        if (
            not isinstance(self.pen_width, int)
            or isinstance(self.pen_width, bool)
            or not 1 <= self.pen_width <= 255
        ):
            raise ValueError('pen_width must be an integer from 1 to 255')

        for name in ('allow_upscale', 'exclude_background', 'dry_run'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f'{name} must be a boolean')
        if (
            not isinstance(self.background_threshold, Real)
            or isinstance(self.background_threshold, bool)
            or not isfinite(self.background_threshold)
            or not 0.0 <= self.background_threshold <= 1.0
        ):
            raise ValueError(
                'background_threshold must be between zero and one')

        positive = (
            'control_rate_hz', 'linear_gain', 'angular_gain',
            'max_linear_speed', 'max_angular_speed',
            'parking_x', 'parking_y',
            'position_tolerance', 'angle_tolerance',
            'service_timeout_sec', 'pose_timeout_sec',
            'movement_timeout_sec',
        )
        for name in positive:
            value = getattr(self, name)
            if (
                not isinstance(value, Real)
                or isinstance(value, bool)
                or not isfinite(value)
                or value <= 0.0
            ):
                raise ValueError(f'{name} must be a positive finite number')
        if self.angle_tolerance > pi:
            raise ValueError('angle_tolerance must not exceed pi')
        if (
            not isinstance(self.color_change_pause_sec, Real)
            or isinstance(self.color_change_pause_sec, bool)
            or not isfinite(self.color_change_pause_sec)
            or self.color_change_pause_sec < 0.0
        ):
            raise ValueError(
                'color_change_pause_sec must be a nonnegative finite number')

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> 'PainterConfig':
        """Build configuration from declared ROS parameter values."""
        options = {
            name: values[name] for name in cls.__dataclass_fields__
        }
        options['transparency_color'] = tuple(options['transparency_color'])
        return cls(**options)

    @classmethod
    def defaults(cls) -> Mapping[str, object]:
        """Return parameter names and their default values."""
        instance = cls()
        return {
            name: getattr(instance, name)
            for name in cls.__dataclass_fields__
        }

    @property
    def bounds(self) -> CanvasBounds:
        """Return the safe drawing bounds."""
        return CanvasBounds(
            self.canvas_min_x,
            self.canvas_max_x,
            self.canvas_min_y,
            self.canvas_max_y,
        )


def distance_between(first: Point, second: Point) -> float:
    """Return Euclidean distance between two points."""
    return hypot(second.x - first.x, second.y - first.y)


def heading_between(first: Point, second: Point) -> float:
    """Return the heading from one point to another."""
    return atan2(second.y - first.y, second.x - first.x)


def normalize_angle(angle: float) -> float:
    """Wrap an angle into the negative-inclusive pi range."""
    return (angle + pi) % (2.0 * pi) - pi


def clamp_signed(value: float, limit: float) -> float:
    """Clamp a signed value to symmetric limits."""
    return max(-limit, min(limit, value))


def position_arrived(current: Point, target: Point, tolerance: float) -> bool:
    """Return whether the target is within positional tolerance."""
    return distance_between(current, target) <= tolerance


def angle_arrived(current: float, target: float, tolerance: float) -> bool:
    """Return whether the shortest angle error is within tolerance."""
    return abs(normalize_angle(target - current)) <= tolerance


def alignment_command(
    current: float,
    target: float,
    gain: float,
    maximum: float,
) -> VelocityCommand:
    """Return a clamped in-place angular command."""
    error = normalize_angle(target - current)
    return VelocityCommand(angular=clamp_signed(gain * error, maximum))


def drive_command(
    current: Point,
    heading: float,
    target: Point,
    linear_gain: float,
    angular_gain: float,
    max_linear: float,
    max_angular: float,
) -> VelocityCommand:
    """Return clamped feedback velocities toward a target point."""
    distance = distance_between(current, target)
    target_heading = heading_between(current, target)
    return VelocityCommand(
        linear=min(max_linear, linear_gain * distance),
        angular=clamp_signed(
            angular_gain * normalize_angle(target_heading - heading),
            max_angular,
        ),
    )
