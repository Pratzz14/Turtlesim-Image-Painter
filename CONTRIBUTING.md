# Contributing

Any contribution that you make to this repository will
be under the MIT license, as dictated by that
[license](https://opensource.org/licenses/MIT).

Keep image processing and stroke generation independent of ROS where possible,
preserve the painter's non-blocking state machine and safety timeouts, and add
tests for every behavior change.

Before submitting a change, run from the ROS 2 workspace root:

```bash
source /opt/ros/jazzy/setup.bash
colcon build --packages-select turtlesim_image_painter
colcon test --packages-select turtlesim_image_painter
colcon test-result --verbose
```

New Python files must include the project's MIT copyright header and pass the
ament flake8, PEP 257, and copyright checks.
