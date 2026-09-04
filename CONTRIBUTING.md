# Contributing

Any contribution that you make to this repository will
be under the MIT license, as dictated by that
[license](https://opensource.org/licenses/MIT).

Keep image processing, stroke generation, configuration validation, and motion
math independent of ROS. Preserve the painter's non-blocking state machine and
safety timeouts, and add tests for every behavior change.

Use comments to explain non-obvious intent—callback ownership, asynchronous
sequencing, safety decisions, and coordinate transforms—not to restate the
syntax. Put longer conceptual explanations and runnable lessons in `docs/`,
and link new guides from `docs/README.md`.

Before submitting a change, run from the ROS 2 workspace root:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select turtlesim_image_painter
colcon test --packages-select turtlesim_image_painter
colcon test-result --verbose
```

New Python files must include the project's MIT copyright header and pass the
ament flake8, PEP 257, and copyright checks.
