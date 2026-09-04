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
Compatibility imports for the former combined control module.

New code should import parameter rules from :mod:`configuration` and movement
math from :mod:`motion_control`. Re-exporting the old names keeps existing
lessons and user code working while the source tree demonstrates one concern
per module.
"""

from .configuration import PainterConfig
from .motion_control import (
    alignment_command,
    angle_arrived,
    clamp_signed,
    distance_between,
    drive_command,
    heading_between,
    normalize_angle,
    position_arrived,
    VelocityCommand,
)

__all__ = [
    'alignment_command',
    'angle_arrived',
    'clamp_signed',
    'distance_between',
    'drive_command',
    'heading_between',
    'normalize_angle',
    'PainterConfig',
    'position_arrived',
    'VelocityCommand',
]
