"""Turn raster images into compact painting plans for ROS 2 turtlesim."""

from .image_processing import ImageProcessingError, ImageProcessor
from .models import (
    Color,
    PaintingPlan,
    Point,
    ProcessedImage,
    Progress,
    Statistics,
    Stroke,
)

__all__ = [
    'Color',
    'ImageProcessingError',
    'ImageProcessor',
    'PaintingPlan',
    'Point',
    'ProcessedImage',
    'Progress',
    'Statistics',
    'Stroke',
]
