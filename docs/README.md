# ROS 2 Learning Guide

This directory turns `turtlesim_image_painter` into a guided ROS 2 study
project. The application is intentionally larger than a minimal publisher or
subscriber: it shows how those primitives fit together in a complete,
testable, failure-aware program.

## What you will learn

By working through the guides in order, you will learn how to:

- recognize the files that make a Python project a ROS 2 package;
- build and source an overlay workspace;
- start multiple nodes with a Python launch file;
- use topics for streams, services for discrete operations, and parameters for
  configuration;
- keep callbacks short and avoid blocking the ROS executor;
- turn subscriber feedback into closed-loop motion commands;
- model a long-running behavior as an explicit state machine;
- keep domain logic independent of ROS and unit test it quickly;
- test ROS-facing code with controlled clocks and fake interfaces;
- inspect a running ROS graph from the command line.

## Recommended reading order

1. [Architecture and data flow](01-architecture-and-data-flow.md)
2. [ROS 2 package, build, and launch](02-ros2-package-build-and-launch.md)
3. [Nodes, topics, services, and parameters](03-ros2-communication.md)
4. [Image processing and stroke planning](04-image-processing-and-planning.md)
5. [State machine and motion control](05-state-machine-and-control.md)
6. [Testing, debugging, and exercises](06-testing-debugging-and-exercises.md)

The project root [README](../README.md) is the operator reference: it explains
how to install, launch, configure, and troubleshoot the application. These
documents explain why the code is structured this way and how its ROS 2 pieces
cooperate.

## A productive study loop

For each chapter:

1. Read the concept and locate the linked source file.
2. Predict what one configuration or code change will do.
3. Run the relevant test before changing anything.
4. Make one small change.
5. Run the test again and inspect the ROS graph or generated plan.
6. Revert or commit the experiment before starting the next one.

This tight loop is more useful than reading every source file from top to
bottom without running it.

## Quick setup

From the ROS 2 workspace root, not this package directory:

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --packages-select turtlesim_image_painter
source install/setup.bash
```

Use a small image for early experiments:

```bash
ros2 launch turtlesim_image_painter painter.launch.py \
  image:=/absolute/path/to/image.png colors:=3 resolution:=12
```

Open a second sourced terminal for `ros2 node`, `ros2 topic`, `ros2 service`,
and `ros2 param` inspection commands.

## Source-code reading map

The source is split by responsibility:

```text
configuration.py   validated application settings
models.py          immutable data exchanged between layers
image_processing.py
                    file and pixel operations; no ROS imports
stroke_generation.py
                    image-to-canvas geometry; no ROS imports
motion_control.py  controller math; no ROS imports
pipeline.py        planning orchestration and artifacts
preview.py         human-readable PNG report
painter.py         ROS node, interfaces, timers, and state machine
turtle_control.py  compatibility imports for older lessons/code
```

The separation is itself a lesson: importing ROS message classes throughout a
project makes logic harder to test and reuse. Here, only the execution boundary
converts plain Python values into ROS messages and requests.

## How comments are used

The code uses docstrings to state what public modules, classes, and functions
do. Inline comments are reserved for decisions that are not obvious from the
syntax—for example, why planning runs off the executor, why pose generations
are tracked, or why background color is reserved during quantization.

Comments that merely repeat an assignment are intentionally avoided. The
long-form rationale belongs in these guides so the implementation remains
readable during experiments.
