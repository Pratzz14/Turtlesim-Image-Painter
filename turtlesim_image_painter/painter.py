"""Timer-driven ROS 2 node for painting a complete image plan."""

from concurrent.futures import Future
from enum import auto, Enum
import signal
import sys
from threading import Thread
import time
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

from .image_processing import ImageProcessor
from .models import Color, PaintingPlan, Point
from .pipeline import PaintingPipeline
from .turtle_control import (
    alignment_command,
    angle_arrived,
    drive_command,
    heading_between,
    PainterConfig,
    position_arrived,
)


class PainterState(Enum):
    """Public execution states for a complete painting plan."""

    IDLE = auto()
    PREPARING = auto()
    MOVING_TO_STROKE = auto()
    ALIGNING = auto()
    PEN_DOWN = auto()
    DRAWING = auto()
    PEN_UP = auto()
    COLOR_CHANGE = auto()
    PARKING = auto()
    FINISHED = auto()
    ERROR = auto()


_PENDING = object()


class _DaemonPlanningWorker:
    """Run the single pipeline task without delaying interpreter shutdown."""

    def __init__(self) -> None:
        self._future = None

    def submit(self, function, *args, **kwargs):
        """Start one daemon task and expose its result as a Future."""
        if self._future is not None:
            raise RuntimeError('planning worker accepts only one task')
        future = Future()
        self._future = future

        def run() -> None:
            if not future.set_running_or_notify_cancel():
                return
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

        Thread(
            target=run,
            name='painting-plan',
            daemon=True,
        ).start()
        return future

    def shutdown(self, wait=False, cancel_futures=False) -> None:
        """Cancel work that has not started; daemon work never blocks exit."""
        if cancel_futures and self._future is not None:
            self._future.cancel()


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
    """Generate and execute one complete painting plan asynchronously."""

    def __init__(
        self,
        *,
        parameter_overrides=None,
        monotonic: Callable[[], float] = time.monotonic,
        pipeline=None,
        executor=None,
        context=None,
    ) -> None:
        """Declare configuration and create ROS and planning interfaces."""
        super().__init__(
            'painter',
            parameter_overrides=parameter_overrides,
            context=context,
        )
        self._monotonic = monotonic
        try:
            self.config = self._declare_config()
            if not self.config.image_path.strip():
                raise ValueError('image_path must not be empty')
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

        self._pipeline = pipeline or PaintingPipeline(
            processor=ImageProcessor(self.config.transparency_color),
            bounds=self.config.bounds,
            exclude_background=self.config.exclude_background,
        )
        self._owns_executor = executor is None
        self._executor = executor or _DaemonPlanningWorker()

        now = self._monotonic()
        self.state = PainterState.IDLE
        self.finished = False
        self.exit_code = 1
        self.failure_reason: Optional[str] = None
        self._pose: Optional[Pose] = None
        self._pose_time: Optional[float] = None
        self._pose_generation = 0
        self._teleport_pose_generation = 0
        self._parking_pose_generation = 0
        self._plan: Optional[PaintingPlan] = None
        self._planning_future = None
        self._future = None
        self._phase = ''
        self._stroke_index = 0
        self.completed_strokes = 0
        self._service_deadline = now
        self._pose_deadline = now
        self._state_deadline = now
        self._error_cleanup_started = False
        self._planner_closed = False
        self._timer = self.create_timer(
            1.0 / self.config.control_rate_hz, self._tick)
        self.get_logger().info('Painter ready to prepare image plan')

    def _declare_config(self) -> PainterConfig:
        """Declare all node parameters and return their validated snapshot."""
        values = {}
        for name, default in PainterConfig.defaults().items():
            if name == 'transparency_color':
                default = list(default)
            values[name] = self.declare_parameter(name, default).value
        return PainterConfig.from_mapping(values)

    def _pose_callback(self, pose: Pose) -> None:
        """Record the freshest turtle pose without advancing execution."""
        self._pose = pose
        self._pose_time = self._monotonic()
        self._pose_generation += 1

    def _pose_is_fresh(self) -> bool:
        """Return whether a recent pose sample is available."""
        return (
            self._pose is not None
            and self._pose_time is not None
            and self._monotonic() - self._pose_time
            <= self.config.pose_timeout_sec
        )

    def _services_ready(self) -> bool:
        """Return whether services required by the current plan are ready."""
        ready = (
            self._pen_client.service_is_ready()
            and self._teleport_client.service_is_ready()
            and self._clear_client.service_is_ready()
            and self._parameter_client.services_are_ready()
        )
        return ready

    @property
    def _current_stroke(self):
        """Return the stroke currently being executed."""
        return self._plan.strokes[self._stroke_index]

    def _transition(self, state: PainterState) -> None:
        """Enter a state and reset state-local asynchronous bookkeeping."""
        self.state = state
        self._phase = ''
        self._future = None
        now = self._monotonic()
        if state in (PainterState.ALIGNING, PainterState.DRAWING):
            self._state_deadline = now + self.config.movement_timeout_sec
        elif state == PainterState.COLOR_CHANGE:
            self._state_deadline = now + self.config.color_change_pause_sec
        else:
            self._state_deadline = now + self.config.service_timeout_sec
        self.get_logger().info('Painter state: %s' % state.name.lower())

    def _start_service(self, operation: str, start: Callable[[], object]) -> bool:
        """Start and track a service request, normalizing sync failures."""
        try:
            future = start()
        except Exception as error:
            self._fail(f'{operation} failed: {error}')
            return False
        if future is None:
            self._fail(f'{operation} did not create a service request')
            return False
        self._future = future
        self._state_deadline = (
            self._monotonic() + self.config.service_timeout_sec)
        return True

    def _service_result(self, operation: str):
        """Return a response, a pending sentinel, or enter safe error state."""
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

    def _pen_request(self, off: bool, color: Optional[Color] = None):
        """Build a pen request for a stroke or a safe pen-off fallback."""
        selected = color or Color(0, 0, 0)
        request = SetPen.Request()
        request.r = selected.red
        request.g = selected.green
        request.b = selected.blue
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

    def _submit_pipeline(self) -> bool:
        """Submit image processing without touching ROS from the worker."""
        try:
            self._planning_future = self._executor.submit(
                self._pipeline.run,
                self.config.image_path,
                max_width=self.config.max_width,
                max_height=self.config.max_height,
                palette_size=self.config.palette_size,
                background_threshold=self.config.background_threshold,
                background_tolerance=self.config.background_tolerance,
                allow_upscale=self.config.allow_upscale,
                stroke_orientation=self.config.stroke_orientation,
                color_order=self.config.color_order,
                path_order=self.config.path_order,
                plan_output=self.config.plan_output or None,
                preview_output=self.config.preview_output or None,
            )
        except Exception as error:
            self._fail(f'starting painting pipeline failed: {error}')
            return False
        return True

    def _tick_preparing(self) -> None:
        """Poll planning, readiness, and the asynchronous setup sequence."""
        if self._phase == '':
            if self._submit_pipeline():
                self._phase = 'planning'
            return

        if self._phase == 'planning':
            if not self._planning_future.done():
                return
            try:
                result = self._planning_future.result()
            except Exception as error:
                self._fail(f'painting pipeline failed: {error}')
                return
            if result is None or getattr(result, 'plan_result', None) is None:
                self._fail('painting pipeline returned no plan')
                return
            self._plan = result.plan_result.plan
            now = self._monotonic()
            self._service_deadline = now + self.config.service_timeout_sec
            self._pose_deadline = now + self.config.pose_timeout_sec
            self._phase = 'waiting'
            self.get_logger().info(
                'Prepared %d strokes' % len(self._plan.strokes))
            return

        if self._phase == 'waiting':
            now = self._monotonic()
            if not self._services_ready():
                if now >= self._service_deadline:
                    self._fail(
                        'required turtlesim services were not available in time')
                return
            if self._plan.strokes and not self._pose_is_fresh():
                if now >= self._pose_deadline:
                    self._fail('initial turtle pose was not available in time')
                return
            color = self._plan.strokes[0].color if self._plan.strokes else None
            if self._start_service(
                'turning pen off',
                lambda: self._pen_client.call_async(
                    self._pen_request(True, color)),
            ):
                self._phase = 'pen_off'
            return

        if self._phase == 'pen_off':
            if self._service_result('turning pen off') is _PENDING:
                return
            parameters = [
                Parameter('background_r', value=self.config.background_r),
                Parameter('background_g', value=self.config.background_g),
                Parameter('background_b', value=self.config.background_b),
            ]
            if self._start_service(
                'setting background parameters',
                lambda: self._parameter_client.set_parameters(parameters),
            ):
                self._phase = 'background'
            return

        if self._phase == 'background':
            result = self._service_result('setting background parameters')
            if result is _PENDING:
                return
            results = getattr(result, 'results', ())
            if len(results) != 3 or not all(item.successful for item in results):
                reasons = [
                    item.reason for item in results if not item.successful
                ]
                detail = '; '.join(filter(None, reasons))
                self._fail(
                    'setting background parameters failed: '
                    + (detail or 'parameter rejected'))
                return
            if self._start_service(
                'clearing canvas',
                lambda: self._clear_client.call_async(Empty.Request()),
            ):
                self._phase = 'clear'
            return

        if self._phase == 'clear':
            if self._service_result('clearing canvas') is _PENDING:
                return
        if not self._plan.strokes:
            self._transition(PainterState.PARKING)
            return
        self._transition(PainterState.MOVING_TO_STROKE)

    def _tick_moving_to_stroke(self) -> None:
        """Teleport with the pen raised and confirm the target pose."""
        target = self._current_stroke.start
        if self._phase == '':
            if not self._require_fresh_pose('moving to stroke'):
                return
            current = Point(self._pose.x, self._pose.y)
            if position_arrived(
                current, target, self.config.position_tolerance,
            ):
                self._transition(PainterState.ALIGNING)
                return
            request = TeleportAbsolute.Request()
            request.x = target.x
            request.y = target.y
            request.theta = self._pose.theta
            self._teleport_pose_generation = self._pose_generation
            if self._start_service(
                'teleporting turtle',
                lambda: self._teleport_client.call_async(request),
            ):
                self._phase = 'teleport'
            return

        if self._phase == 'teleport':
            if self._service_result('teleporting turtle') is _PENDING:
                return
            self._phase = 'pose'
            self._state_deadline = (
                self._monotonic() + self.config.pose_timeout_sec)

        if (
            self._pose_generation > self._teleport_pose_generation
            and self._pose_is_fresh()
            and position_arrived(
                Point(self._pose.x, self._pose.y),
                target,
                self.config.position_tolerance,
            )
        ):
            self._transition(PainterState.ALIGNING)
        elif self._monotonic() >= self._state_deadline:
            self._fail('post-teleport pose was not available in time')

    def _tick_aligning(self) -> None:
        """Rotate toward the current stroke using pose feedback."""
        if self._monotonic() >= self._state_deadline:
            self._fail('alignment movement timed out')
            return
        if not self._require_fresh_pose('aligning'):
            return
        target = heading_between(
            self._current_stroke.start, self._current_stroke.end)
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

    def _tick_pen_down(self) -> None:
        """Enable the current color, unless this is a dry run."""
        if self.config.dry_run:
            self._transition(PainterState.DRAWING)
            return
        if self._phase == '':
            if self._start_service(
                'turning pen on',
                lambda: self._pen_client.call_async(
                    self._pen_request(False, self._current_stroke.color)),
            ):
                self._phase = 'service'
            return
        if self._service_result('turning pen on') is not _PENDING:
            self._transition(PainterState.DRAWING)

    def _tick_drawing(self) -> None:
        """Drive visibly to the current stroke endpoint."""
        if self._monotonic() >= self._state_deadline:
            self._fail('drawing movement timed out')
            return
        if not self._require_fresh_pose('drawing'):
            return
        current = Point(self._pose.x, self._pose.y)
        target = self._current_stroke.end
        if position_arrived(
            current, target, self.config.position_tolerance,
        ):
            self.publish_stop()
            self._transition(PainterState.PEN_UP)
            return
        command = drive_command(
            current,
            self._pose.theta,
            target,
            self.config.linear_gain,
            self.config.angular_gain,
            self.config.max_linear_speed,
            self.config.max_angular_speed,
        )
        self._publish_velocity(command.linear, command.angular)

    def _advance_stroke(self) -> None:
        """Record completion and select the next layer or terminal state."""
        previous_color = self._current_stroke.color
        self.completed_strokes += 1
        self._stroke_index += 1
        if self._stroke_index >= len(self._plan.strokes):
            self._transition(PainterState.PARKING)
            return
        if self._current_stroke.color != previous_color:
            self._transition(PainterState.COLOR_CHANGE)
        else:
            self._transition(PainterState.MOVING_TO_STROKE)

    def _tick_pen_up(self) -> None:
        """Raise the pen after one stroke and advance the plan."""
        if self.config.dry_run:
            self._advance_stroke()
            return
        if self._phase == '':
            if self._start_service(
                'turning pen off',
                lambda: self._pen_client.call_async(
                    self._pen_request(True, self._current_stroke.color)),
            ):
                self._phase = 'service'
            return
        if self._service_result('turning pen off') is not _PENDING:
            self._advance_stroke()

    def _tick_color_change(self) -> None:
        """Pause without blocking before beginning the next color layer."""
        if self._monotonic() >= self._state_deadline:
            self._transition(PainterState.MOVING_TO_STROKE)

    def _tick_parking(self) -> None:
        """Teleport the pen-up turtle out of the completed painting."""
        target = Point(self.config.parking_x, self.config.parking_y)
        if self._phase == '':
            request = TeleportAbsolute.Request()
            request.x = target.x
            request.y = target.y
            request.theta = 0.0
            self._parking_pose_generation = self._pose_generation
            if self._start_service(
                'parking turtle',
                lambda: self._teleport_client.call_async(request),
            ):
                self._phase = 'teleport'
            return

        if self._phase == 'teleport':
            if self._service_result('parking turtle') is _PENDING:
                return
            self._phase = 'pose'
            self._state_deadline = (
                self._monotonic() + self.config.pose_timeout_sec)

        if (
            self._pose_generation > self._parking_pose_generation
            and self._pose_is_fresh()
            and position_arrived(
                Point(self._pose.x, self._pose.y),
                target,
                self.config.position_tolerance,
            )
        ):
            if self._plan.strokes:
                message = 'Painting completed and turtle parked successfully'
            else:
                message = 'Empty painting plan completed and turtle parked successfully'
            self._succeed(message)
        elif self._monotonic() >= self._state_deadline:
            self._fail('parked turtle pose was not available in time')

    def _tick(self) -> None:
        """Advance the complete non-blocking state machine by one tick."""
        if self.finished:
            return
        if self.state == PainterState.IDLE:
            self.publish_stop()
            self._transition(PainterState.PREPARING)
        elif self.state == PainterState.PREPARING:
            self._tick_preparing()
        elif self.state == PainterState.MOVING_TO_STROKE:
            self._tick_moving_to_stroke()
        elif self.state == PainterState.ALIGNING:
            self._tick_aligning()
        elif self.state == PainterState.PEN_DOWN:
            self._tick_pen_down()
        elif self.state == PainterState.DRAWING:
            self._tick_drawing()
        elif self.state == PainterState.PEN_UP:
            self._tick_pen_up()
        elif self.state == PainterState.COLOR_CHANGE:
            self._tick_color_change()
        elif self.state == PainterState.PARKING:
            self._tick_parking()
        elif self.state == PainterState.ERROR:
            self._tick_error()

    def _fail(self, reason: str) -> None:
        """Stop immediately and enter bounded best-effort cleanup."""
        if self.finished or self.state == PainterState.ERROR:
            return
        self.failure_reason = reason
        self.get_logger().error(reason)
        if self._future is not None and not self._future.done():
            self._future.cancel()
        if (
            self._planning_future is not None
            and not self._planning_future.done()
        ):
            self._planning_future.cancel()
        self.publish_stop()
        self.state = PainterState.ERROR
        self._phase = ''
        self._future = None
        self._error_cleanup_started = False
        self._state_deadline = (
            self._monotonic() + self.config.service_timeout_sec)
        self._shutdown_planner()

    def _tick_error(self) -> None:
        """Attempt one bounded pen-off request, then finish in ERROR."""
        if not self._error_cleanup_started:
            self._error_cleanup_started = True
            if not self._pen_client.service_is_ready():
                self._finish_failure()
                return
            color = None
            if self._plan is not None and self._plan.strokes:
                stroke_index = min(
                    self._stroke_index,
                    len(self._plan.strokes) - 1,
                )
                color = self._plan.strokes[stroke_index].color
            try:
                self._future = self._pen_client.call_async(
                    self._pen_request(True, color))
            except Exception as error:
                self.get_logger().error(
                    'pen-off cleanup failed: %s' % error)
                self._finish_failure()
                return
            if self._future is None:
                self.get_logger().error(
                    'pen-off cleanup did not create a service request')
                self._finish_failure()
                return
            self._state_deadline = (
                self._monotonic() + self.config.service_timeout_sec)
            return
        if self._future.done() or self._monotonic() >= self._state_deadline:
            if not self._future.done():
                self._future.cancel()
            self._finish_failure()

    def _succeed(self, message: str) -> None:
        """Stop and terminate successfully in FINISHED."""
        self.publish_stop()
        self.state = PainterState.FINISHED
        self.finished = True
        self.exit_code = 0
        self._timer.cancel()
        self._shutdown_planner()
        self.get_logger().info(message)

    def _finish_failure(self) -> None:
        """Publish a final stop and terminate while remaining in ERROR."""
        self.publish_stop()
        self.finished = True
        self.exit_code = 1
        self._timer.cancel()
        self._shutdown_planner()

    def _shutdown_planner(self) -> None:
        """Cancel pending planning and release the owned worker once."""
        if self._planner_closed:
            return
        self._planner_closed = True
        if (
            self._planning_future is not None
            and not self._planning_future.done()
        ):
            self._planning_future.cancel()
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def destroy_node(self):
        """Release the planning worker before destroying ROS resources."""
        if hasattr(self, '_planner_closed'):
            self._shutdown_planner()
        return super().destroy_node()

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
