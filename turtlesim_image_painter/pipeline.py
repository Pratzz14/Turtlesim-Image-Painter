"""Orchestrate image processing, planning, and artifact generation."""

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional, Union

from .image_processing import ImageProcessor
from .models import CanvasBounds, Color, PipelineResult, PlanResult
from .preview import PreviewGenerator
from .stroke_generation import StrokeGenerator


def _color_value(color: Optional[Color]):
    """Return a JSON-compatible RGB value."""
    return list(color.as_tuple()) if color is not None else None


def _plan_document(
    result: PlanResult,
    color_order: str,
    path_order: str,
) -> dict:
    """Build the stable JSON representation of a painting plan."""
    plan = result.plan
    statistics = result.statistics
    return {
        'format_version': 1,
        'image': {
            'width': plan.width,
            'height': plan.height,
            'background': _color_value(plan.background),
        },
        'strategies': {
            'color_order': color_order,
            'path_order': path_order,
        },
        'statistics': {
            'pixel_count': statistics.pixel_count,
            'palette_size': statistics.palette_size,
            'stroke_count': statistics.stroke_count,
            'skipped_pixels': statistics.skipped_pixels,
            'color_counts': [
                {'color': _color_value(color), 'pixels': count}
                for color, count in statistics.color_counts
            ],
            'paint_distance': statistics.paint_distance,
            'travel_distance': statistics.travel_distance,
            'total_distance': statistics.total_distance,
        },
        'strokes': [
            {
                'start': {'x': stroke.start.x, 'y': stroke.start.y},
                'end': {'x': stroke.end.x, 'y': stroke.end.y},
                'color': _color_value(stroke.color),
            }
            for stroke in plan.strokes
        ],
    }


class PaintingPipeline:
    """Run the complete image-to-plan workflow and write its artifacts."""

    def __init__(
        self,
        processor: Optional[ImageProcessor] = None,
        bounds: CanvasBounds = CanvasBounds(),
        exclude_background: bool = True,
    ) -> None:
        """Configure image conversion and canvas planning behavior."""
        self.processor = processor or ImageProcessor()
        self.bounds = bounds
        self.exclude_background = exclude_background
        self.preview_generator = PreviewGenerator()

    @staticmethod
    def _paths_alias(first: Path, second: Path) -> bool:
        """Return whether two paths identify the same filesystem object."""
        try:
            return first.samefile(second)
        except FileNotFoundError:
            return first.resolve() == second.resolve()

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        """Reserve a destination-local path suitable for atomic replacement."""
        with NamedTemporaryFile(
            dir=destination.parent,
            prefix='.' + destination.stem + '-',
            suffix=destination.suffix,
            delete=False,
        ) as temporary:
            return Path(temporary.name)

    def run(
        self,
        image_path: Union[str, Path],
        max_width: int = 64,
        max_height: int = 64,
        palette_size: int = 8,
        background_threshold: float = 0.5,
        allow_upscale: bool = False,
        color_order: str = 'largest_first',
        path_order: str = 'raster',
        plan_output: Optional[Union[str, Path]] = None,
        preview_output: Optional[Union[str, Path]] = None,
    ) -> PipelineResult:
        """Process an image, order its strokes, and write JSON and PNG."""
        source_path = Path(image_path)
        plan_path = Path(plan_output) if plan_output else source_path.with_name(
            source_path.stem + '_plan.json')
        preview_path = (
            Path(preview_output) if preview_output else source_path.with_name(
                source_path.stem + '_preview.png')
        )
        if plan_path.suffix.lower() != '.json':
            raise ValueError('plan output must use a .json suffix')
        if preview_path.suffix.lower() != '.png':
            raise ValueError('preview output must use a .png suffix')
        if self._paths_alias(source_path, plan_path) or self._paths_alias(
            source_path, preview_path,
        ):
            raise ValueError('artifact output must not overwrite the source image')
        if self._paths_alias(plan_path, preview_path):
            raise ValueError('plan and preview outputs must be different files')

        original = self.processor.load_image(source_path)
        resized = self.processor.resize_image(
            original,
            max_width,
            max_height,
            allow_upscale=allow_upscale,
        )
        quantized = self.processor.quantize_image(resized, palette_size)
        processed = self.processor.to_processed_image(
            quantized, background_threshold)
        generator = StrokeGenerator(
            bounds=self.bounds,
            exclude_background=self.exclude_background,
            color_order=color_order,
            path_order=path_order,
        )
        result = generator.generate(processed)

        plan_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_plan = self._temporary_path(plan_path)
        try:
            temporary_preview = self._temporary_path(preview_path)
            try:
                temporary_plan.write_text(
                    json.dumps(
                        _plan_document(result, color_order, path_order),
                        indent=2,
                    ) + '\n',
                    encoding='utf-8',
                )
                self.preview_generator.generate(
                    original,
                    resized,
                    quantized,
                    processed,
                    result,
                    temporary_preview,
                    color_order,
                    path_order,
                )
                os.replace(temporary_plan, plan_path)
                os.replace(temporary_preview, preview_path)
            finally:
                temporary_preview.unlink(missing_ok=True)
        finally:
            temporary_plan.unlink(missing_ok=True)
        return PipelineResult(
            processed_image=processed,
            plan_result=result,
            plan_path=str(plan_path),
            preview_path=str(preview_path),
        )
