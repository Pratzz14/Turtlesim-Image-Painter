#!/usr/bin/env python3
"""Process an image into a compact pixel-art matrix from the command line."""

import argparse
from pathlib import Path
from typing import Optional, Sequence

from turtlesim_image_painter import ImageProcessingError, ImageProcessor


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description='Convert a PNG or JPEG into a quantized pixel matrix.',
    )
    parser.add_argument('image', type=Path, help='path to a PNG or JPEG image')
    parser.add_argument('--width', type=int, default=64, help='maximum width')
    parser.add_argument('--height', type=int, default=64, help='maximum height')
    parser.add_argument(
        '--colors',
        type=int,
        choices=range(4, 9),
        default=8,
        metavar='4-8',
        help='palette size (default: 8)',
    )
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """Process the requested image and print its palette and pixel matrix."""
    options = build_parser().parse_args(arguments)

    try:
        result = ImageProcessor().process(
            options.image,
            max_width=options.width,
            max_height=options.height,
            palette_size=options.colors,
        )
    except (ImageProcessingError, TypeError, ValueError) as error:
        print(f'Error: {error}')
        return 1

    print(f'Size: {result.width}x{result.height}')
    print('Palette:')
    for index, color in enumerate(result.palette):
        print(f'  {index}: {color.as_tuple()}')
    if result.background is None:
        print('Background: none detected')
    else:
        print(f'Background: {result.background.as_tuple()}')
    print('Pixels (hex RGB):')
    for row in result.pixels:
        print(' '.join(
            f'{color.red:02x}{color.green:02x}{color.blue:02x}'
            for color in row
        ))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
