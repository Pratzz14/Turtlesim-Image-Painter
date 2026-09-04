# 5. State Machine and Motion Control

## Learning goals

This chapter explains how `PainterNode` remains responsive, how pose feedback
becomes velocity commands, and how failures are bounded.

## Node construction

`PainterNode.__init__()` performs five jobs:

1. Declare every supported ROS parameter and validate a `PainterConfig`.
2. Create the velocity publisher and pose subscription.
3. Create turtlesim service and parameter clients.
4. Create the planning pipeline and its worker.
5. Create the periodic state-machine timer.

No image is processed in the constructor. Constructors run while the node is
joining the graph, so expensive work there would delay interface readiness and
make failures harder to manage.

## Planning worker

Pillow processing and file output happen on a daemon thread. The worker sets a
`concurrent.futures.Future`; `_tick_preparing()` checks whether it is complete.

Only pure planning code runs on that thread. ROS publishers, clients, logging,
and node state remain on the executor thread. This narrow ownership rule avoids
unnecessary synchronization.

The daemon property means a stuck third-party image operation does not prevent
the Python process from exiting after an abort. Normal work is still tracked
through the future and errors are forwarded into the node state machine.

## Preparation phases

`PREPARING` contains smaller `_phase` values:

```text
"" -> planning -> waiting -> pen_off -> background -> clear
```

- `planning` waits for the worker future.
- `waiting` requires service discovery and, for nonempty plans, a fresh pose.
- `pen_off` ensures canvas setup cannot draw accidentally.
- `background` updates parameters on `/turtlesim`.
- `clear` clears using the newly selected background.

Each phase returns to the executor while waiting. Service deadlines prevent a
missing or broken server from hanging the program.

## Per-stroke sequence

### `MOVING_TO_STROKE`

The pen is already raised. If the turtle is not at the target start point, the
node calls `teleport_absolute`. It preserves the current heading so alignment
is handled explicitly in the next state.

Before the call, the node records `_pose_generation`. Completion requires a
newer pose sample at the requested location. A recent timestamp alone would
not prove that the sample reflects the teleport.

### `ALIGNING`

The target heading is:

```text
atan2(end.y - start.y, end.x - start.x)
```

Angles are normalized into `[-pi, pi)` so the turtle takes the shortest turn.
The proportional command is:

```text
angular = clamp(angular_gain * heading_error, max_angular_speed)
```

The node publishes zero velocity before leaving the state.

### `PEN_DOWN`

The node calls `set_pen` with the stroke RGB and configured width. In dry-run
mode it skips enabling the pen but continues through all motion states.

### `DRAWING`

The controller is recalculated from every fresh pose:

```text
linear  = min(max_linear_speed, linear_gain * remaining_distance)
angular = clamp(angular_gain * live_heading_error, max_angular_speed)
```

This is closed-loop control: later commands depend on measured state, not only
the original plan. Linear speed naturally decreases near the endpoint.

### `PEN_UP`

The node disables the pen, increments progress, and selects the next state. A
stroke with the same color begins immediately. A new color enters
`COLOR_CHANGE`, which implements a non-blocking pause using a deadline.

## Pose freshness

The node stores both the latest pose and its local monotonic receipt time. A
motion state fails when no pose arrives within `pose_timeout_sec`.

Monotonic time is used instead of wall-clock time because clock corrections
must not extend or shorten safety deadlines.

There are two separate concepts:

- Freshness: the sample arrived recently.
- Generation: the sample arrived after a particular teleport request.

Both are required when confirming teleports and parking.

## Parking and success

After the final stroke, or immediately after an empty plan, the turtle is
teleported pen-up to `(parking_x, parking_y)` with heading zero. A new matching
pose is required before success.

On success the node publishes stop, enters `FINISHED`, cancels its timer,
closes the planner, logs final statistics, and returns exit code zero.

## Error path

`_fail()` is a transition, not an exception thrown through the executor. It:

1. Records the first failure reason.
2. Cancels pending futures when possible.
3. Publishes zero velocity.
4. Enters `ERROR`.
5. Stops accepting planning work.

`_tick_error()` then attempts one best-effort pen-off request. Cleanup has its
own deadline; it cannot wait forever for the service graph that may already be
broken. The node publishes a final stop and exits with code one.

SIGINT and SIGTERM are caught by the entry point and converted into the same
abort path before `rclpy.shutdown()` destroys communication resources.

## Why this is not an action server

Painting is a long-running operation, so a ROS 2 action would be a natural
production interface. This repository first exposes the underlying mechanics:
state, feedback, cancellation, progress, and terminal results.

After mastering this implementation, an excellent extension is an action
server whose execute logic drives the existing state machine and publishes
stroke progress as action feedback.

## Controller experiment

Run a low-resolution dry route and change only one value at a time:

```bash
ros2 run turtlesim_image_painter painter \
  --ros-args --params-file /path/to/default.yaml \
  -p image_path:=/tmp/icon.png -p dry_run:=true \
  -p linear_gain:=1.0
```

Observe how lower gain slows convergence. Then restore it and reduce
`max_linear_speed`. The gain shapes the command near the target; the maximum
caps it far from the target.
