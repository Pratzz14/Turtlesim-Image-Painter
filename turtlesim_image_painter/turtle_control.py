"""Pure configuration and feedback-control helpers for turtlesim."""

from dataclasses import dataclass
from math import atan2, hypot, isfinite, pi
from numbers import Real
from typing import Mapping

from .models import CanvasBounds, Point


@dataclass(frozen=True)
class VelocityCommand:
    """A planar velocity command independent of ROS message types."""

    linear: float = 0.0
    angular: float = 0.0


@dataclass(frozen=True)
class PainterConfig:
    """Validated startup configuration for one horizontal line."""

    start_x: float = 2.0
    end_x: float = 9.0
    line_y: float = 5.5
    line_r: int = 255
    line_g: int = 0
    line_b: int = 0
    pen_width: int = 3
    background_r: int = 255
    background_g: int = 255
    background_b: int = 255
    canvas_min_x: float = 1.0
    canvas_max_x: float = 10.0
    canvas_min_y: float = 1.0
    canvas_max_y: float = 10.0
    control_rate_hz: float = 20.0
    linear_gain: float = 1.5
    angular_gain: float = 6.0
    max_linear_speed: float = 2.0
    max_angular_speed: float = 4.0
    position_tolerance: float = 0.05
    angle_tolerance: float = 0.02
    service_timeout_sec: float = 5.0
    pose_timeout_sec: float = 2.0

    def __post_init__(self) -> None:
        """Reject unsafe geometry, colors, and controller settings."""
        bounds = CanvasBounds(
            self.canvas_min_x,
            self.canvas_max_x,
            self.canvas_min_y,
            self.canvas_max_y,
        )
        for name in ('start_x', 'end_x', 'line_y'):
            value = getattr(self, name)
            if (
                not isinstance(value, Real)
                or isinstance(value, bool)
                or not isfinite(value)
            ):
                raise ValueError(f'{name} must be a finite number')
        if not bounds.min_x <= self.start_x <= bounds.max_x:
            raise ValueError('start_x must lie inside the canvas bounds')
        if not bounds.min_x <= self.end_x <= bounds.max_x:
            raise ValueError('end_x must lie inside the canvas bounds')
        if not bounds.min_y <= self.line_y <= bounds.max_y:
            raise ValueError('line_y must lie inside the canvas bounds')
        if self.start_x == self.end_x:
            raise ValueError('start_x and end_x must be different')

        for name in (
            'line_r', 'line_g', 'line_b',
            'background_r', 'background_g', 'background_b',
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= 255
            ):
                raise ValueError(f'{name} must be an integer from 0 to 255')
        if (
            not isinstance(self.pen_width, int)
            or isinstance(self.pen_width, bool)
            or not 1 <= self.pen_width <= 255
        ):
            raise ValueError('pen_width must be an integer from 1 to 255')

        positive = (
            'control_rate_hz', 'linear_gain', 'angular_gain',
            'max_linear_speed', 'max_angular_speed',
            'position_tolerance', 'angle_tolerance',
            'service_timeout_sec', 'pose_timeout_sec',
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

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> 'PainterConfig':
        """Build configuration from declared ROS parameter values."""
        return cls(**{name: values[name] for name in cls.__dataclass_fields__})

    @classmethod
    def defaults(cls) -> Mapping[str, object]:
        """Return parameter names and their default values."""
        instance = cls()
        return {
            name: getattr(instance, name)
            for name in cls.__dataclass_fields__
        }

    @property
    def start(self) -> Point:
        """Return the requested line start point."""
        return Point(self.start_x, self.line_y)

    @property
    def end(self) -> Point:
        """Return the requested line end point."""
        return Point(self.end_x, self.line_y)


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
