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

"""Tests for the installed ROS 2 launch interface."""

import importlib.util
from pathlib import Path

from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch_ros.actions import Node
import pytest


LAUNCH_PATH = Path(__file__).parents[1] / 'launch' / 'painter.launch.py'


def load_launch_module():
    """Load the Python launch file as a normal test module."""
    specification = importlib.util.spec_from_file_location(
        'painter_launch', LAUNCH_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_launch_argument_mapping_preserves_yaml_defaults():
    """Omitted convenience arguments do not replace YAML parameters."""
    module = load_launch_module()

    assert module._painter_parameter_overrides('/tmp/image.png') == {
        'image_path': '/tmp/image.png',
    }


def test_launch_argument_mapping_applies_colors_and_square_resolution():
    """Convenience arguments map to their exact painter parameters."""
    module = load_launch_module()

    assert module._painter_parameter_overrides(
        '/tmp/image.png', '6', '48') == {
            'image_path': '/tmp/image.png',
            'palette_size': 6,
            'max_width': 48,
            'max_height': 48,
        }


@pytest.mark.parametrize(
    'colors,resolution,message',
    [
        ('1', '', 'colors'),
        ('9', '', 'colors'),
        ('red', '', 'colors'),
        ('', '0', 'resolution'),
        ('', 'large', 'resolution'),
    ],
)
def test_launch_argument_mapping_rejects_invalid_values(
    colors, resolution, message,
):
    """Invalid launch values fail before the painter process starts."""
    module = load_launch_module()

    with pytest.raises(ValueError, match=message):
        module._painter_parameter_overrides(
            '/tmp/image.png', colors, resolution)


def test_launch_description_exposes_arguments_and_both_nodes(
    tmp_path, monkeypatch,
):
    """The public description contains required arguments and both nodes."""
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path / 'ros-logs'))
    module = load_launch_module()
    monkeypatch.setattr(
        module,
        'get_package_share_directory',
        lambda package_name: str(LAUNCH_PATH.parents[1]),
    )
    actions = module.generate_launch_description().entities
    declarations = {
        action.name: action
        for action in actions
        if isinstance(action, DeclareLaunchArgument)
    }
    nodes = [action for action in actions if isinstance(action, Node)]

    assert set(declarations) == {'image', 'colors', 'resolution'}
    assert declarations['image'].default_value is None
    assert declarations['colors'].default_value is not None
    assert declarations['resolution'].default_value is not None
    assert [(node.node_package, node.node_executable) for node in nodes] == [
        ('turtlesim', 'turtlesim_node'),
    ]
    assert any(isinstance(action, OpaqueFunction) for action in actions)

    context = LaunchContext()
    context.launch_configurations.update({
        'image': '/tmp/image.png',
        'colors': '6',
        'resolution': '48',
    })
    painter_nodes = module._launch_painter(context)
    assert [(node.node_package, node.node_executable)
            for node in painter_nodes] == [
        ('turtlesim_image_painter', 'painter'),
    ]
