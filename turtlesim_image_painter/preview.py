"""Create an inspectable composite preview for a painting plan."""

from pathlib import Path
from typing import Union

from PIL import Image, ImageDraw, ImageFont

from .models import PlanResult, ProcessedImage


class PreviewGenerator:
    """Render image stages, palette, and plan statistics into one PNG."""

    WIDTH = 1100
    HEIGHT = 700
    PANEL_SIZE = (300, 300)

    @staticmethod
    def _fit(image: Image.Image, resampling: int) -> Image.Image:
        """Fit an image into a preview panel while preserving aspect ratio."""
        panel_width, panel_height = PreviewGenerator.PANEL_SIZE
        scale = min(panel_width / image.width, panel_height / image.height)
        size = (
            max(1, round(image.width * scale)),
            max(1, round(image.height * scale)),
        )
        return image.resize(size, resampling)

    @staticmethod
    def _draw_panel(
        canvas: Image.Image,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        x: int,
        label: str,
        resampling: int,
    ) -> None:
        """Draw one labeled and centered image panel."""
        panel_y = 70
        panel_width, panel_height = PreviewGenerator.PANEL_SIZE
        draw.text((x, 35), label, fill='black')
        draw.rectangle(
            (x, panel_y, x + panel_width, panel_y + panel_height),
            fill=(238, 238, 238),
            outline=(120, 120, 120),
        )
        fitted = PreviewGenerator._fit(image, resampling)
        position = (
            x + (panel_width - fitted.width) // 2,
            panel_y + (panel_height - fitted.height) // 2,
        )
        canvas.paste(fitted, position)

    def generate(
        self,
        original: Image.Image,
        resized: Image.Image,
        quantized: Image.Image,
        processed: ProcessedImage,
        result: PlanResult,
        output_path: Union[str, Path],
        color_order: str,
        path_order: str,
    ) -> Path:
        """Write a deterministic composite preview and return its path."""
        path = Path(output_path)
        if path.suffix.lower() != '.png':
            raise ValueError('preview output must use a .png suffix')
        path.parent.mkdir(parents=True, exist_ok=True)

        canvas = Image.new('RGB', (self.WIDTH, self.HEIGHT), 'white')
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        draw.text((40, 10), 'Turtlesim Painting Preview', fill='black', font=font)
        self._draw_panel(
            canvas, draw, original, 40, 'Original thumbnail',
            Image.Resampling.LANCZOS,
        )
        self._draw_panel(
            canvas, draw, resized, 400, 'Resized image',
            Image.Resampling.NEAREST,
        )
        self._draw_panel(
            canvas, draw, quantized, 760, 'Quantized image',
            Image.Resampling.NEAREST,
        )

        draw.text((40, 395), 'Palette', fill='black', font=font)
        swatch_x = 40
        swatch_y = 420
        for color in processed.palette:
            draw.rectangle(
                (swatch_x, swatch_y, swatch_x + 55, swatch_y + 40),
                fill=color.as_tuple(),
                outline='black',
            )
            draw.text(
                (swatch_x, swatch_y + 47),
                '#{:02X}{:02X}{:02X}'.format(*color.as_tuple()),
                fill='black',
                font=font,
            )
            swatch_x += 125

        details_y = 500
        if processed.background is None:
            background_text = 'Background: none detected'
        else:
            background = processed.background
            draw.rectangle(
                (40, details_y, 75, details_y + 25),
                fill=background.as_tuple(),
                outline='black',
            )
            background_text = 'Background: RGB{}'.format(
                background.as_tuple())
        draw.text((85, details_y + 7), background_text, fill='black', font=font)

        statistics = result.statistics
        lines = (
            'Resolution: original {}x{}; processed {}x{}'.format(
                original.width, original.height,
                processed.width, processed.height,
            ),
            'Strategies: color={}; path={}'.format(color_order, path_order),
            'Strokes: {}; skipped pixels: {}'.format(
                statistics.stroke_count, statistics.skipped_pixels),
            'Distance: paint={:.3f}; travel={:.3f}; total={:.3f}'.format(
                statistics.paint_distance,
                statistics.travel_distance,
                statistics.total_distance,
            ),
        )
        for index, line in enumerate(lines):
            draw.text(
                (40, 545 + index * 28), line, fill='black', font=font)

        canvas.save(path, format='PNG')
        return path
