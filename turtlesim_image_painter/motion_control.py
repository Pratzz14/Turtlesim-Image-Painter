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

"""
ROS-independent geometry and proportional motion-control helpers.

The functions return plain Python data rather than ``geometry_msgs/Twist``.
That boundary is intentional: controller math can be learned and tested
without starting a ROS graph, while ``PainterNode`` owns message conversion.
"""

from dataclasses import dataclass
from math import atan2, hypot, pi

from .models import Point


@dataclass(frozen=True)
class VelocityCommand:
    """A planar velocity command independent of ROS message types."""

    linear: float = 0.0
    angular: float = 0.0


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
