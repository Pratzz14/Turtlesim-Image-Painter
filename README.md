# Turtlesim Image Painter

Turtlesim Image Painter is a teaching-oriented ROS 2 application that turns a
PNG or JPEG into simplified pixel art, plans color-grouped strokes, and drives
the standard turtlesim turtle to paint the result. One launch command starts
the simulator and painter, writes an inspectable JSON plan and PNG preview,
prints progress as the picture is drawn, and leaves the finished canvas open.

## Learn ROS 2 with this repository

The source is organized as a guided ROS 2 project, from pure Python planning
through topics, services, parameters, timers, feedback control, and safe
shutdown. Start with the ordered [ROS 2 Learning Guide](docs/README.md). It
includes architecture explanations, graph-inspection commands, controller
walkthroughs, testing techniques, and progressively harder exercises.

## How it works

The project separates image processing from ROS control so each stage can be
understood and tested independently:

```text
PNG/JPEG
  -> orient, composite transparency, and resize
  -> detect background and quantize the palette
  -> convert logical pixels into color-grouped strokes
  -> save JSON plan and composite PNG preview
  -> set/clear the turtlesim canvas
  -> teleport pen-up, align, and draw each stroke
  -> park the turtle and report final statistics
```

`image_processing.py` owns Pillow conversion and quantization.
`stroke_generation.py` maps processed pixels into safe turtlesim coordinates.
`pipeline.py` writes the plan and preview atomically. `painter.py` is a
timer-driven ROS node: image processing runs in a worker thread, while service,
pose, and velocity operations remain non-blocking in the ROS executor.
Configuration validation lives separately in `configuration.py`, and
ROS-independent controller math lives in `motion_control.py`.

The generated distance values are planned canvas-space distances. Paint
distance is the sum of stroke lengths; travel distance covers pen-up movement
between planned strokes. Initial turtle placement and final parking are not
included.

## Requirements and setup

The package targets ROS 2 Jazzy and Python 3. Install turtlesim, Pillow, and
PyYAML through rosdep or your platform package manager. From the workspace
root:

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --packages-select turtlesim_image_painter
source install/setup.bash
```

Always source both ROS and the workspace in every new terminal. The launch file
and default configuration are installed under
`share/turtlesim_image_painter/`.

## Paint an image

Use an absolute path so the painter resolves the same file regardless of the
directory from which launch is called:

```bash
ros2 launch turtlesim_image_painter painter.launch.py \
  image:=/absolute/path/to/image.png
```

The `image` argument is required. Two optional convenience arguments override
the installed YAML values:

```bash
ros2 launch turtlesim_image_painter painter.launch.py \
  image:=/absolute/path/to/image.png \
  colors:=6 \
  resolution:=48
```

- `colors` accepts 2 through 8 and maps to `palette_size`.
- `resolution` is a positive integer that sets both `max_width` and
  `max_height`. Aspect ratio is preserved inside that square bound.
- If either optional argument is omitted, its values come from the installed
  `config/default.yaml`.

Run `ros2 launch turtlesim_image_painter painter.launch.py --show-args` to
inspect the launch interface. After the painter exits, turtlesim intentionally
continues running so the final canvas remains visible. Press Ctrl-C in the
launch terminal when finished.

By default, `<image_stem>_plan.json` and `<image_stem>_preview.png` are written
next to the source image. The output directory must therefore be writable.
The terminal reports every color layer and completed stroke, then prints the
original and processed resolution, palette and painted colors, skipped
background, logical pixels, strokes, color changes, distances, elapsed time,
and both artifact paths.

## Configuration parameters

The launch file loads `config/default.yaml` from the installed package. Edit a
workspace copy and rebuild when teaching or tuning the full parameter set.
For direct node experiments, pass that YAML file with `ros2 run` and override
individual parameters using `-p`.

| Parameter | Default | Purpose |
| --- | ---: | --- |
| `image_path` | empty | Required PNG or JPEG path; supplied by launch `image`. |
| `plan_output` | empty | JSON path; empty selects the image-adjacent default. |
| `preview_output` | empty | PNG path; empty selects the image-adjacent default. |
| `max_width`, `max_height` | `80`, `80` | Processed-image bounding box. |
| `palette_size` | `4` | Maximum quantized colors, from 2 through 8. |
| `transparency_color` | `[255, 255, 255]` | RGB used beneath transparent pixels. |
| `background_threshold` | `0.5` | Fraction required to identify a dominant background. |
| `background_tolerance` | `24` | RGB channel tolerance used to consolidate near-background pixels. |
| `allow_upscale` | `false` | Allow small inputs to grow to the configured bound. |
| `exclude_background` | `true` | Skip detected background pixels and use that RGB for the canvas. |
| `color_order` | `largest_first` | Paint larger color regions first. |
| `path_order` | `raster` | Use `raster` or alternating `snake` traversal within layers. |
| `stroke_orientation` | `auto` | Use `auto`, `horizontal`, or `vertical` runs. |
| `pen_width` | `6` | Turtlesim pen width in pixels. |
| `background_r/g/b` | `255/255/255` | Canvas fallback when detection is absent or exclusion is disabled. |
| `canvas_min_x/max_x` | `1.0/10.0` | Safe horizontal painting limits. |
| `canvas_min_y/max_y` | `1.0/10.0` | Safe vertical painting limits. |
| `parking_x`, `parking_y` | `0.5`, `0.5` | Unobtrusive final turtle position. |
| `control_rate_hz` | `20.0` | Painter state-machine update rate. |
| `linear_gain`, `angular_gain` | `3.0`, `12.0` | Feedback-controller gains. |
| `max_linear_speed` | `4.0` | Linear velocity limit. |
| `max_angular_speed` | `8.0` | Angular velocity limit. |
| `position_tolerance` | `0.05` | Accepted endpoint error in canvas units. |
| `angle_tolerance` | `0.02` | Accepted heading error in radians. |
| `service_timeout_sec` | `5.0` | Bound for turtlesim service operations. |
| `pose_timeout_sec` | `2.0` | Bound for fresh pose feedback. |
| `movement_timeout_sec` | `30.0` | Bound for one alignment or drawing movement. |
| `color_change_pause_sec` | `1.0` | Non-blocking pause between color layers. |
| `dry_run` | `false` | Execute the route while keeping the pen disabled. |

When `exclude_background` is enabled and a dominant background is detected,
the painter sets turtlesim to that detected RGB before clearing. If detection
finds nothing, or exclusion is disabled, the configured `background_r/g/b`
fallback is used. Empty foreground plans still clear the canvas and park
safely.

## Process without ROS

The standalone command runs the same processing, planning, and preview stages:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 run turtlesim_image_painter process_image \
  /absolute/path/to/image.png --colors 4 --path-order snake
```

The Python API exposes the same building blocks:

```python
from turtlesim_image_painter import ImageProcessor, StrokeGenerator

processed = ImageProcessor().process('picture.png', palette_size=4)
planned = StrokeGenerator().generate(processed)
print(planned.statistics)
```

## Manual GUI demonstration

1. Choose a small, high-contrast PNG or JPEG with two to four large color
   regions. Confirm its directory is writable.
2. Build and source the workspace using the commands above.
3. Launch with the image's absolute path. For a quick classroom run, add
   `colors:=4 resolution:=24`.
4. Confirm turtlesim opens, the canvas is cleared to the detected or fallback
   background, and terminal logs advance color by color and stroke by stroke.
5. Wait for the turtle to park in the lower-left corner and for the final
   statistics block to appear.
6. Compare the recognizable canvas painting with the saved preview PNG and
   inspect the JSON plan if desired.
7. Confirm the canvas remains visible after the painter process completes,
   then press Ctrl-C to close the launch.

## Troubleshooting

- **`Package ... not found`**: source `/opt/ros/jazzy/setup.bash`, rebuild, and
  source the workspace's `install/setup.bash` in the same terminal.
- **Launch says `image` is required**: provide `image:=` followed by an
  absolute PNG or JPEG path.
- **Image or artifact error**: verify the file exists, has PNG/JPEG contents,
  and its directory is writable. Use `plan_output` and `preview_output` with a
  direct node run when another destination is needed.
- **Painter times out waiting for services or pose**: ensure only one turtlesim
  instance owns `/turtlesim` and `/turtle1`, then restart the launch.
- **Painting has gaps**: lower the logical resolution or increase `pen_width`.
- **Painting is slow**: lower `resolution`, choose fewer colors, or tune speed
  limits conservatively. `dry_run:=true` is useful for route debugging through
  a direct node run.
- **Background is painted unexpectedly**: check `exclude_background`,
  `background_threshold`, and `background_tolerance`.

## Extending the project

New image algorithms should remain in the ROS-independent processor and return
validated `ProcessedImage` data. New route strategies belong in
`StrokeGenerator` and should preserve color grouping, bounded endpoints, and
distance accounting. Controller changes should stay timer-driven and keep all
service, pose, and movement timeouts plus the best-effort pen-off failure path.

Add pure unit tests for processing and geometry first, then state-machine tests
with fake ROS clients. When introducing a new user setting, add it consistently
to `PainterConfig`, `config/default.yaml`, launch mapping when appropriate, and
this parameter reference. See `CONTRIBUTING.md` for the validation checklist.

## License

This project is licensed under the MIT License. See `LICENSE`.
