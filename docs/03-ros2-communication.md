# 3. Nodes, Topics, Services, and Parameters

## Learning goals

This chapter connects the communication primitives in ROS 2 to their concrete
uses in `PainterNode`.

## The ROS graph

A ROS graph contains nodes and named communication endpoints. During a normal
run, the important nodes are:

```text
/turtlesim    standard simulator node
/painter      node implemented by this package
```

Inspect them from another sourced terminal:

```bash
ros2 node list
ros2 node info /painter
ros2 node info /turtlesim
```

## Topics: ongoing streams

Topics suit data produced continuously, where publisher and subscriber do not
need a one-to-one request/response relationship.

The painter publishes `geometry_msgs/msg/Twist` on `/turtle1/cmd_vel`:

```text
linear.x   forward velocity
angular.z  yaw rate
```

It subscribes to `turtlesim/msg/Pose` on `/turtle1/pose`, receiving position,
heading, and simulator velocity feedback.

Useful inspection commands are:

```bash
ros2 topic list -t
ros2 topic info /turtle1/pose --verbose
ros2 interface show turtlesim/msg/Pose
ros2 topic echo /turtle1/pose
ros2 topic hz /turtle1/pose
```

The integer `10` passed when creating the publisher and subscription is the
history depth for the default QoS profile. For this local teaching example the
defaults are sufficient. In distributed or lossy systems, reliability,
durability, and deadline policies deserve explicit design.

## Services: discrete operations

Services suit bounded operations with one request and one response. The node
uses:

| Service | Type | Purpose |
|---|---|---|
| `/turtle1/set_pen` | `turtlesim/srv/SetPen` | Select RGB, width, and pen state |
| `/turtle1/teleport_absolute` | `turtlesim/srv/TeleportAbsolute` | Move pen-up to a stroke or parking point |
| `/clear` | `std_srvs/srv/Empty` | Clear the canvas |

Inspect their schemas:

```bash
ros2 service list -t
ros2 interface show turtlesim/srv/SetPen
ros2 interface show turtlesim/srv/TeleportAbsolute
ros2 interface show std_srvs/srv/Empty
```

`call_async()` immediately returns a `Future`. The painter stores that future
and checks it during later timer ticks. Calling a synchronous service from the
timer callback could deadlock a single-threaded executor.

Try a service manually while only turtlesim is running:

```bash
ros2 service call /turtle1/set_pen turtlesim/srv/SetPen \
  "{r: 255, g: 0, b: 0, width: 5, off: 0}"
```

## Parameters: node configuration

Parameters are named values owned by a node. This project declares every
supported painter parameter during node construction, taking defaults from
`PainterConfig` and values supplied by YAML or command-line overrides.

Inspect parameters while the painter is active:

```bash
ros2 param list /painter
ros2 param get /painter control_rate_hz
ros2 param dump /painter
```

The painter takes one validated snapshot at startup. Changing its parameters
during a run does not update `PainterConfig`, because no on-set callback is
registered. This makes one painting deterministic. A future lesson could add
dynamic tuning deliberately.

The painter also acts as a parameter client for `/turtlesim`. It updates
`background_r`, `background_g`, and `background_b`, then calls `/clear` so the
new canvas color becomes visible.

## Timer and executor

The node creates a periodic timer at:

```text
period = 1 / control_rate_hz
```

At the default 20 Hz, `_tick()` is eligible every 50 ms. The executor decides
when callbacks run; it is not a hard real-time scheduler.

Each callback must return quickly:

- `_pose_callback()` stores the latest sample and returns.
- `_tick()` advances one state without sleeping.
- image processing runs on a worker thread.
- service calls return futures that are polled later.

This is cooperative event-driven programming. Responsiveness depends on every
callback respecting the executor.

## Names and namespaces

The code currently uses absolute interface names such as
`/turtle1/cmd_vel`. The leading slash anchors a name at the graph root. This is
clear for a single standard turtlesim instance, but it makes namespacing and
multi-robot reuse harder.

A useful advanced exercise is to replace hard-coded absolute names with
relative names or parameters, launch the nodes inside a namespace, and use ROS
remapping rules. Do this only after you can explain the existing graph.

## Choosing a communication style

Use this rule of thumb:

- Topic: ongoing data stream, loosely coupled producers and consumers.
- Service: short request/response operation.
- Parameter: node-owned configuration or state intended for inspection.
- Action: long-running goal with feedback and cancellation.

The full painting job could be modeled as a ROS 2 action in a more advanced
version. This teaching version keeps the one-shot state machine visible before
introducing action-server abstractions.
