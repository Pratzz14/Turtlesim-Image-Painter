"""Tests for the one-shot ROS 2 painter state machine."""

import signal
from types import SimpleNamespace

import pytest

from rclpy.context import Context
from rclpy.exceptions import InvalidParameterTypeException
from rclpy.parameter import Parameter
from rclpy.signals import SignalHandlerOptions

from turtlesim.msg import Pose

from turtlesim_image_painter import painter
from turtlesim_image_painter.painter import PainterNode, PainterState
from turtlesim_image_painter.turtle_control import PainterConfig


class _FakeClock:
    """Controllable monotonic clock for timeout tests."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _FakeFuture:
    """Minimal completed or pending rclpy-future replacement."""

    def __init__(self, result=None, error=None, done=True):
        self._result = result
        self._error = error
        self._done = done
        self.cancelled = False

    def done(self):
        return self._done

    def result(self):
        if self._error is not None:
            raise self._error
        return self._result

    def cancel(self):
        self.cancelled = True


class _FakeClient:
    """Ready service client that records requests and returns fake futures."""

    def __init__(self, name, events, futures=None, ready=True):
        self.name = name
        self.events = events
        self.futures = list(futures or [])
        self.ready = ready

    def service_is_ready(self):
        return self.ready

    def call_async(self, request):
        event = self.name
        if self.name == 'pen':
            event = 'pen_off' if request.off else 'pen_down'
        self.events.append(event)
        if self.futures:
            return self.futures.pop(0)
        return _FakeFuture(result=SimpleNamespace())


class _FakeParameterClient:
    """Ready background client with configurable result."""

    def __init__(self, events, future=None, ready=True):
        self.events = events
        self.future = future or _FakeFuture(result=SimpleNamespace(results=[
            SimpleNamespace(successful=True, reason='') for _ in range(3)
        ]))
        self.ready = ready
        self.parameters = None

    def services_are_ready(self):
        return self.ready

    def set_parameters(self, parameters):
        self.events.append('background')
        self.parameters = parameters
        return self.future


class _FakePublisher:
    """Capture velocity messages and their place in the event stream."""

    def __init__(self, events):
        self.events = events
        self.messages = []

    def publish(self, message):
        self.messages.append(message)
        if message.linear.x != 0.0:
            self.events.append('draw')
        elif message.angular.z != 0.0:
            self.events.append('align')
        else:
            self.events.append('stop')


@pytest.fixture
def ros_context():
    """Provide an isolated rclpy context for node construction."""
    context = Context()
    context.init(args=[], initialize_logging=False)
    try:
        yield context
    finally:
        if context.ok():
            context.shutdown()


def make_node(clock, events, context):
    """Create a painter and replace its external interfaces with fakes."""
    node = PainterNode(monotonic=clock, context=context)
    node._velocity_publisher = _FakePublisher(events)
    node._pen_client = _FakeClient('pen', events)
    node._teleport_client = _FakeClient('teleport', events)
    node._clear_client = _FakeClient('clear', events)
    node._parameter_client = _FakeParameterClient(events)
    return node


def pose(x, y, theta=0.0):
    """Build a turtlesim pose for direct callback delivery."""
    message = Pose()
    message.x = x
    message.y = y
    message.theta = theta
    return message


def tick_service(node):
    """Start and then complete the current immediate service future."""
    node._tick()
    node._tick()


def test_node_declares_every_supported_parameter(ros_context):
    """ROS parameters exactly cover the validated configuration contract."""
    node = PainterNode(context=ros_context)
    try:
        declared = set(node.list_parameters([], depth=1).names)
        assert set(PainterConfig.defaults()) <= declared
        assert node.get_parameter('start_x').value == 2.0
        assert node.get_parameter('line_r').value == 255
    finally:
        node.destroy_node()


def test_invalid_ros_parameter_override_rejects_node(ros_context):
    """Cross-field validation also applies to ROS launch overrides."""
    overrides = [
        Parameter('start_x', value=4.0),
        Parameter('end_x', value=4.0),
    ]

    with pytest.raises(ValueError, match='different'):
        PainterNode(parameter_overrides=overrides, context=ros_context)


def test_successful_services_and_pose_feedback_draw_in_order(ros_context):
    """The complete one-line sequence uses feedback and finishes safely."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context)
    try:
        node._pose_callback(pose(5.5, 5.5, theta=0.5))
        node._tick()
        assert node.state == PainterState.BACKGROUND

        tick_service(node)
        tick_service(node)
        tick_service(node)
        tick_service(node)
        assert node.state == PainterState.WAIT_TELEPORT_POSE

        node._pose_callback(pose(2.0, 5.5, theta=0.5))
        node._tick()
        node._tick()
        assert events[-1] == 'align'

        node._pose_callback(pose(2.0, 5.5, theta=0.0))
        node._tick()
        assert node.state == PainterState.PEN_DOWN
        tick_service(node)

        node._pose_callback(pose(2.0, 5.5, theta=0.0))
        node._tick()
        assert events[-1] == 'draw'
        node._pose_callback(pose(9.0, 5.5, theta=0.0))
        node._tick()
        tick_service(node)

        assert node.finished
        assert node.exit_code == 0
        assert events == [
            'background', 'clear', 'pen_off', 'teleport',
            'align', 'stop', 'pen_down', 'draw', 'stop',
            'pen_off', 'stop',
        ]
        assert all(
            parameter.value == 255
            for parameter in node._parameter_client.parameters
        )
        assert node._velocity_publisher.messages[-1].linear.x == 0.0
        assert node._velocity_publisher.messages[-1].angular.z == 0.0
    finally:
        node.destroy_node()


def test_rejected_background_parameters_stop_and_raise_pen(ros_context):
    """A rejected async operation enters safe bounded cleanup."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context)
    node._parameter_client = _FakeParameterClient(
        events,
        future=_FakeFuture(result=SimpleNamespace(results=[
            SimpleNamespace(successful=True, reason=''),
            SimpleNamespace(successful=False, reason='read only'),
            SimpleNamespace(successful=True, reason=''),
        ])),
    )
    try:
        node._pose_callback(pose(5.5, 5.5))
        node._tick()
        tick_service(node)

        assert node.state == PainterState.CLEANUP
        assert 'read only' in node.failure_reason
        node._tick()
        node._tick()
        assert node.finished
        assert node.exit_code == 1
        assert events == ['background', 'stop', 'pen_off', 'stop']
    finally:
        node.destroy_node()


def test_service_exception_stops_and_attempts_pen_cleanup(ros_context):
    """A future exception cannot leave the turtle moving or drawing."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context)
    node._clear_client = _FakeClient(
        'clear', events,
        futures=[_FakeFuture(error=RuntimeError('service broke'))],
    )
    try:
        node._pose_callback(pose(5.5, 5.5))
        node._tick()
        tick_service(node)
        tick_service(node)

        assert node.state == PainterState.CLEANUP
        node._tick()
        node._tick()
        assert node.finished
        assert 'service broke' in node.failure_reason
        assert events[-2:] == ['pen_off', 'stop']
    finally:
        node.destroy_node()


def test_service_availability_timeout_stops_safely(ros_context):
    """Missing services terminate rather than waiting indefinitely."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context)
    node._clear_client.ready = False
    try:
        node._pose_callback(pose(5.5, 5.5))
        clock.now = node.config.service_timeout_sec
        node._tick()
        assert node.state == PainterState.CLEANUP
        node._tick()
        node._tick()
        assert node.finished
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_stale_pose_during_draw_stops_and_raises_pen(ros_context):
    """Motion aborts safely when pose feedback stops arriving."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context)
    try:
        node.state = PainterState.DRAW
        node._pose_callback(pose(3.0, 5.5))
        clock.now = node.config.pose_timeout_sec + 0.01
        node._tick()

        assert node.state == PainterState.CLEANUP
        assert events[-1] == 'stop'
        node._tick()
        node._tick()
        assert node.finished
        assert events[-2:] == ['pen_off', 'stop']
    finally:
        node.destroy_node()


def test_pending_service_response_times_out_and_is_cancelled(ros_context):
    """An accepted request cannot hang the one-shot process forever."""
    clock = _FakeClock()
    events = []
    pending = _FakeFuture(done=False)
    node = make_node(clock, events, ros_context)
    node._clear_client = _FakeClient('clear', events, futures=[pending])
    try:
        node.state = PainterState.CLEAR
        node._tick()
        clock.now = node.config.service_timeout_sec
        node._tick()

        assert pending.cancelled
        assert node.state == PainterState.CLEANUP
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_main_reports_wrong_typed_ros_parameter_without_traceback(
    monkeypatch, capsys,
):
    """ROS parameter type errors become clean configuration failures."""
    expected = Parameter.Type.INTEGER
    error = InvalidParameterTypeException(
        Parameter('line_r', value='oops'), expected)

    def reject_parameters():
        raise error

    context_ok = True
    monkeypatch.setattr(painter.rclpy, 'init', lambda **kwargs: None)
    monkeypatch.setattr(painter.rclpy, 'ok', lambda: context_ok)
    monkeypatch.setattr(painter.rclpy, 'shutdown', lambda: None)
    monkeypatch.setattr(painter, 'PainterNode', reject_parameters)

    assert painter.main([]) == 1
    assert 'invalid painter configuration' in capsys.readouterr().err


def test_main_handles_sigint_before_shutting_down_ros(monkeypatch):
    """SIGINT cleanup publishes while the ROS context remains valid."""
    events = []
    initialized = {}
    context_ok = True

    class FakeMainNode:
        """Record the lifecycle operations performed by main."""

        def __init__(self):
            self.finished = False
            self.exit_code = 1
            self.config = SimpleNamespace(service_timeout_sec=1.0)

        def request_abort(self, reason):
            events.append(('abort', reason))

        def publish_stop(self):
            assert context_ok
            events.append('stop')

        def destroy_node(self):
            events.append('destroy')

    spin_count = 0

    def fake_init(**kwargs):
        initialized.update(kwargs)

    def fake_spin_once(node, timeout_sec):
        nonlocal spin_count
        spin_count += 1
        if spin_count == 1:
            signal.raise_signal(signal.SIGINT)
        else:
            node.finished = True

    def fake_shutdown():
        nonlocal context_ok
        events.append('shutdown')
        context_ok = False

    monkeypatch.setattr(painter, 'PainterNode', FakeMainNode)
    monkeypatch.setattr(painter.rclpy, 'init', fake_init)
    monkeypatch.setattr(painter.rclpy, 'ok', lambda: context_ok)
    monkeypatch.setattr(painter.rclpy, 'spin_once', fake_spin_once)
    monkeypatch.setattr(painter.rclpy, 'shutdown', fake_shutdown)

    assert painter.main([]) == 1
    assert initialized['signal_handler_options'] == SignalHandlerOptions.NO
    assert events[0][0] == 'abort'
    assert 'SIGINT' in events[0][1]
    assert events[1:] == ['stop', 'destroy', 'shutdown']
