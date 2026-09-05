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

"""Tests for the standalone image-processing pipeline."""

from pathlib import Path

from PIL import Image, ImageColor
import pytest

from turtlesim_image_painter import Color, ImageProcessingError, ImageProcessor


@pytest.fixture
def processor():
    """Create an image processor with a visible transparency color."""
    return ImageProcessor(transparency_color=Color(10, 20, 30))


@pytest.mark.parametrize('suffix,image_format', [('.png', 'PNG'), ('.jpg', 'JPEG')])
def test_loads_supported_images(tmp_path, processor, suffix, image_format):
    """PNG and JPEG inputs are loaded as owned RGB images."""
    path = tmp_path / ('input' + suffix)
    Image.new('RGB', (3, 2), 'red').save(path, format=image_format)

    loaded = processor.load_image(path)

    assert loaded.mode == 'RGB'
    assert loaded.size == (3, 2)
    assert loaded.getpixel((0, 0))[0] > 200


@pytest.mark.parametrize('name', ['missing.png', 'input.gif', 'broken.jpg'])
def test_rejects_missing_unsupported_and_corrupt_images(tmp_path, processor, name):
    """Invalid inputs produce one stable, public exception type."""
    path = tmp_path / name
    if name == 'input.gif':
        Image.new('RGB', (1, 1)).save(path, format='GIF')
    elif name == 'broken.jpg':
        path.write_bytes(b'not an image')

    with pytest.raises(ImageProcessingError):
        processor.load_image(path)


def test_oversized_image_uses_public_exception(
    tmp_path, processor, monkeypatch,
):
    """Pillow's decompression-bomb rejection is normalized for callers."""
    path = tmp_path / 'oversized.png'
    Image.new('RGB', (20, 20), 'white').save(path)
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 1)

    with pytest.raises(ImageProcessingError):
        processor.load_image(path)


def test_applies_exif_orientation(tmp_path, processor):
    """EXIF orientation is applied before an image is returned."""
    path = tmp_path / 'rotated.jpg'
    image = Image.new('RGB', (4, 2), 'red')
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)

    assert processor.load_image(path).size == (2, 4)


def test_rgb_conversion_preserves_rgb(processor):
    """Converting an RGB image does not alter its pixels."""
    image = Image.new('RGB', (1, 1), (1, 2, 3))
    assert processor.to_rgb(image).getpixel((0, 0)) == (1, 2, 3)


def test_transparency_is_composited(processor):
    """Fully transparent pixels use the configured solid background."""
    image = Image.new('RGBA', (2, 1), (200, 100, 50, 255))
    image.putpixel((1, 0), (255, 255, 255, 0))

    converted = processor.to_rgb(image)

    assert converted.getpixel((0, 0)) == (200, 100, 50)
    assert converted.getpixel((1, 0)) == (10, 20, 30)


@pytest.mark.parametrize(
    'source,bounds,expected',
    [
        ((200, 100), (50, 50), (50, 25)),
        ((100, 200), (50, 50), (25, 50)),
        ((100, 100), (40, 40), (40, 40)),
    ],
)
def test_resize_preserves_aspect_ratio(processor, source, bounds, expected):
    """Landscape, portrait, and square images fit within their bounds."""
    image = Image.new('RGB', source)
    assert processor.resize_image(image, *bounds).size == expected


def test_resize_does_not_upscale_by_default(processor):
    """Small sources retain their original dimensions unless requested."""
    image = Image.new('RGB', (10, 5))
    assert processor.resize_image(image, 100, 100).size == (10, 5)


def test_resize_does_not_invent_gray_pixels_around_sharp_edges(processor):
    """Nearest-neighbor resizing preserves a hard two-color boundary."""
    image = Image.new('RGB', (200, 200), 'white')
    for y in range(40, 160):
        for x in range(40, 160):
            image.putpixel((x, y), (0, 0, 0))

    resized = processor.resize_image(image, 20, 20)

    assert set(resized.getdata()) == {
        (0, 0, 0),
        (255, 255, 255),
    }


@pytest.mark.parametrize('palette_size', [2, 8])
def test_quantization_limits_palette(processor, palette_size):
    """Median-cut output never exceeds the requested palette size."""
    image = Image.new('RGB', (16, 16))
    for y in range(16):
        for x in range(16):
            image.putpixel((x, y), (x * 16, y * 16, (x + y) * 8))

    quantized = processor.quantize_image(image, palette_size)

    assert quantized.mode == 'RGB'
    assert len(set(quantized.getdata())) <= palette_size


def test_background_aware_quantization_reserves_and_cleans_background(
    processor,
):
    """Near-background noise does not consume foreground palette entries."""
    image = Image.new('RGB', (12, 1), (255, 255, 255))
    image.putdata([
        (255, 255, 255),
        (254, 254, 254),
        (249, 251, 252),
        (255, 255, 255),
        (32, 24, 21),
        (28, 20, 18),
        (2, 96, 147),
        (0, 91, 144),
        (255, 255, 255),
        (252, 252, 252),
        (32, 24, 21),
        (2, 96, 147),
    ])

    quantized = processor.quantize_image(
        image,
        4,
        background=Color(255, 255, 255),
        background_tolerance=24,
    )
    palette = set(quantized.getdata())

    assert (255, 255, 255) in palette
    assert len(palette) <= 4
    assert all(
        color == (255, 255, 255)
        or max(255 - channel for channel in color) > 24
        for color in palette
    )
    assert quantized.getpixel((1, 0)) == (255, 255, 255)
    assert quantized.getpixel((2, 0)) == (255, 255, 255)


def test_background_aware_quantization_handles_background_only(processor):
    """An all-background image remains a single exact color."""
    image = Image.new('RGB', (3, 2), (252, 253, 254))

    quantized = processor.quantize_image(
        image,
        2,
        background=Color(255, 255, 255),
        background_tolerance=24,
    )

    assert set(quantized.getdata()) == {(255, 255, 255)}


def test_quantization_merges_antialiased_borders_into_foreground(processor):
    """Edge-only neutral and tinted rings do not become painted colors."""
    image = Image.new('RGB', (19, 9), 'white')
    for y in range(1, 8):
        for x in range(1, 8):
            image.putpixel((x, y), (160, 160, 160))
        for x in range(11, 18):
            image.putpixel((x, y), (120, 170, 200))
    for y in range(2, 7):
        for x in range(2, 7):
            image.putpixel((x, y), (0, 0, 0))
        for x in range(12, 17):
            image.putpixel((x, y), (0, 90, 145))

    quantized = processor.quantize_image(
        image,
        5,
        background=Color(255, 255, 255),
        background_tolerance=0,
    )

    assert set(quantized.getdata()) == {
        (0, 0, 0),
        (0, 90, 145),
        (255, 255, 255),
    }


def test_quantization_preserves_isolated_gray_foreground(processor):
    """A gray detail without another foreground neighbor remains paintable."""
    image = Image.new('RGB', (5, 5), 'white')
    for x in range(1, 4):
        image.putpixel((x, 2), (128, 128, 128))

    quantized = processor.quantize_image(
        image,
        2,
        background=Color(255, 255, 255),
        background_tolerance=0,
    )

    assert set(quantized.getdata()) == {
        (128, 128, 128),
        (255, 255, 255),
    }


@pytest.mark.parametrize('tolerance', [-1, 256, 1.5, True])
def test_quantization_rejects_invalid_background_tolerance(
    processor, tolerance,
):
    """Background cleanup tolerance is a bounded integer."""
    with pytest.raises(ValueError):
        processor.quantize_image(
            Image.new('RGB', (1, 1)),
            4,
            background_tolerance=tolerance,
        )


@pytest.mark.parametrize('palette_size', [1, 9])
def test_quantization_rejects_palette_outside_supported_range(
    processor, palette_size,
):
    """The public quantizer enforces the supported 2-to-8-color range."""
    with pytest.raises(ValueError):
        processor.quantize_image(Image.new('RGB', (1, 1)), palette_size)


@pytest.mark.parametrize('palette_size', [True, 4.5])
def test_quantization_rejects_non_integer_palette_size(
    processor, palette_size,
):
    """Booleans and fractional palette sizes are not valid counts."""
    with pytest.raises(TypeError):
        processor.quantize_image(Image.new('RGB', (1, 1)), palette_size)


def test_detects_dominant_background(processor):
    """A color over the configured threshold is selected as background."""
    image = Image.new('RGB', (10, 10), 'white')
    for x in range(4):
        for y in range(4):
            image.putpixel((x, y), (0, 0, 0))

    assert processor.detect_dominant_background(image, 0.8) == Color(255, 255, 255)
    assert processor.detect_dominant_background(image, 0.9) is None


def test_end_to_end_produces_pixel_matrix(tmp_path, processor):
    """The public pipeline yields a bounded 4-color-compatible matrix."""
    path = Path(tmp_path) / 'landscape.png'
    image = Image.new('RGB', (40, 20))
    colors = ('red', 'green', 'blue', 'white', 'black', 'yellow')
    for x in range(image.width):
        for y in range(image.height):
            image.putpixel((x, y), ImageColor.getrgb(colors[x % len(colors)]))
    image.save(path)

    result = processor.process(path, max_width=12, max_height=12, palette_size=4)

    assert (result.width, result.height) == (12, 6)
    assert len(result.pixels) == 6
    assert all(len(row) == 12 for row in result.pixels)
    assert 1 <= len(result.palette) <= 4
