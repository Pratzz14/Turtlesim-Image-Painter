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
