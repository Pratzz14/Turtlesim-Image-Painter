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

"""Raster image loading, resizing, quantization, and analysis."""

from collections import Counter
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

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
        # The painter treats every resized pixel as a discrete color cell.
        # Interpolating filters invent blended edge colors, which show up as
        # gray halos around otherwise sharp artwork after quantization.
        return image.resize(size, Image.Resampling.NEAREST)

    @staticmethod
    def quantize_image(
        image: Image.Image,
        palette_size: int,
        background: Optional[Color] = None,
        background_tolerance: int = 24,
    ) -> Image.Image:
        """Reduce an RGB image while reserving a detected background color."""
        if not isinstance(palette_size, int) or isinstance(palette_size, bool):
            raise TypeError('palette size must be an integer')
        if not 2 <= palette_size <= 8:
            raise ValueError('palette size must be between 2 and 8')
        if background is not None and not isinstance(background, Color):
            raise TypeError('background must be a Color or None')
        if (
            not isinstance(background_tolerance, int)
            or isinstance(background_tolerance, bool)
            or not 0 <= background_tolerance <= 255
        ):
            raise ValueError(
                'background tolerance must be an integer from 0 to 255')
        rgb_image = image.convert('RGB')
        if background is None:
            return rgb_image.quantize(
                colors=palette_size,
                method=Image.Quantize.MEDIANCUT,
                dither=Image.Dither.NONE,
            ).convert('RGB')

        background_value = background.as_tuple()
        mask = []
        foreground_pixels = []
        # Reserve the detected background instead of asking median-cut to spend
        # one of its limited palette entries rediscovering near-identical tones.
        for pixel in rgb_image.getdata():
            is_background = max(
                abs(channel - reference)
                for channel, reference in zip(pixel, background_value)
            ) <= background_tolerance
            mask.append(is_background)
            if not is_background:
                foreground_pixels.append(pixel)

        if not foreground_pixels:
            return Image.new('RGB', rgb_image.size, background_value)

        foreground = Image.new('RGB', (len(foreground_pixels), 1))
        foreground.putdata(foreground_pixels)
        reduced = foreground.quantize(
            colors=palette_size - 1,
            method=Image.Quantize.MEDIANCUT,
            dither=Image.Dither.NONE,
        ).convert('RGB')
        reduced_pixels = iter(reduced.getdata())
        output = Image.new('RGB', rgb_image.size)
        output.putdata([
            background_value if is_background else next(reduced_pixels)
            for is_background in mask
        ])
        return ImageProcessor._clean_antialiased_edges(
            output, background_value)

    @staticmethod
    def _clean_antialiased_edges(
        image: Image.Image,
        background: Tuple[int, int, int],
    ) -> Image.Image:
        """Merge edge-only palette colors into adjacent foreground colors."""
        pixels = list(image.convert('RGB').getdata())
        width, height = image.size
        colors = set(pixels)
        if len(colors) <= 2:
            return image.copy()

        def neighbors(index):
            x = index % width
            y = index // width
            for offset_y in (-1, 0, 1):
                for offset_x in (-1, 0, 1):
                    if offset_x == 0 and offset_y == 0:
                        continue
                    neighbor_x = x + offset_x
                    neighbor_y = y + offset_y
                    if 0 <= neighbor_x < width and 0 <= neighbor_y < height:
                        yield pixels[neighbor_y * width + neighbor_x]

        positions = {
            color: [
                index for index, pixel in enumerate(pixels)
                if pixel == color
            ]
            for color in colors
            if color != background
        }
        edge_colors = set()
        for color, indices in positions.items():
            background_edges = 0
            foreground_edges = 0
            interior_pixels = 0
            for index in indices:
                adjacent = tuple(neighbors(index))
                if background in adjacent:
                    background_edges += 1
                if any(
                    pixel != background and pixel != color
                    for pixel in adjacent
                ):
                    foreground_edges += 1
                if adjacent and all(pixel == color for pixel in adjacent):
                    interior_pixels += 1
            count = len(indices)
            if (
                background_edges / count >= 0.02
                and foreground_edges / count >= 0.75
                and interior_pixels / count <= 0.05
            ):
                edge_colors.add(color)

        if not edge_colors:
            return image.copy()

        cleaned = list(pixels)
        for index, color in enumerate(pixels):
            if color not in edge_colors:
                continue
            adjacent = Counter(
                pixel for pixel in neighbors(index)
                if pixel != background and pixel not in edge_colors
            )
            if not adjacent:
                cleaned[index] = background
                continue
            cleaned[index] = min(
                adjacent,
                key=lambda candidate: (
                    -adjacent[candidate],
                    sum(
                        (first - second) ** 2
                        for first, second in zip(color, candidate)
                    ),
                    candidate,
                ),
            )

        output = Image.new('RGB', image.size)
        output.putdata(cleaned)
        return output

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
        max_width: int = 80,
        max_height: int = 80,
        palette_size: int = 4,
        background_threshold: float = 0.5,
        allow_upscale: bool = False,
        background_tolerance: int = 24,
    ) -> ProcessedImage:
        """Run the complete file-to-pixel-matrix processing pipeline."""
        loaded = self.load_image(path)
        resized = self.resize_image(
            loaded, max_width, max_height, allow_upscale=allow_upscale)
        background = self.detect_dominant_background(
            resized, background_threshold)
        # Detect before quantization so the quantizer cannot invent a dominant
        # color and then have it mistaken for the source background.
        quantized = self.quantize_image(
            resized,
            palette_size,
            background=background,
            background_tolerance=background_tolerance,
        )
        return self.to_processed_image(quantized, background_threshold)

    def to_processed_image(
        self,
        quantized: Image.Image,
        background_threshold: float = 0.5,
    ) -> ProcessedImage:
        """Convert a quantized Pillow image into the immutable core model."""
        quantized = quantized.convert('RGB')
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
