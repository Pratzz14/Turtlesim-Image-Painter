# turtlesim_image_painter

Turtle Image Painter is a ROS 2 application that converts a PNG or JPEG into
a simplified pixel-art representation and commands a turtlesim turtle to paint
it on the canvas.

The image-processing core can be used without starting ROS:

```python
from turtlesim_image_painter import ImageProcessor

result = ImageProcessor().process(
    'picture.png',
    max_width=64,
    max_height=64,
    palette_size=8,
)

print(result.width, result.height)
print(result.palette)
print(result.pixels)
```

The processed pixels can then be converted into safe horizontal strokes:

```python
from turtlesim_image_painter import CanvasBounds, StrokeGenerator

generator = StrokeGenerator(
    bounds=CanvasBounds(1.0, 10.0, 1.0, 10.0),
    exclude_background=True,
)
generated = generator.generate(result)

print(generated.plan.strokes)
print(generated.statistics)
```

The image is uniformly scaled and centered inside the configured canvas. Image
rows are mapped from top to bottom by inverting the Turtlesim Y-axis, and each
maximal horizontal run of one color becomes a stroke spanning the complete
logical cell edges. Detected background runs are skipped by default.

The standalone command runs the complete planning pipeline and writes a JSON
painting plan plus a composite PNG preview next to the input image:

```bash
process_image picture.png --path-order snake
```

The default artifacts are `picture_plan.json` and `picture_preview.png`. Use
`--plan-output` and `--preview-output` to choose other paths. Colors are grouped
largest-first by painted pixel count with RGB tie-breaking. Raster order scans
each group from top-left; snake order reverses both run order and stroke
endpoints on odd source rows. Reported travel covers pen-up movement between
strokes, while paint distance covers the strokes themselves.

Inputs are EXIF-oriented, converted to RGB, composited over white when they
contain transparency, resized without changing aspect ratio, and quantized
using median cut. The default ROS parameters are in `config/default.yaml`.

## Draw one line in Turtlesim

Sprint 4 adds a one-shot `painter` node. It clears the canvas, teleports with
the pen raised, aligns from pose feedback, and draws one configured horizontal
line. All service calls and motion are asynchronous; completion is determined
from `/turtle1/pose`, not elapsed sleeps.

Build the workspace and source ROS 2 Jazzy plus the workspace installation.
Then start Turtlesim in one terminal:

```bash
ros2 run turtlesim turtlesim_node
```

In a second terminal, run the painter with the installed defaults:

```bash
ros2 run turtlesim_image_painter painter --ros-args \
  --params-file "$(ros2 pkg prefix turtlesim_image_painter)/share/turtlesim_image_painter/config/default.yaml"
```

The default run clears to white, draws a red line from `(2.0, 5.5)` to
`(9.0, 5.5)`, stops the turtle, turns its pen off, logs successful completion,
and exits. The start and end X coordinates, shared Y coordinate, line and
background RGB values, pen width, controller gains and limits, tolerances, and
service/pose timeouts can all be overridden with ROS parameters. Both
left-to-right and right-to-left lines are supported; equal X endpoints and
coordinates outside the configured canvas bounds are rejected.
