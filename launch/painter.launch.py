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

"""Launch turtlesim and paint one image with the configured painter node."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


PACKAGE_NAME = 'turtlesim_image_painter'


def _optional_integer(value, name, minimum=1, maximum=None):
    """Parse an optional bounded launch argument as an integer."""
    if value == '':
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f'{name} must be an integer') from error
    if parsed < minimum or maximum is not None and parsed > maximum:
        if maximum is None:
            expected = f'at least {minimum}'
        else:
            expected = f'from {minimum} to {maximum}'
        raise ValueError(f'{name} must be {expected}')
    return parsed


def _painter_parameter_overrides(image, colors='', resolution=''):
    """Map the public launch arguments onto painter ROS parameters."""
    if not image.strip():
        raise ValueError('image must not be empty')
    parameters = {'image_path': image}
    palette_size = _optional_integer(colors, 'colors', 2, 8)
    maximum_size = _optional_integer(resolution, 'resolution')
    if palette_size is not None:
        parameters['palette_size'] = palette_size
    if maximum_size is not None:
        parameters['max_width'] = maximum_size
        parameters['max_height'] = maximum_size
    return parameters


def _launch_painter(context):
    """Create the painter after resolving and validating launch arguments."""
    parameters = _painter_parameter_overrides(
        LaunchConfiguration('image').perform(context),
        LaunchConfiguration('colors').perform(context),
        LaunchConfiguration('resolution').perform(context),
    )
    configuration = Path(
        get_package_share_directory(PACKAGE_NAME),
        'config',
        'default.yaml',
    )
    return [Node(
        package=PACKAGE_NAME,
        executable='painter',
        name='painter',
        output='screen',
        parameters=[str(configuration), parameters],
    )]


def generate_launch_description():
    """Return the complete one-command image painter launch description."""
    return LaunchDescription([
        DeclareLaunchArgument(
            'image',
            description='Required absolute path to a PNG or JPEG image.',
        ),
        DeclareLaunchArgument(
            'colors',
            default_value='',
            description=(
                'Optional palette size from 2 to 8; YAML default if omitted.'),
        ),
        DeclareLaunchArgument(
            'resolution',
            default_value='',
            description=(
                'Optional positive square maximum; YAML defaults if omitted.'),
        ),
        Node(
            package='turtlesim',
            executable='turtlesim_node',
            name='turtlesim',
            output='screen',
        ),
        OpaqueFunction(function=_launch_painter),
    ])
