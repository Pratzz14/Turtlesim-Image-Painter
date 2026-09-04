"""Turn raster images into compact painting plans for ROS 2 turtlesim."""

from .image_processing import ImageProcessingError, ImageProcessor
from .models import (
    CanvasBounds,
    Color,
    PaintingPlan,
    PlanResult,
    Point,
    ProcessedImage,
    Progress,
    Statistics,
    Stroke,
)
from .stroke_generation import StrokeGenerationError, StrokeGenerator

__all__ = [
    'CanvasBounds',
    'Color',
    'ImageProcessingError',
    'ImageProcessor',
    'PaintingPlan',
    'PlanResult',
    'Point',
    'ProcessedImage',
    'Progress',
    'Statistics',
    'Stroke',
    'StrokeGenerationError',
    'StrokeGenerator',
]
