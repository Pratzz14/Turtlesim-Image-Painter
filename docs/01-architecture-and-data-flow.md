# 1. Architecture and Data Flow

## Learning goals

After this chapter you should be able to identify the boundary between domain
logic and ROS 2 infrastructure, trace an image through the application, and
explain why the painter is implemented as a state machine.

## The two halves of the application

The package has a planning half and an execution half:

```text
Planning: image file -> ProcessedImage -> PaintingPlan -> artifacts
Execution: PaintingPlan + Pose feedback -> ROS commands/services -> canvas
```

Planning is deterministic and ROS-independent. It can run in a normal Python
process and is exercised by fast unit tests. Execution depends on a live ROS
graph and contains the timing, communication, and safety behavior.

The dependency direction is deliberately one-way:

```text
models
  ^        ^             ^
  |        |             |
image   strokes     motion_control
  \        /             |
   \      /              |
    pipeline              |
        \                 |
         +---- painter ---+
```

The pure layers do not import `rclpy`, `geometry_msgs`, or `turtlesim`. This is
the most important factoring rule in the repository.

## End-to-end startup

The normal entry path is:

1. `ros2 launch` loads `launch/painter.launch.py`.
2. The launch description starts the standard `turtlesim_node`.
3. It starts this package's `painter` executable with YAML parameters and
   launch-argument overrides.
4. `painter:main` initializes `rclpy` and creates `PainterNode`.
5. The node creates its publisher, subscriber, service clients, parameter
   client, and periodic timer.
6. The first timer tick starts the planning pipeline on a worker thread.
7. The executor continues receiving pose samples while planning runs.
8. When the plan is ready, the node configures the canvas and executes strokes.
9. The turtle is parked, final statistics are logged, and the painter exits.
10. The turtlesim process remains open so the finished canvas can be studied.

## Data objects crossing the layers

Read `turtlesim_image_painter/models.py` before the algorithms. Its frozen
dataclasses form the vocabulary of the codebase:

- `Color` is a validated RGB value.
- `ProcessedImage` is an immutable logical pixel grid and palette.
- `Point` is a canvas position.
- `Stroke` is one colored line segment.
- `PaintingPlan` is the ordered sequence the node executes.
- `Statistics` describes the plan without requiring ROS.
- `PipelineResult` connects the plan to its source dimensions and artifacts.

Validation occurs when these objects are constructed. That makes errors fail
near their source instead of surfacing later as malformed service requests or
unsafe coordinates.

## Why the pipeline returns a plan

The image processor does not command the turtle directly. It first produces a
complete plan. This provides several advantages:

- The expensive work finishes before movement starts.
- The JSON plan can be inspected without running turtlesim.
- Geometry and ordering can be tested exactly.
- Runtime progress has a known total.
- The node does not need to mix pixel algorithms into callbacks.

This is an example of separating planning from execution, a common robotics
pattern. More advanced systems use the same idea for paths, trajectories, and
task plans.

## Why execution needs explicit state

A naive implementation might call a service, sleep, move, sleep again, and
repeat. In a single-threaded executor those sleeps prevent pose and service
callbacks from running. The program would be waiting for information it had
prevented itself from receiving.

Instead, each timer tick performs a small amount of work and returns. State
records what should happen on the next tick. Service `Future` objects are
polled rather than waited on synchronously.

The main sequence is:

```text
IDLE -> PREPARING
     -> MOVING_TO_STROKE -> ALIGNING -> PEN_DOWN -> DRAWING -> PEN_UP
     -> COLOR_CHANGE when the RGB layer changes
     -> PARKING -> FINISHED

Any active state -> ERROR -> bounded cleanup
```

This architecture allows the executor to interleave timer, subscription, and
service-response callbacks.

## Distance terminology

The plan reports two geometric distances:

- Paint distance is the sum of visible stroke lengths.
- Travel distance is the distance from one completed stroke endpoint to the
  next stroke start.

The executor teleports during pen-up repositioning, so travel distance is a
property of route quality, not measured driving odometry. Initial placement
and final parking are not counted.

## Questions to check your understanding

1. Which modules can be imported on a machine without ROS 2 installed?
2. Why is `ProcessedImage` immutable?
3. Why does the node plan everything before it lowers the pen?
4. What callback would be starved if a timer callback used `time.sleep()`?
5. Why can a valid image result in an empty painting plan?
