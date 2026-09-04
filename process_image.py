#!/usr/bin/env python3
"""Process an image into a compact pixel-art matrix from the command line."""

import argparse
from pathlib import Path
from typing import Optional, Sequence

from turtlesim_image_painter import ImageProcessingError, PaintingPipeline


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
    parser.add_argument(
        '--color-order',
        choices=('largest_first',),
        default='largest_first',
        help='color-group ordering strategy (default: largest_first)',
    )
    parser.add_argument(
        '--path-order',
        choices=('raster', 'snake'),
        default='raster',
        help='stroke ordering within each color (default: raster)',
    )
    parser.add_argument(
        '--plan-output',
        type=Path,
        help='plan JSON path (default: <image_stem>_plan.json)',
    )
    parser.add_argument(
        '--preview-output',
        type=Path,
        help='preview PNG path (default: <image_stem>_preview.png)',
    )
    return parser


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """Process the requested image and print its palette and pixel matrix."""
    options = build_parser().parse_args(arguments)

    try:
        pipeline_result = PaintingPipeline().run(
            options.image,
            max_width=options.width,
            max_height=options.height,
            palette_size=options.colors,
            color_order=options.color_order,
            path_order=options.path_order,
            plan_output=options.plan_output,
            preview_output=options.preview_output,
        )
    except (ImageProcessingError, OSError, TypeError, ValueError) as error:
        print(f'Error: {error}')
        return 1

    result = pipeline_result.processed_image
    statistics = pipeline_result.plan_result.statistics

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
    print(f'Strokes: {statistics.stroke_count}')
    print(f'Paint distance: {statistics.paint_distance:.3f}')
    print(f'Travel distance: {statistics.travel_distance:.3f}')
    print(f'Total distance: {statistics.total_distance:.3f}')
    print(f'Plan JSON: {pipeline_result.plan_path}')
    print(f'Preview PNG: {pipeline_result.preview_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
