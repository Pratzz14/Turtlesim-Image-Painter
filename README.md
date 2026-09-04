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

Inputs are EXIF-oriented, converted to RGB, composited over white when they
contain transparency, resized without changing aspect ratio, and quantized
using median cut. The default ROS parameters are in `config/default.yaml`.
