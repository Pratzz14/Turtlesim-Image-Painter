# 4. Image Processing and Stroke Planning

## Learning goals

This chapter explains the ROS-independent half of the repository and the
geometry used to map image pixels onto the turtlesim canvas.

## Why this layer has no ROS imports

Image conversion is a domain problem, not a communication problem. Keeping it
independent means it can be:

- run through the `process_image` CLI;
- unit tested without initializing `rclpy`;
- reused with a different simulator or physical robot;
- executed on a worker without calling ROS APIs from that thread.

The key files are `models.py`, `image_processing.py`,
`stroke_generation.py`, `pipeline.py`, and `preview.py`.

## Loading and normalizing an image

`ImageProcessor.load_image()` performs several checks:

1. The suffix must be PNG or JPEG.
2. The path must identify a file.
3. Pillow verifies that the encoded contents are valid.
4. The decoded format must also be PNG or JPEG.
5. EXIF orientation is applied.
6. The result is converted into an owned RGB image.

If alpha is present, the image is composited on `transparency_color`. A turtle
pen cannot paint transparency, so the ambiguity is resolved before planning.

## Resizing

For source size `(source_width, source_height)` and configured bounds
`(max_width, max_height)`:

```text
scale = min(max_width / source_width, max_height / source_height)
```

The same scale is used on both axes, preserving aspect ratio. Upscaling is off
by default because adding logical pixels makes painting slower without adding
source detail.

## Background detection and quantization

The most common exact RGB value is accepted as background when:

```text
count(most_common_color) / total_pixels >= background_threshold
```

When a background exists, every source pixel within
`background_tolerance` on all RGB channels is considered background. That
exact color is reserved, and median-cut quantization uses the remaining
palette entries for the foreground.

This avoids spending several palette entries on nearly identical whites or
transparent-edge colors. Dithering is disabled because alternating dithered
pixels would create many tiny strokes.

## From Pillow image to immutable model

`to_processed_image()` converts each RGB tuple to `Color`, groups the flat
Pillow data into rows, creates a deterministic sorted palette, and constructs
`ProcessedImage`.

The model validates that its dimensions, pixels, palette, and optional
background agree. Downstream code can therefore operate without repeating
shape checks.

## Fitting the image onto the canvas

For canvas bounds and a logical image of `W` by `H`:

```text
canvas_width  = max_x - min_x
canvas_height = max_y - min_y
cell_scale    = min(canvas_width / W, canvas_height / H)
```

The painted width and height are `W * cell_scale` and `H * cell_scale`. The
remaining space is divided equally on both sides, centering the image.

Image rows increase downward, but turtlesim Y increases upward. For a
horizontal stroke on `row_index`:

```text
y = bottom + (H - row_index - 0.5) * cell_scale
```

The `0.5` puts the pen on the center line of the logical cells. Stroke X
coordinates use cell boundaries, so a one-pixel run still has nonzero length.

## Run-length compression

The generator merges adjacent same-color pixels on each row or column.

```text
R R R B B R
```

becomes:

```text
RRR | BB | R
```

This reduces service calls, teleports, and alignment operations. Horizontal
and vertical candidates are both constructed.

## Ordering strategies

Foreground colors are ordered by descending pixel count. RGB ordering breaks
ties, making output deterministic.

Within a color layer:

- `raster` processes each row or column in increasing order.
- `snake` reverses odd lines and their stroke directions.

For `stroke_orientation=auto`, each color first chooses the orientation with
the smaller stroke count. Tied orientations are combined and compared by
inter-stroke travel distance. A final exact tie prefers horizontal strokes.

## Background exclusion

If `exclude_background` is enabled and a background was detected, its runs are
not emitted. The same RGB is sent to turtlesim as its canvas background before
`/clear` is called.

If no dominant background exists, every palette color is painted and the
configured fallback canvas RGB is used. If every pixel is excluded, the plan
contains no strokes but is still valid; the node clears the canvas and parks.

## Plan and preview artifacts

`PaintingPipeline` writes a versioned JSON document containing logical image
metadata, strategies, statistics, and ordered strokes. This makes the planner
observable independently of animation.

The PNG preview contains original, resized, and quantized panels plus palette
and statistics. It is a target-processing report, not a simulation of pen
thickness or controller error.

Both artifacts are completed in temporary files before destinations are
replaced. This prevents a preview-generation failure from leaving a new plan
beside an old preview.

## Standalone experiment

Run the planner without ROS:

```bash
ros2 run turtlesim_image_painter process_image /tmp/icon.png \
  --width 12 --height 12 --colors 3 \
  --stroke-orientation auto --path-order snake
```

Then inspect the JSON:

```bash
python3 -m json.tool /tmp/icon_plan.json | less
```

Compare horizontal, vertical, and automatic plans by stroke count and travel
distance before watching turtlesim execute them.
