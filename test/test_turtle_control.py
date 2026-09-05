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

"""Tests for pure turtlesim feedback-control behavior."""

from math import pi
from pathlib import Path

import pytest

from turtlesim_image_painter.configuration import (
    PainterConfig,
    recommended_pen_width,
)
from turtlesim_image_painter.models import CanvasBounds
from turtlesim_image_painter.models import Point
from turtlesim_image_painter.motion_control import (
    alignment_command,
    angle_arrived,
    distance_between,
    drive_command,
    heading_between,
    normalize_angle,
    position_arrived,
)
import yaml


def test_default_configuration_describes_image_painter():
    """Defaults describe image planning and bounded turtle execution."""
    config = PainterConfig()

    assert config.image_path == ''
    assert (config.max_width, config.max_height) == (80, 80)
    assert config.palette_size == 4
    assert config.background_tolerance == 24
    assert config.stroke_orientation == 'auto'
    assert config.bounds.min_x == 1.0
    assert (config.parking_x, config.parking_y) == (0.5, 0.5)
    assert config.pen_width == 6
    assert config.auto_pen_width
    assert (
        config.linear_gain,
        config.angular_gain,
        config.max_linear_speed,
        config.max_angular_speed,
    ) == (3.0, 12.0, 4.0, 8.0)
    assert (
        config.background_r,
        config.background_g,
        config.background_b,
    ) == (255, 255, 255)
    assert not config.dry_run


def test_yaml_defaults_match_validated_configuration():
    """Installed-style YAML defaults stay aligned with the Python contract."""
    config_path = Path(__file__).parents[1] / 'config' / 'default.yaml'
    document = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    yaml_defaults = document['painter']['ros__parameters']
    expected = dict(PainterConfig.defaults())
    expected['transparency_color'] = list(expected['transparency_color'])

    assert yaml_defaults == expected


@pytest.mark.parametrize(
    'changes,message',
    [
        ({'max_width': 0}, 'max_width'),
        ({'palette_size': 1}, 'palette_size'),
        ({'palette_size': 9}, 'palette_size'),
        ({'transparency_color': (0, 0)}, 'three channels'),
        ({'background_threshold': 1.1}, 'background_threshold'),
        ({'background_tolerance': -1}, 'background_tolerance'),
        ({'background_tolerance': 256}, 'background_tolerance'),
        ({'path_order': 'diagonal'}, 'path_order'),
        ({'stroke_orientation': 'diagonal'}, 'stroke_orientation'),
        ({'background_b': -1}, 'background_b'),
        ({'pen_width': 0}, 'pen_width'),
        ({'auto_pen_width': 1}, 'auto_pen_width'),
        ({'canvas_min_x': 5.0, 'canvas_max_x': 5.0}, 'minimums'),
        ({'control_rate_hz': 0.0}, 'control_rate_hz'),
        ({'linear_gain': float('inf')}, 'linear_gain'),
        ({'max_angular_speed': -1.0}, 'max_angular_speed'),
        ({'parking_x': 0.0}, 'parking_x'),
        ({'parking_y': float('nan')}, 'parking_y'),
        ({'angle_tolerance': pi + 0.1}, 'angle_tolerance'),
        ({'service_timeout_sec': 0.0}, 'service_timeout_sec'),
        ({'pose_timeout_sec': False}, 'pose_timeout_sec'),
        ({'movement_timeout_sec': 0.0}, 'movement_timeout_sec'),
        ({'color_change_pause_sec': -1.0}, 'color_change_pause_sec'),
        ({'dry_run': 1}, 'dry_run'),
    ],
)
def test_configuration_rejects_invalid_parameters(changes, message):
    """Unsafe geometry, appearance, and controller values fail early."""
    values = dict(PainterConfig.defaults())
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        PainterConfig.from_mapping(values)


@pytest.mark.parametrize(
    'width,height,expected',
    [
        (80, 80, 6),
        (249, 148, 2),
        (1000, 1000, 1),
        (1, 1, 255),
    ],
)
def test_recommended_pen_width_tracks_logical_cell_size(
    width, height, expected,
):
    """Automatic brushes stay near one logical cell at every resolution."""
    assert recommended_pen_width(
        CanvasBounds(), width, height) == expected


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
