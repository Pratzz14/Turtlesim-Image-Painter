# 2. ROS 2 Package, Build, and Launch

## Learning goals

This chapter explains the files ROS 2 uses to discover, build, install, and
launch the package, plus the difference between an underlay and an overlay.

## Workspace and package layout

A typical workspace is:

```text
ros2_ws/
  src/
    turtlesim_image_painter/   <- this repository
  build/                       <- colcon intermediate files
  install/                     <- runnable overlay
  log/                         <- build and test logs
```

Edit files under `src`. `colcon build` copies or links package products into
`install`. ROS commands discover the installed package through environment
variables populated by setup scripts.

## Underlay and overlay

These two commands serve different purposes:

```bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
```

The first sources the ROS 2 Jazzy underlay: `rclpy`, message definitions,
launch, turtlesim, and command-line tools. The second sources your workspace
overlay so ROS can find this package and its latest build.

Source them in that order in every new terminal. If `ros2 pkg prefix
turtlesim_image_painter` fails, the overlay is missing or stale.

## `package.xml`

`package.xml` is the ROS package manifest. It declares:

- package name and version;
- maintainer and license;
- runtime dependencies such as `rclpy`, `geometry_msgs`, and `turtlesim`;
- test dependencies such as `ament_flake8` and `pytest`;
- `ament_python` as the build type.

`rosdep` reads these dependency declarations and maps them to platform
packages. Python's `install_requires` is still present, but ROS dependencies
belong in `package.xml` because they are not ordinary PyPI libraries.

## `setup.py`, `setup.cfg`, and the resource marker

`setup.py` is the Python packaging definition. It installs:

- the `turtlesim_image_painter` Python package;
- the top-level `process_image` module;
- `package.xml`, the license, configuration, launch files, and learning docs;
- the `painter` and `process_image` console scripts.

`setup.cfg` places console scripts in `lib/turtlesim_image_painter`, the
location from which `ros2 run` expects to find Python executables.

The empty `resource/turtlesim_image_painter` marker is installed into the
ament resource index. It lets tools such as `ament_index_python` discover the
package share directory.

Inspect the installation after building:

```bash
ros2 pkg prefix turtlesim_image_painter
ros2 pkg executables turtlesim_image_painter
```

## Building only this package

From the workspace root:

```bash
colcon build --packages-select turtlesim_image_painter
source install/setup.bash
```

Re-source after building so the current shell uses the refreshed overlay.
When diagnosing confusing imports, inspect the path Python selected:

```bash
python3 -c "import turtlesim_image_painter; print(turtlesim_image_painter.__file__)"
```

## Python launch file

`launch/painter.launch.py` returns a `LaunchDescription`. Its visible actions
are:

- three launch arguments: `image`, `colors`, and `resolution`;
- a `Node` action for the standard turtlesim node;
- an `OpaqueFunction` that creates the painter node.

Launch substitutions are lazy objects, not ordinary strings. The
`OpaqueFunction` runs after a `LaunchContext` exists, allowing the code to
resolve the argument strings, validate them, and construct parameter
overrides.

The painter receives two parameter sources:

```python
parameters=[path_to_default_yaml, launch_argument_overrides]
```

Later entries override earlier ones. If `colors` or `resolution` is omitted,
the key is absent from the override dictionary and the YAML value survives.

View the public interface with:

```bash
ros2 launch turtlesim_image_painter painter.launch.py --show-args
```

## `ros2 launch` versus `ros2 run`

Use launch for the complete application:

```bash
ros2 launch turtlesim_image_painter painter.launch.py image:=/tmp/icon.png
```

Use `ros2 run` when you want to start pieces manually or override arbitrary ROS
parameters:

```bash
ros2 run turtlesim turtlesim_node

ros2 run turtlesim_image_painter painter \
  --ros-args \
  --params-file /path/to/default.yaml \
  -p image_path:=/tmp/icon.png \
  -p dry_run:=true
```

The second approach is useful while learning because each process has its own
terminal and logs.

## Suggested experiment

1. Run `ros2 pkg executables turtlesim_image_painter`.
2. Change the launch `resolution` and inspect the processed dimensions in the
   final report.
3. Omit `colors` and verify that the YAML default is used.
4. Temporarily provide `colors:=9` and observe that launch validation rejects
   it before the painter node starts.
