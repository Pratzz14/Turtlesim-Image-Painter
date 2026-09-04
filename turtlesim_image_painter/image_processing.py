"""Raster image loading, resizing, quantization, and analysis."""

from collections import Counter
from pathlib import Path
from typing import Optional, Sequence, Union

from PIL import Image, ImageOps, UnidentifiedImageError

from .models import Color, PixelMatrix, ProcessedImage


class ImageProcessingError(ValueError):
    """Raised when an input cannot be safely processed as an image."""


class ImageProcessor:
    """Convert PNG and JPEG files into bounded-palette pixel matrices."""

    SUPPORTED_FORMATS = frozenset({'JPEG', 'PNG'})
    SUPPORTED_SUFFIXES = frozenset({'.jpeg', '.jpg', '.png'})

    def __init__(
        self,
        transparency_color: Union[Color, Sequence[int]] = Color(255, 255, 255),
    ) -> None:
        """Set the solid color used to composite transparent pixels."""
        if isinstance(transparency_color, Color):
            self.transparency_color = transparency_color
        else:
            values = tuple(transparency_color)
            if len(values) != 3:
                raise ValueError('transparency color must have three channels')
            self.transparency_color = Color(*values)

    def load_image(self, path: Union[str, Path]) -> Image.Image:
        """Validate, orient, and return an owned RGB PNG or JPEG image."""
        image_path = Path(path)
        if image_path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise ImageProcessingError('only PNG and JPEG images are supported')
        if not image_path.is_file():
            raise ImageProcessingError(f'image does not exist: {image_path}')

        try:
            with Image.open(image_path) as source:
                source.verify()
            with Image.open(image_path) as source:
                if source.format not in self.SUPPORTED_FORMATS:
                    raise ImageProcessingError(
                        'file contents are not a supported PNG or JPEG image')
                oriented = ImageOps.exif_transpose(source)
                return self.to_rgb(oriented)
        except ImageProcessingError:
            raise
        except (
            Image.DecompressionBombError,
            OSError,
            UnidentifiedImageError,
        ) as error:
            raise ImageProcessingError(f'invalid or corrupt image: {image_path}') from error

    def to_rgb(self, image: Image.Image) -> Image.Image:
        """Convert an image to RGB, compositing alpha onto a solid color."""
        if image.mode == 'RGB':
            return image.copy()
        if 'A' in image.getbands() or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            base = Image.new('RGBA', rgba.size, self.transparency_color.as_tuple() + (255,))
            return Image.alpha_composite(base, rgba).convert('RGB')
        return image.convert('RGB')

    @staticmethod
    def resize_image(
        image: Image.Image,
        max_width: int,
        max_height: int,
        allow_upscale: bool = False,
    ) -> Image.Image:
        """Fit an image inside a bounding box while preserving aspect ratio."""
        if max_width <= 0 or max_height <= 0:
            raise ValueError('maximum dimensions must be positive')
        scale = min(max_width / image.width, max_height / image.height)
        if not allow_upscale:
            scale = min(scale, 1.0)
        size = (
            max(1, min(max_width, round(image.width * scale))),
            max(1, min(max_height, round(image.height * scale))),
        )
        if size == image.size:
            return image.copy()
        return image.resize(size, Image.Resampling.LANCZOS)

    @staticmethod
    def quantize_image(image: Image.Image, palette_size: int) -> Image.Image:
        """Reduce an RGB image using Pillow's median-cut quantizer."""
        if not isinstance(palette_size, int) or isinstance(palette_size, bool):
            raise TypeError('palette size must be an integer')
        if not 4 <= palette_size <= 8:
            raise ValueError('palette size must be between 4 and 8')
        rgb_image = image.convert('RGB')
        return rgb_image.quantize(
            colors=palette_size,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        ).convert('RGB')

    @staticmethod
    def detect_dominant_background(
        image: Image.Image,
        threshold: float = 0.5,
    ) -> Optional[Color]:
        """Return the most common color when it occupies enough pixels."""
        if not 0.0 <= threshold <= 1.0:
            raise ValueError('background threshold must be between zero and one')
        pixels = list(image.convert('RGB').getdata())
        if not pixels:
            return None
        value, count = Counter(pixels).most_common(1)[0]
        if count / len(pixels) < threshold:
            return None
        return Color.from_tuple(value)

    def process(
        self,
        path: Union[str, Path],
        max_width: int = 64,
        max_height: int = 64,
        palette_size: int = 8,
        background_threshold: float = 0.5,
        allow_upscale: bool = False,
    ) -> ProcessedImage:
        """Run the complete file-to-pixel-matrix processing pipeline."""
        loaded = self.load_image(path)
        resized = self.resize_image(
            loaded, max_width, max_height, allow_upscale=allow_upscale)
        quantized = self.quantize_image(resized, palette_size)
        raw_pixels = list(quantized.getdata())
        colors = tuple(Color.from_tuple(value) for value in raw_pixels)
        rows: PixelMatrix = tuple(
            tuple(colors[offset:offset + quantized.width])
            for offset in range(0, len(colors), quantized.width)
        )
        palette = tuple(sorted(set(colors)))
        background = self.detect_dominant_background(
            quantized, background_threshold)
        return ProcessedImage(
            width=quantized.width,
            height=quantized.height,
            pixels=rows,
            palette=palette,
            background=background,
        )

    process_image = process
