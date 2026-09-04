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

"""Turn raster images into compact painting plans for ROS 2 turtlesim."""

from .image_processing import ImageProcessingError, ImageProcessor
from .models import (
    CanvasBounds,
    Color,
    PaintingPlan,
    PipelineResult,
    PlanResult,
    Point,
    ProcessedImage,
    Progress,
    Statistics,
    Stroke,
)
from .pipeline import PaintingPipeline
from .preview import PreviewGenerator
from .stroke_generation import StrokeGenerationError, StrokeGenerator

__all__ = [
    'CanvasBounds',
    'Color',
    'ImageProcessingError',
    'ImageProcessor',
    'PaintingPlan',
    'PaintingPipeline',
    'PipelineResult',
    'PlanResult',
    'Point',
    'ProcessedImage',
    'Progress',
    'PreviewGenerator',
    'Statistics',
    'Stroke',
    'StrokeGenerationError',
    'StrokeGenerator',
]
