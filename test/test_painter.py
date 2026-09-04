# Copyright 2026 Pratik Mahankal
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""Tests for the complete ROS 2 painter state machine."""

from math import atan2
import signal
from types import SimpleNamespace

import pytest

from rclpy.context import Context
from rclpy.exceptions import InvalidParameterTypeException
from rclpy.parameter import Parameter
from rclpy.signals import SignalHandlerOptions

from turtlesim.msg import Pose

from turtlesim_image_painter import (
    Color,
    PaintingPlan,
    Point,
    Statistics,
    Stroke,
)
from turtlesim_image_painter import painter
from turtlesim_image_painter.painter import PainterNode, PainterState
from turtlesim_image_painter.turtle_control import PainterConfig


RED = Color(255, 0, 0)
BLUE = Color(0, 0, 255)


class _FakeClock:
    """Controllable monotonic clock for timeout tests."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _FakeFuture:
    """Minimal controllable future replacement."""

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

    def complete(self, result):
        self._result = result
        self._done = True


class _FakeExecutor:
    """Capture submitted pipeline work without starting a thread."""

    def __init__(self, future):
        self.future = future
        self.calls = []

    def submit(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return self.future


class _FakePipeline:
    """Pipeline placeholder whose call is owned by the fake executor."""

    def run(self, *args, **kwargs):
        raise AssertionError('fake executor must not invoke pipeline directly')


class _FakeClient:
    """Ready service client that records requests and returns fake futures."""

    def __init__(self, name, events, futures=None, ready=True):
        self.name = name
        self.events = events
        self.futures = list(futures or [])
        self.ready = ready
        self.requests = []

    def service_is_ready(self):
        return self.ready

    def call_async(self, request):
        self.requests.append(request)
        if self.name == 'pen':
            color = (request.r, request.g, request.b)
            event = ('pen_off' if request.off else 'pen_down', color)
        else:
            event = self.name
        self.events.append(event)
        if self.futures:
            return self.futures.pop(0)
        return _FakeFuture(result=SimpleNamespace())


class _RaisingClient(_FakeClient):
    """Service client that fails before returning a future."""

    def call_async(self, request):
        self.events.append(self.name + '_sync_failure')
        raise RuntimeError(self.name + ' start failed')


class _FakeParameterClient:
    """Ready background client with configurable results."""

    def __init__(self, events, futures=None, ready=True):
        self.events = events
        self.futures = list(futures or [])
        self.ready = ready
        self.parameters = None

    def services_are_ready(self):
        return self.ready

    def set_parameters(self, parameters):
        self.events.append('background')
        self.parameters = parameters
        if self.futures:
            return self.futures.pop(0)
        result = SimpleNamespace(results=[
            SimpleNamespace(successful=True, reason='') for _ in range(3)
        ])
        return _FakeFuture(result=result)


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


class _FakeLogger:
    """Capture informational and error messages for reporting tests."""

    def __init__(self):
        self.infos = []
        self.errors = []

    def info(self, message):
        """Record one informational message."""
        self.infos.append(message)

    def error(self, message):
        """Record one error message."""
        self.errors.append(message)


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


def pipeline_result(strokes, background=None):
    """Build the portion of PipelineResult consumed by PainterNode."""
    plan = PaintingPlan(
        tuple(strokes), width=2, height=2, background=background)
    colors = tuple(dict.fromkeys(stroke.color for stroke in strokes))
    palette = colors
    if background is not None and background not in palette:
        palette += (background,)
    skipped = 1 if background is not None else 0
    statistics = Statistics(
        pixel_count=4,
        palette_size=len(palette),
        stroke_count=len(strokes),
        skipped_pixels=skipped,
        color_counts=tuple((color, 1) for color in palette),
        paint_distance=float(len(strokes)),
        travel_distance=0.0,
        total_distance=float(len(strokes)),
    )
    processed = SimpleNamespace(
        width=2,
        height=2,
        palette=palette,
        background=background,
    )
    return SimpleNamespace(
        original_width=4,
        original_height=3,
        processed_image=processed,
        plan_result=SimpleNamespace(plan=plan, statistics=statistics),
        plan_path='/tmp/test_plan.json',
        preview_path='/tmp/test_preview.png',
    )


def make_node(clock, events, context, strokes, **changes):
    """Create a painter wired to deterministic fake dependencies."""
    pipeline_background = changes.pop('pipeline_background', None)
    options = {'image_path': '/tmp/test.png'}
    options.update(changes)
    overrides = [Parameter(name, value=value) for name, value in options.items()]
    plan_future = _FakeFuture(
        result=pipeline_result(strokes, pipeline_background))
    executor = _FakeExecutor(plan_future)
    node = PainterNode(
        parameter_overrides=overrides,
        monotonic=clock,
        pipeline=_FakePipeline(),
        executor=executor,
        context=context,
    )
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


def prepare(node, initial_pose=None):
    """Advance through planning and asynchronous canvas preparation."""
    if initial_pose is not None:
        node._pose_callback(initial_pose)
    for _ in range(7):
        node._tick()


def execute_current_stroke(node):
    """Teleport, align, draw, and raise the pen for one stroke."""
    stroke = node._current_stroke
    node._tick()
    assert node._phase == 'teleport'
    node._tick()
    node._pose_callback(pose(stroke.start.x, stroke.start.y, theta=0.4))
    node._tick()
    assert node.state == PainterState.ALIGNING
    heading = atan2(
        stroke.end.y - stroke.start.y,
        stroke.end.x - stroke.start.x,
    )
    node._pose_callback(pose(stroke.start.x, stroke.start.y, heading))
    node._tick()
    assert node.state == PainterState.PEN_DOWN
    if not node.config.dry_run:
        node._tick()
    node._tick()
    assert node.state == PainterState.DRAWING
    node._pose_callback(pose(stroke.start.x, stroke.start.y, heading))
    node._tick()
    node._pose_callback(pose(stroke.end.x, stroke.end.y, heading))
    node._tick()
    assert node.state == PainterState.PEN_UP
    if not node.config.dry_run:
        node._tick()
    node._tick()


def complete_parking(node):
    """Start parking, confirm its pose, and reach successful completion."""
    assert node.state == PainterState.PARKING
    node._tick()
    assert node._phase == 'teleport'
    request = node._teleport_client.requests[-1]
    assert (request.x, request.y, request.theta) == (
        node.config.parking_x,
        node.config.parking_y,
        0.0,
    )
    node._tick()
    assert node._phase == 'pose'
    assert not node.finished
    node._pose_callback(pose(node.config.parking_x, node.config.parking_y))
    node._tick()
    assert node.state == PainterState.FINISHED


def test_public_state_set_matches_sprint_contract():
    """The state enum exposes only the complete-painter states."""
    assert [state.name for state in PainterState] == [
        'IDLE', 'PREPARING', 'MOVING_TO_STROKE', 'ALIGNING',
        'PEN_DOWN', 'DRAWING', 'PEN_UP', 'COLOR_CHANGE',
        'PARKING', 'FINISHED', 'ERROR',
    ]


def test_node_declares_every_supported_parameter(ros_context):
    """ROS parameters exactly cover the validated configuration contract."""
    node = make_node(_FakeClock(), [], ros_context, [])
    try:
        declared = set(node.list_parameters([], depth=1).names)
        assert set(PainterConfig.defaults()) <= declared
        assert node.get_parameter('image_path').value == '/tmp/test.png'
        assert node.get_parameter('dry_run').value is False
    finally:
        node.destroy_node()


def test_empty_image_path_rejects_node(ros_context):
    """The painter requires an explicit source image."""
    with pytest.raises(ValueError, match='image_path'):
        PainterNode(context=ros_context)


def test_pending_pipeline_does_not_block_pose_callback(ros_context):
    """PREPARING only polls its worker future and remains callback-safe."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context, [])
    node._executor.future = _FakeFuture(done=False)
    try:
        node._tick()
        node._tick()
        node._tick()
        node._pose_callback(pose(3.0, 4.0))

        assert node.state == PainterState.PREPARING
        assert node._pose.x == 3.0
        assert events == ['stop']
        assert len(node._executor.calls) == 1
        _, args, kwargs = node._executor.calls[0]
        assert args == ('/tmp/test.png',)
        assert kwargs['max_width'] == 80
        assert kwargs['max_height'] == 80
        assert kwargs['palette_size'] == 4
        assert kwargs['background_tolerance'] == 24
        assert kwargs['stroke_orientation'] == 'auto'
        assert kwargs['plan_output'] is None
    finally:
        node.destroy_node()


def test_same_color_strokes_execute_without_layer_pause(ros_context):
    """Every stroke in one color is completed before changing layers."""
    strokes = [
        Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED),
        Stroke(Point(4.0, 5.0), Point(5.0, 5.0), RED),
    ]
    events = []
    node = make_node(_FakeClock(), events, ros_context, strokes)
    try:
        prepare(node, pose(5.5, 5.5))
        assert node.state == PainterState.MOVING_TO_STROKE
        execute_current_stroke(node)
        assert node.state == PainterState.MOVING_TO_STROKE
        execute_current_stroke(node)
        assert node.state == PainterState.PARKING
        complete_parking(node)

        assert node.state == PainterState.FINISHED
        assert node.finished
        assert node.exit_code == 0
        assert node.completed_strokes == 2
        assert [event for event in events if event == 'teleport'] == [
            'teleport', 'teleport', 'teleport',
        ]
        assert ('pen_down', RED.as_tuple()) in events
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_color_layer_transition_obeys_timer(ros_context):
    """A color change waits without sleeping before the next stroke."""
    clock = _FakeClock()
    strokes = [
        Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED),
        Stroke(Point(2.0, 6.0), Point(3.0, 6.0), BLUE),
    ]
    events = []
    node = make_node(clock, events, ros_context, strokes)
    try:
        prepare(node, pose(5.5, 5.5))
        execute_current_stroke(node)
        assert node.state == PainterState.COLOR_CHANGE

        clock.now = node.config.color_change_pause_sec - 0.01
        node._tick()
        assert node.state == PainterState.COLOR_CHANGE
        clock.now = node.config.color_change_pause_sec
        node._tick()
        assert node.state == PainterState.MOVING_TO_STROKE
        execute_current_stroke(node)
        assert node.state == PainterState.PARKING
        complete_parking(node)

        assert node.state == PainterState.FINISHED
        assert node.exit_code == 0
        assert node.completed_strokes == 2
        assert ('pen_down', BLUE.as_tuple()) in events
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_dry_run_executes_motion_without_enabling_pen(ros_context):
    """Dry run performs setup and motion while the pen remains disabled."""
    stroke = Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED)
    events = []
    node = make_node(
        _FakeClock(), events, ros_context, [stroke], dry_run=True)
    try:
        prepare(node, pose(5.5, 5.5))
        execute_current_stroke(node)
        assert node.state == PainterState.PARKING
        complete_parking(node)

        assert node.state == PainterState.FINISHED
        assert 'background' in events
        assert 'clear' in events
        assert 'teleport' in events
        assert 'draw' in events
        pen_events = [event for event in events if isinstance(event, tuple)]
        assert pen_events == [('pen_off', RED.as_tuple())]
    finally:
        node.destroy_node()


def test_detected_background_is_applied_before_clear(ros_context):
    """Excluded detected background replaces the configured canvas RGB."""
    detected = Color(12, 34, 56)
    events = []
    node = make_node(
        _FakeClock(),
        events,
        ros_context,
        [],
        pipeline_background=detected,
    )
    try:
        prepare(node)
        parameters = {
            parameter.name: parameter.value
            for parameter in node._parameter_client.parameters
        }

        assert parameters == {
            'background_r': 12,
            'background_g': 34,
            'background_b': 56,
        }
        assert events.index('background') < events.index('clear')
    finally:
        node.destroy_node()


def test_configured_background_is_used_when_exclusion_is_disabled(ros_context):
    """Painting background pixels keeps the explicitly configured canvas."""
    events = []
    node = make_node(
        _FakeClock(),
        events,
        ros_context,
        [],
        pipeline_background=Color(12, 34, 56),
        exclude_background=False,
        background_r=210,
        background_g=220,
        background_b=230,
    )
    try:
        prepare(node)
        parameters = {
            parameter.name: parameter.value
            for parameter in node._parameter_client.parameters
        }

        assert parameters == {
            'background_r': 210,
            'background_g': 220,
            'background_b': 230,
        }
    finally:
        node.destroy_node()


def test_progress_and_final_statistics_cover_complete_run(ros_context):
    """Successful painting logs every color, stroke, and final measurement."""
    clock = _FakeClock()
    strokes = [
        Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED),
        Stroke(Point(2.0, 6.0), Point(3.0, 6.0), BLUE),
    ]
    events = []
    logger = _FakeLogger()
    node = make_node(clock, events, ros_context, strokes)
    node.get_logger = lambda: logger
    try:
        prepare(node, pose(5.5, 5.5))
        execute_current_stroke(node)
        clock.now = node.config.color_change_pause_sec
        node._tick()
        execute_current_stroke(node)
        clock.now = 4.0
        complete_parking(node)

        color_logs = [
            message for message in logger.infos
            if message.startswith('Color ')
        ]
        stroke_logs = [
            message for message in logger.infos
            if message.startswith('Stroke ')
        ]
        final = next(
            message for message in logger.infos
            if message.startswith('Final painting statistics:')
        )

        assert len(color_logs) == 2
        assert 'Color 1/2: RGB(255, 0, 0)' in color_logs[0]
        assert 'Color 2/2: RGB(0, 0, 255)' in color_logs[1]
        assert len(stroke_logs) == 2
        assert 'Stroke 1/2 complete (50.0%)' in stroke_logs[0]
        assert 'Stroke 2/2 complete (100.0%)' in stroke_logs[1]
        assert 'original=4x3, processed=2x2' in final
        assert 'palette=2, painted=2, changes=1' in final
        assert 'Logical pixels: total=4, painted=4; strokes=2' in final
        assert 'paint=2.000, travel=0.000, total=2.000' in final
        assert 'Elapsed time: 4.000 seconds' in final
        assert 'Preview PNG: /tmp/test_preview.png' in final
    finally:
        node.destroy_node()


def test_empty_plan_prepares_canvas_and_parks_without_initial_pose(ros_context):
    """Zero strokes still park successfully without needing an initial pose."""
    events = []
    node = make_node(_FakeClock(), events, ros_context, [])
    try:
        prepare(node)
        assert node.state == PainterState.PARKING
        complete_parking(node)

        assert node.state == PainterState.FINISHED
        assert node.exit_code == 0
        assert events == [
            'stop', ('pen_off', (0, 0, 0)), 'background', 'clear',
            'teleport', 'stop',
        ]
    finally:
        node.destroy_node()


def test_parking_uses_configured_corner_and_requires_new_pose(ros_context):
    """Parking does not finish on stale feedback or the wrong position."""
    events = []
    node = make_node(
        _FakeClock(),
        events,
        ros_context,
        [],
        parking_x=0.75,
        parking_y=0.8,
    )
    try:
        node._plan = pipeline_result([]).plan_result.plan
        node.state = PainterState.PARKING
        node._pose_callback(pose(0.75, 0.8))

        node._tick()
        request = node._teleport_client.requests[-1]
        assert (request.x, request.y) == (0.75, 0.8)
        node._tick()
        assert node.state == PainterState.PARKING
        assert not node.finished

        node._pose_callback(pose(1.0, 1.0))
        node._tick()
        assert node.state == PainterState.PARKING

        node._pose_callback(pose(0.75, 0.8))
        node._tick()
        assert node.state == PainterState.FINISHED
        assert node.exit_code == 0
    finally:
        node.destroy_node()


def test_parking_pose_timeout_enters_error(ros_context):
    """A parking teleport must receive timely matching pose feedback."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context, [])
    try:
        node._plan = pipeline_result([]).plan_result.plan
        node.state = PainterState.PARKING
        node._tick()
        node._tick()
        clock.now = node.config.pose_timeout_sec
        node._tick()

        assert node.state == PainterState.ERROR
        assert 'parked turtle pose' in node.failure_reason
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_parking_failure_cleans_up_after_final_stroke(ros_context):
    """Cleanup safely reuses the last color after the stroke index advances."""
    events = []
    stroke = Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED)
    node = make_node(_FakeClock(), events, ros_context, [stroke])
    node._plan = pipeline_result([stroke]).plan_result.plan
    node._stroke_index = 1
    node.completed_strokes = 1
    node.state = PainterState.PARKING
    node._teleport_client = _FakeClient(
        'teleport',
        events,
        futures=[_FakeFuture(error=RuntimeError('parking broke'))],
    )
    try:
        node._tick()
        node._tick()
        assert node.state == PainterState.ERROR
        assert 'parking broke' in node.failure_reason

        node._tick()
        node._tick()
        assert node.finished
        assert node.exit_code == 1
        assert ('pen_off', RED.as_tuple()) in events
    finally:
        node.destroy_node()


@pytest.mark.parametrize(
    'state,reason',
    [
        (PainterState.ALIGNING, 'alignment movement timed out'),
        (PainterState.DRAWING, 'drawing movement timed out'),
    ],
)
def test_movement_deadline_enters_error(ros_context, state, reason):
    """Fresh pose cannot make a stuck movement state run forever."""
    clock = _FakeClock()
    stroke = Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED)
    events = []
    node = make_node(clock, events, ros_context, [stroke])
    try:
        node._plan = pipeline_result([stroke]).plan_result.plan
        node.state = state
        node._state_deadline = node.config.movement_timeout_sec
        node._pose_callback(pose(2.0, 5.0, theta=1.0))
        clock.now = node.config.movement_timeout_sec
        node._tick()

        assert node.state == PainterState.ERROR
        assert node.failure_reason == reason
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_pending_service_times_out_and_is_cancelled(ros_context):
    """An accepted service request cannot hang execution."""
    clock = _FakeClock()
    pending = _FakeFuture(done=False)
    events = []
    node = make_node(clock, events, ros_context, [])
    node._clear_client = _FakeClient(
        'clear', events, futures=[pending])
    try:
        for _ in range(6):
            node._tick()
        assert node._phase == 'clear'
        clock.now = node.config.service_timeout_sec
        node._tick()

        assert pending.cancelled
        assert node.state == PainterState.ERROR
        assert 'clearing canvas timed out' in node.failure_reason
    finally:
        node.destroy_node()


@pytest.mark.parametrize('operation', ['pen', 'teleport', 'clear'])
def test_failed_turtlesim_operation_enters_error(ros_context, operation):
    """Pen, teleport, and clear exceptions are unrecoverable."""
    clock = _FakeClock()
    events = []
    stroke = Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED)
    node = make_node(clock, events, ros_context, [stroke])
    failing = _FakeFuture(error=RuntimeError(operation + ' broke'))
    try:
        if operation == 'clear':
            node._clear_client = _FakeClient(
                'clear', events, futures=[failing])
            node._pose_callback(pose(5.5, 5.5))
            for _ in range(7):
                node._tick()
        else:
            node._plan = pipeline_result([stroke]).plan_result.plan
            node._pose_callback(pose(5.5, 5.5))
            if operation == 'teleport':
                node.state = PainterState.MOVING_TO_STROKE
                node._teleport_client = _FakeClient(
                    'teleport', events, futures=[failing])
            else:
                node.state = PainterState.PEN_DOWN
                node._pen_client = _FakeClient(
                    'pen', events, futures=[failing])
            node._tick()
            node._tick()

        assert node.state == PainterState.ERROR
        assert operation + ' broke' in node.failure_reason
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_synchronous_pen_failure_still_completes_safe_cleanup(ros_context):
    """A call_async exception cannot escape or leave cleanup unfinished."""
    stroke = Stroke(Point(2.0, 5.0), Point(3.0, 5.0), RED)
    events = []
    node = make_node(_FakeClock(), events, ros_context, [stroke])
    node._plan = pipeline_result([stroke]).plan_result.plan
    node.state = PainterState.PEN_UP
    node._pen_client = _RaisingClient('pen', events)
    try:
        node._tick()
        assert node.state == PainterState.ERROR
        assert 'pen start failed' in node.failure_reason
        assert events[-1] == 'stop'

        node._tick()
        assert node.state == PainterState.ERROR
        assert node.finished
        assert node.exit_code == 1
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_rejected_background_parameters_enter_error(ros_context):
    """A rejected parameter result safely aborts preparation."""
    clock = _FakeClock()
    events = []
    rejected = SimpleNamespace(results=[
        SimpleNamespace(successful=True, reason=''),
        SimpleNamespace(successful=False, reason='read only'),
        SimpleNamespace(successful=True, reason=''),
    ])
    node = make_node(clock, events, ros_context, [])
    node._parameter_client = _FakeParameterClient(
        events, futures=[_FakeFuture(result=rejected)])
    try:
        for _ in range(6):
            node._tick()

        assert node.state == PainterState.ERROR
        assert 'read only' in node.failure_reason
        assert events[-1] == 'stop'
    finally:
        node.destroy_node()


def test_pipeline_failure_enters_error_and_finishes_cleanup(ros_context):
    """Planning errors use the same terminal safe-stop behavior."""
    clock = _FakeClock()
    events = []
    node = make_node(clock, events, ros_context, [])
    node._executor.future = _FakeFuture(error=OSError('bad image'))
    try:
        node._tick()
        node._tick()
        node._tick()
        assert node.state == PainterState.ERROR
        assert events[-1] == 'stop'

        node._tick()
        node._tick()
        assert node.state == PainterState.ERROR
        assert node.finished
        assert node.exit_code == 1
        assert events[-2:] == [('pen_off', (0, 0, 0)), 'stop']
    finally:
        node.destroy_node()


def test_main_reports_wrong_typed_ros_parameter_without_traceback(
    monkeypatch, capsys,
):
    """ROS parameter type errors become clean configuration failures."""
    expected = Parameter.Type.INTEGER
    error = InvalidParameterTypeException(
        Parameter('pen_width', value='oops'), expected)

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
