"""One-shot ROS 2 node for drawing a horizontal turtlesim line."""

import signal
import sys
import time
from enum import Enum, auto
from typing import Callable, Optional, Sequence

from geometry_msgs.msg import Twist

import rclpy
from rclpy.exceptions import ParameterException
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.signals import SignalHandlerOptions

from std_srvs.srv import Empty

from turtlesim.msg import Pose
from turtlesim.srv import SetPen, TeleportAbsolute

from .models import Point
from .turtle_control import (
    PainterConfig,
    alignment_command,
    angle_arrived,
    drive_command,
    heading_between,
    position_arrived,
)


class PainterState(Enum):
    """Execution states for one horizontal line."""

    WAITING = auto()
    BACKGROUND = auto()
    CLEAR = auto()
    PEN_OFF_INITIAL = auto()
    TELEPORT = auto()
    WAIT_TELEPORT_POSE = auto()
    ALIGN = auto()
    PEN_DOWN = auto()
    DRAW = auto()
    PEN_OFF_FINAL = auto()
    CLEANUP = auto()
    DONE = auto()


_PENDING = object()


def _install_shutdown_signal_handlers(callback):
    """Install signal handlers, or return None outside the main thread."""
    previous = {}
    try:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            previous[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, callback)
    except ValueError:
        for signal_number, handler in previous.items():
            try:
                signal.signal(signal_number, handler)
            except ValueError:
                pass
        return None
    return previous


def _restore_signal_handlers(previous) -> None:
    """Restore handlers replaced by the painter entry point."""
    if previous is None:
        return
    for signal_number, handler in previous.items():
        signal.signal(signal_number, handler)


class PainterNode(Node):
    """Draw one configured line using pose feedback and async services."""

    def __init__(
        self,
        *,
        parameter_overrides=None,
        monotonic: Callable[[], float] = time.monotonic,
        context=None,
    ) -> None:
        """Declare configuration and create the ROS interfaces."""
        super().__init__(
            'painter',
            parameter_overrides=parameter_overrides,
            context=context,
        )
        self._monotonic = monotonic
        try:
            self.config = self._declare_config()
        except Exception:
            self.destroy_node()
            raise

        self._velocity_publisher = self.create_publisher(
            Twist, '/turtle1/cmd_vel', 10)
        self._pose_subscription = self.create_subscription(
            Pose, '/turtle1/pose', self._pose_callback, 10)
        self._pen_client = self.create_client(SetPen, '/turtle1/set_pen')
        self._teleport_client = self.create_client(
            TeleportAbsolute, '/turtle1/teleport_absolute')
        self._clear_client = self.create_client(Empty, '/clear')
        self._parameter_client = AsyncParameterClient(self, '/turtlesim')

        now = self._monotonic()
        self.state = PainterState.WAITING
        self.finished = False
        self.exit_code = 1
        self.failure_reason: Optional[str] = None
        self._pose: Optional[Pose] = None
        self._pose_time: Optional[float] = None
        self._pose_generation = 0
        self._teleport_pose_generation = 0
        self._service_deadline = now + self.config.service_timeout_sec
        self._pose_deadline = now + self.config.pose_timeout_sec
        self._state_deadline = now
        self._future = None
        self._entered = False
        self._timer = self.create_timer(
            1.0 / self.config.control_rate_hz, self._tick)
        self.get_logger().info('Waiting for turtlesim services and pose')

    def _declare_config(self) -> PainterConfig:
        """Declare all node parameters and return their validated snapshot."""
        values = {}
        for name, default in PainterConfig.defaults().items():
            values[name] = self.declare_parameter(name, default).value
        return PainterConfig.from_mapping(values)

    def _pose_callback(self, pose: Pose) -> None:
        """Record the freshest turtle pose."""
        self._pose = pose
        self._pose_time = self._monotonic()
        self._pose_generation += 1

    def _services_ready(self) -> bool:
        """Return whether every required service endpoint is available."""
        return (
            self._pen_client.service_is_ready()
            and self._teleport_client.service_is_ready()
            and self._clear_client.service_is_ready()
            and self._parameter_client.services_are_ready()
        )

    def _pose_is_fresh(self) -> bool:
        """Return whether a recently received pose is available."""
        return (
            self._pose is not None
            and self._pose_time is not None
            and self._monotonic() - self._pose_time
            <= self.config.pose_timeout_sec
        )

    def _transition(self, state: PainterState) -> None:
        """Enter a new state and reset its asynchronous bookkeeping."""
        self.state = state
        self._entered = False
        self._future = None
        self._state_deadline = (
            self._monotonic() + self.config.service_timeout_sec)
        self.get_logger().info('Painter state: %s' % state.name.lower())

    def _start_future(self, future) -> None:
        """Track one asynchronous service operation."""
        self._future = future
        self._entered = True
        self._state_deadline = (
            self._monotonic() + self.config.service_timeout_sec)

    def _future_result(self, operation: str):
        """Return a completed result, a pending sentinel, or start cleanup."""
        if self._future is None:
            self._fail(f'{operation} did not create a service request')
            return _PENDING
        if not self._future.done():
            if self._monotonic() >= self._state_deadline:
                self._future.cancel()
                self._fail(f'{operation} timed out')
            return _PENDING
        try:
            result = self._future.result()
        except Exception as error:
            self._fail(f'{operation} failed: {error}')
            return _PENDING
        if result is None:
            self._fail(f'{operation} returned no response')
            return _PENDING
        return result

    def _pen_request(self, off: bool):
        """Build a pen request using the configured line appearance."""
        request = SetPen.Request()
        request.r = self.config.line_r
        request.g = self.config.line_g
        request.b = self.config.line_b
        request.width = self.config.pen_width
        request.off = int(off)
        return request

    def _publish_velocity(
        self,
        linear: float = 0.0,
        angular: float = 0.0,
    ) -> None:
        """Publish one planar velocity command."""
        message = Twist()
        message.linear.x = float(linear)
        message.angular.z = float(angular)
        self._velocity_publisher.publish(message)

    def publish_stop(self) -> None:
        """Publish an explicit zero velocity command."""
        self._publish_velocity()

    def _require_fresh_pose(self, operation: str) -> bool:
        """Fail a motion state when pose feedback has gone stale."""
        if self._pose_is_fresh():
            return True
        self._fail(f'pose feedback unavailable while {operation}')
        return False

    def _tick_waiting(self) -> None:
        """Wait concurrently for service discovery and initial pose."""
        now = self._monotonic()
        services_ready = self._services_ready()
        pose_ready = self._pose_is_fresh()
        if not services_ready and now >= self._service_deadline:
            self._fail(
                'required turtlesim services were not available in time')
            return
        if not pose_ready and now >= self._pose_deadline:
            self._fail('initial turtle pose was not available in time')
            return
        if services_ready and pose_ready:
            self._transition(PainterState.BACKGROUND)

    def _tick_background(self) -> None:
        """Set the Turtlesim background parameters."""
        if not self._entered:
            parameters = [
                Parameter('background_r', value=self.config.background_r),
                Parameter('background_g', value=self.config.background_g),
                Parameter('background_b', value=self.config.background_b),
            ]
            self._start_future(
                self._parameter_client.set_parameters(parameters))
            return
        result = self._future_result('setting background parameters')
        if result is _PENDING:
            return
        results = getattr(result, 'results', ())
        if len(results) != 3 or not all(item.successful for item in results):
            reasons = [item.reason for item in results if not item.successful]
            detail = '; '.join(filter(None, reasons)) or 'parameter rejected'
            self._fail(f'setting background parameters failed: {detail}')
            return
        self._transition(PainterState.CLEAR)

    def _tick_simple_service(
        self,
        operation: str,
        start: Callable[[], object],
        next_state: PainterState,
    ) -> None:
        """Run an empty-response async service state."""
        if not self._entered:
            self._start_future(start())
            return
        if self._future_result(operation) is not _PENDING:
            self._transition(next_state)

    def _tick_teleport(self) -> None:
        """Teleport to the start while preserving the current heading."""
        if not self._entered:
            request = TeleportAbsolute.Request()
            request.x = self.config.start_x
            request.y = self.config.line_y
            request.theta = self._pose.theta
            self._start_future(self._teleport_client.call_async(request))
            return
        if self._future_result('teleporting turtle') is not _PENDING:
            self._teleport_pose_generation = self._pose_generation
            self._transition(PainterState.WAIT_TELEPORT_POSE)
            self._state_deadline = (
                self._monotonic() + self.config.pose_timeout_sec)

    def _tick_wait_teleport_pose(self) -> None:
        """Confirm teleport completion with a newer pose sample."""
        if (
            self._pose_generation > self._teleport_pose_generation
            and self._pose_is_fresh()
            and position_arrived(
                Point(self._pose.x, self._pose.y),
                self.config.start,
                self.config.position_tolerance,
            )
        ):
            self._transition(PainterState.ALIGN)
            return
        if self._monotonic() >= self._state_deadline:
            self._fail('post-teleport pose was not available in time')

    def _tick_align(self) -> None:
        """Rotate to the line heading using pose feedback."""
        if not self._require_fresh_pose('aligning'):
            return
        target = heading_between(self.config.start, self.config.end)
        if angle_arrived(
            self._pose.theta, target, self.config.angle_tolerance,
        ):
            self.publish_stop()
            self._transition(PainterState.PEN_DOWN)
            return
        command = alignment_command(
            self._pose.theta,
            target,
            self.config.angular_gain,
            self.config.max_angular_speed,
        )
        self._publish_velocity(command.linear, command.angular)

    def _tick_draw(self) -> None:
        """Drive to the line endpoint using fresh pose feedback."""
        if not self._require_fresh_pose('drawing'):
            return
        current = Point(self._pose.x, self._pose.y)
        if position_arrived(
            current, self.config.end, self.config.position_tolerance,
        ):
            self.publish_stop()
            self._transition(PainterState.PEN_OFF_FINAL)
            return
        command = drive_command(
            current,
            self._pose.theta,
            self.config.end,
            self.config.linear_gain,
            self.config.angular_gain,
            self.config.max_linear_speed,
            self.config.max_angular_speed,
        )
        self._publish_velocity(command.linear, command.angular)

    def _tick_cleanup(self) -> None:
        """Attempt bounded pen-off cleanup before a failed exit."""
        if not self._entered:
            if not self._pen_client.service_is_ready():
                self._finish_failure()
                return
            self._start_future(
                self._pen_client.call_async(self._pen_request(off=True)))
            return
        if self._future.done() or self._monotonic() >= self._state_deadline:
            if not self._future.done():
                self._future.cancel()
            self._finish_failure()

    def _tick(self) -> None:
        """Advance the non-blocking one-shot state machine."""
        if self.finished:
            return
        if self.state == PainterState.WAITING:
            self._tick_waiting()
        elif self.state == PainterState.BACKGROUND:
            self._tick_background()
        elif self.state == PainterState.CLEAR:
            self._tick_simple_service(
                'clearing canvas',
                lambda: self._clear_client.call_async(Empty.Request()),
                PainterState.PEN_OFF_INITIAL,
            )
        elif self.state == PainterState.PEN_OFF_INITIAL:
            self._tick_simple_service(
                'turning pen off',
                lambda: self._pen_client.call_async(
                    self._pen_request(off=True)),
                PainterState.TELEPORT,
            )
        elif self.state == PainterState.TELEPORT:
            self._tick_teleport()
        elif self.state == PainterState.WAIT_TELEPORT_POSE:
            self._tick_wait_teleport_pose()
        elif self.state == PainterState.ALIGN:
            self._tick_align()
        elif self.state == PainterState.PEN_DOWN:
            self._tick_simple_service(
                'turning pen on',
                lambda: self._pen_client.call_async(
                    self._pen_request(off=False)),
                PainterState.DRAW,
            )
        elif self.state == PainterState.DRAW:
            self._tick_draw()
        elif self.state == PainterState.PEN_OFF_FINAL:
            self._tick_simple_service(
                'turning pen off',
                lambda: self._pen_client.call_async(
                    self._pen_request(off=True)),
                PainterState.DONE,
            )
            if self.state == PainterState.DONE:
                self.publish_stop()
                self.finished = True
                self.exit_code = 0
                self.get_logger().info(
                    'Horizontal line completed successfully')
        elif self.state == PainterState.CLEANUP:
            self._tick_cleanup()

    def _fail(self, reason: str) -> None:
        """Stop motion and enter bounded failure cleanup."""
        if self.finished or self.state == PainterState.CLEANUP:
            return
        self.failure_reason = reason
        self.get_logger().error(reason)
        self.publish_stop()
        self._transition(PainterState.CLEANUP)

    def _finish_failure(self) -> None:
        """Finish a failed run after publishing another stop command."""
        self.publish_stop()
        self.state = PainterState.DONE
        self.finished = True
        self.exit_code = 1

    def request_abort(self, reason: str = 'painting interrupted') -> None:
        """Request safe termination from the main loop or a test."""
        self._fail(reason)


def main(arguments: Optional[Sequence[str]] = None) -> int:
    """Run the painter until its one-shot state machine completes."""
    shutdown_signal = None

    def request_shutdown(signal_number, _frame) -> None:
        """Latch a process signal for handling in the executor loop."""
        nonlocal shutdown_signal
        shutdown_signal = signal_number

    previous_handlers = _install_shutdown_signal_handlers(request_shutdown)
    signal_options = (
        SignalHandlerOptions.NO if previous_handlers is not None else None)
    initialized = False
    node = None
    exit_code = 1
    abort_deadline = None
    try:
        rclpy.init(args=arguments, signal_handler_options=signal_options)
        initialized = True
        node = PainterNode()
        while rclpy.ok() and not node.finished:
            if shutdown_signal is not None and abort_deadline is None:
                signal_name = signal.Signals(shutdown_signal).name
                node.request_abort(f'painting interrupted by {signal_name}')
                abort_deadline = (
                    time.monotonic() + node.config.service_timeout_sec)
            if (
                abort_deadline is not None
                and time.monotonic() >= abort_deadline
            ):
                break
            rclpy.spin_once(node, timeout_sec=0.1)
        exit_code = node.exit_code
    except (ParameterException, TypeError, ValueError) as error:
        print(
            f'Error: invalid painter configuration: {error}',
            file=sys.stderr,
        )
    except KeyboardInterrupt:
        if node is not None:
            node.request_abort()
            deadline = time.monotonic() + node.config.service_timeout_sec
            while (
                rclpy.ok()
                and not node.finished
                and time.monotonic() < deadline
            ):
                rclpy.spin_once(node, timeout_sec=0.1)
            exit_code = 1
    finally:
        if node is not None:
            if initialized and rclpy.ok():
                node.publish_stop()
            node.destroy_node()
        if initialized and rclpy.ok():
            rclpy.shutdown()
        _restore_signal_handlers(previous_handlers)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
