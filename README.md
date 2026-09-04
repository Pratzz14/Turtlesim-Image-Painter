# turtlesim_image_painter

Turtle Image Painter is a ROS 2 application that converts a PNG or JPEG into
a simplified pixel-art representation and commands a turtlesim turtle to paint
it on the canvas.

The image-processing core can be used without starting ROS:

```python
from turtlesim_image_painter import ImageProcessor

result = ImageProcessor().process(
    'picture.png',
    max_width=80,
    max_height=80,
    palette_size=4,
)

print(result.width, result.height)
print(result.palette)
print(result.pixels)
```

Palette sizes from 2 through 8 are supported by both the Python and ROS APIs.

The processed pixels can then be converted into safe horizontal or vertical
strokes:

```python
from turtlesim_image_painter import CanvasBounds, StrokeGenerator

generator = StrokeGenerator(
    bounds=CanvasBounds(1.0, 10.0, 1.0, 10.0),
    exclude_background=True,
    stroke_orientation='auto',
)
generated = generator.generate(result)

print(generated.plan.strokes)
print(generated.statistics)
```

The image is uniformly scaled and centered inside the configured canvas. Image
rows are mapped from top to bottom by inverting the Turtlesim Y-axis. In the
default `auto` orientation, each color layer uses horizontal or vertical runs,
whichever produces fewer strokes. Tied candidates use the shortest pen-up
route, with horizontal as the deterministic final tie-breaker. Each stroke
spans the complete logical cell edges, and detected background runs are skipped
by default.

The standalone command runs the complete planning pipeline and writes a JSON
painting plan plus a composite PNG preview next to the input image:

```bash
process_image picture.png --colors 4 --stroke-orientation auto \
  --path-order snake
```

The default artifacts are `picture_plan.json` and `picture_preview.png`. Use
`--plan-output` and `--preview-output` to choose other paths. Colors are grouped
largest-first by painted pixel count with RGB tie-breaking. Raster order scans
each group from top-left. Snake order alternates direction across rows for
horizontal strokes and columns for vertical strokes. Reported travel covers
pen-up movement between strokes, while paint distance covers the strokes
themselves.

Inputs are EXIF-oriented, converted to RGB, composited over white when they
contain transparency, and resized without changing aspect ratio using Hamming
downsampling to avoid ringing around sharp artwork. When a dominant background
is detected, colors within `background_tolerance` of it are consolidated and
one palette entry is reserved for the exact background; median-cut
quantization then spends the remaining entries on meaningful foreground
colors. The tuned defaults are an 80-pixel bounding box, four colors, a
background tolerance of 24, and a pen width of 6. The default ROS parameters
are in `config/default.yaml`.

## Paint an image in Turtlesim

The one-shot `painter` node runs the image pipeline and executes its complete
multi-color plan. Image processing runs in a background worker, service calls
are asynchronous, and a control timer advances the painting states. The node
uses pen-up teleportation between disconnected strokes and pose-controlled
`cmd_vel` motion while aligning and drawing.

Build the workspace and source ROS 2 Jazzy plus the workspace installation.
Then start Turtlesim in one terminal:

```bash
ros2 run turtlesim turtlesim_node
```

In a second terminal, provide an absolute PNG or JPEG path and run the painter:

```bash
ros2 run turtlesim_image_painter painter --ros-args \
  --params-file "$(ros2 pkg prefix turtlesim_image_painter)/share/turtlesim_image_painter/config/default.yaml" \
  -p image_path:=/absolute/path/to/picture.png
```

By default the generated plan JSON and preview PNG are written next to the
source image. Set `plan_output` and `preview_output` to override those paths.
The painter clears to the configured background, completes every stroke in one
color before waiting `color_change_pause_sec` and switching layers, then stops,
raises the pen, teleports to the configured bottom-left parking position, logs
completion, and exits. The default controller gains and speed limits are tuned
for twice the original movement speed. The default pen width is matched to the
80-pixel planning grid so neighboring strokes visually join instead of leaving
vertical or horizontal gaps. All settings remain overrideable ROS parameters.

Set `dry_run:=true` to perform the same planning, canvas setup, teleports,
alignment, drawing route, and final parking while keeping the pen disabled.
Empty plans are successful: the node still configures and clears the canvas,
ensures the pen is off, and parks the turtle without requiring an initial pose.
Service calls, pose feedback, teleport confirmation, alignment, drawing, and
parking are bounded by the configured timeouts; any unrecoverable error
publishes a stop immediately and makes one bounded best-effort pen-off request
before exiting with failure. Override `parking_x` and `parking_y` to select a
different positive, finite parking position.
