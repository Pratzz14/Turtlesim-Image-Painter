"""Tests for pure turtlesim feedback-control behavior."""

from math import pi

import pytest

from turtlesim_image_painter.models import Point
from turtlesim_image_painter.turtle_control import (
    PainterConfig,
    alignment_command,
    angle_arrived,
    distance_between,
    drive_command,
    heading_between,
    normalize_angle,
    position_arrived,
)


def test_default_configuration_describes_horizontal_red_line():
    """The shipped demo is a bounded red-on-white horizontal line."""
    config = PainterConfig()

    assert config.start == Point(2.0, 5.5)
    assert config.end == Point(9.0, 5.5)
    assert (config.line_r, config.line_g, config.line_b) == (255, 0, 0)
    assert (
        config.background_r,
        config.background_g,
        config.background_b,
    ) == (255, 255, 255)


@pytest.mark.parametrize(
    'changes,message',
    [
        ({'start_x': 0.5}, 'start_x'),
        ({'end_x': 10.5}, 'end_x'),
        ({'line_y': float('nan')}, 'line_y'),
        ({'start_x': 4.0, 'end_x': 4.0}, 'different'),
        ({'line_r': 256}, 'line_r'),
        ({'background_b': -1}, 'background_b'),
        ({'pen_width': 0}, 'pen_width'),
        ({'canvas_min_x': 5.0, 'canvas_max_x': 5.0}, 'minimums'),
        ({'control_rate_hz': 0.0}, 'control_rate_hz'),
        ({'linear_gain': float('inf')}, 'linear_gain'),
        ({'max_angular_speed': -1.0}, 'max_angular_speed'),
        ({'angle_tolerance': pi + 0.1}, 'angle_tolerance'),
        ({'service_timeout_sec': 0.0}, 'service_timeout_sec'),
        ({'pose_timeout_sec': False}, 'pose_timeout_sec'),
    ],
)
def test_configuration_rejects_invalid_parameters(changes, message):
    """Unsafe geometry, appearance, and controller values fail early."""
    values = dict(PainterConfig.defaults())
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        PainterConfig.from_mapping(values)


def test_heading_and_distance_support_both_horizontal_directions():
    """Line geometry reports distance and the correct signed direction."""
    left = Point(2.0, 5.5)
    right = Point(9.0, 5.5)

    assert distance_between(left, right) == pytest.approx(7.0)
    assert heading_between(left, right) == pytest.approx(0.0)
    assert abs(heading_between(right, left)) == pytest.approx(pi)


@pytest.mark.parametrize(
    'angle,expected',
    [(0.0, 0.0), (2.0 * pi, 0.0), (3.0 * pi, -pi), (-3.0 * pi, -pi)],
)
def test_angle_normalization_wraps_across_pi(angle, expected):
    """Heading errors consistently use the shortest rotation."""
    assert normalize_angle(angle) == pytest.approx(expected)


def test_arrival_checks_include_the_tolerance_boundary():
    """Exact tolerance boundaries count as arrived."""
    assert position_arrived(Point(0.0, 0.0), Point(0.03, 0.04), 0.05)
    assert not position_arrived(Point(0.0, 0.0), Point(0.06, 0.0), 0.05)
    assert angle_arrived(pi - 0.01, -pi + 0.01, 0.02)
    assert not angle_arrived(0.0, 0.03, 0.02)


def test_alignment_velocity_is_signed_and_clamped():
    """Large angular errors never exceed the configured limit."""
    positive = alignment_command(0.0, pi / 2.0, 10.0, 2.0)
    negative = alignment_command(0.0, -pi / 2.0, 10.0, 2.0)

    assert positive.linear == 0.0
    assert positive.angular == 2.0
    assert negative.angular == -2.0


def test_drive_velocity_clamps_linear_and_angular_components():
    """Feedback gains cannot command velocities above safe maxima."""
    command = drive_command(
        Point(0.0, 0.0),
        -pi / 2.0,
        Point(10.0, 0.0),
        linear_gain=4.0,
        angular_gain=10.0,
        max_linear=1.5,
        max_angular=3.0,
    )

    assert command.linear == 1.5
    assert command.angular == 3.0
