# 6. Testing, Debugging, and Exercises

## Learning goals

This chapter shows how the test suite is layered, how ROS-facing code is tested
without driving a GUI for every case, and how to extend the project safely.

## Run the complete suite

From the workspace root:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select turtlesim_image_painter
source install/setup.bash
colcon test --packages-select turtlesim_image_painter
colcon test-result --verbose
```

For a faster source-tree loop after the environment is sourced:

```bash
cd src/turtlesim_image_painter
python3 -m pytest -q
```

If imports such as `rclpy`, `launch`, or `ament_flake8` fail during collection,
check that the ROS underlay is sourced. If this package cannot be imported,
source the workspace overlay or install it into the active Python environment.

## Test layers

### Models

`test_models.py` checks invariants such as matrix dimensions, palette
consistency, canvas bounds, and distance totals. These tests demonstrate how
validated value objects prevent invalid state from spreading.

### Image processing

`test_image_processing.py` creates tiny images in temporary directories. It
checks formats, corrupt inputs, decompression protection, EXIF orientation,
alpha composition, resizing, quantization, background tolerance, and the
end-to-end pixel matrix.

### Geometry and controller math

`test_stroke_generation.py` uses hand-written color grids whose exact strokes
are easy to predict. It covers coordinate inversion, centering, bounds,
run-length merging, strategies, distances, and empty plans.

`test_turtle_control.py` exercises configuration and motion math without ROS
messages. Boundary cases include angle wraparound, inclusive tolerances, sign,
and speed clamping.

### Pipeline and CLI

`test_pipeline.py` verifies JSON structure, preview contents, filename
validation, hard-link protection, and all-or-nothing preparation of artifacts.

`test_process_image_cli.py` invokes the CLI entry function directly and checks
exit codes, output text, options, and artifact creation.

### Launch

`test_launch.py` loads the Python launch file as a module. It checks argument
mapping and inspects the resulting launch actions without starting GUI
processes.

### ROS state machine

`test_painter.py` initializes a controlled ROS context but substitutes fake
publishers, service clients, parameter clients, futures, and pipeline results.
A fake monotonic clock moves deadlines instantly.

This makes difficult paths deterministic:

- pending planning while pose callbacks continue;
- service discovery and timeout;
- post-teleport pose generations;
- color-layer pauses;
- dry-run behavior;
- movement deadlines;
- rejected background parameters;
- failures during parking and cleanup;
- SIGINT shutdown ordering.

The tests call `_tick()` deliberately. Each call represents one executor timer
opportunity, making state transitions visible and teachable.

## Debugging a live run

Use three terminals, all with ROS and the workspace sourced.

Terminal 1 starts the application:

```bash
ros2 launch turtlesim_image_painter painter.launch.py \
  image:=/tmp/icon.png resolution:=12
```

Terminal 2 inspects the graph:

```bash
ros2 node info /painter
ros2 topic hz /turtle1/pose
ros2 topic echo /turtle1/cmd_vel
```

Terminal 3 inspects configuration and services:

```bash
ros2 param dump /painter
ros2 service list -t
```

If the painter reports stale pose feedback, first verify that
`/turtle1/pose` is publishing. If a service times out, verify that its exact
name and type appear in `ros2 service list -t`.

## Adding a new parameter

Use this checklist:

1. Add the field and validation to `PainterConfig`.
2. Add the same default under `painter.ros__parameters` in `default.yaml`.
3. Pass it into the relevant planner or executor behavior.
4. Add a launch argument only if it belongs in the intentionally small public
   launch interface.
5. Add valid, invalid, and behavior tests.
6. Update the root parameter table and the relevant learning guide.

The config dataclass is the authoritative list used for ROS declaration; the
YAML file is the installed operational default. Tests should detect drift.

## Adding a planning strategy

For a new stroke or ordering strategy:

1. Implement geometry in `StrokeGenerator`, not `PainterNode`.
2. Keep output deterministic for identical inputs.
3. Preserve endpoint bounds and distance accounting.
4. Extend CLI/config validation consistently.
5. Start with tiny, exact color-grid tests.
6. Inspect generated JSON before running turtlesim.

## Guided exercises

### Exercise 1: Observe feedback control

Run at low resolution and echo `/turtle1/pose` and `/turtle1/cmd_vel`. Identify
when angular velocity dominates and when linear velocity decays.

### Exercise 2: Compare topic and service semantics

Stop the painter and manually publish one `Twist`, then call
`teleport_absolute`. Explain why one operation has no response and the other
does.

### Exercise 3: Add live progress

Create a publisher for completed and total stroke counts. Decide whether a
standard message or custom message is appropriate. Keep progress publication
inside `_advance_stroke()` and add a fake-publisher test.

### Exercise 4: Add namespacing

Replace absolute interface names with relative names and launch both nodes in
a namespace. Use `ros2 node info` to verify resolved names. Consider how a
parameter for the turtle name would affect interfaces.

### Exercise 5: Convert painting into an action

Define goal, feedback, and result data. Reuse the existing state machine rather
than copying movement logic. Support cancellation by entering the current safe
abort path.

### Exercise 6: Replace teleport travel

Add a pen-up driving state instead of teleporting between strokes. Then decide
whether planned travel distance becomes a useful estimate of physical motion
and which additional collision or timeout considerations appear.

## Contribution standard

Comments should explain why a choice exists, especially around ROS callback
ownership, asynchronous behavior, coordinate transforms, and safety. Public
functions and classes need concise docstrings. Detailed tutorials and command
walkthroughs belong in `docs/`, keeping source files readable enough to use in
live teaching.
