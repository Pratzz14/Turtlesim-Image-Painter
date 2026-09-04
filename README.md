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

Inputs are EXIF-oriented, converted to RGB, composited over white when they
contain transparency, resized without changing aspect ratio, and quantized
using median cut. The default ROS parameters are in `config/default.yaml`.
