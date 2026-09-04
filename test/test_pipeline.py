"""Tests for complete planning and preview artifact generation."""

import json
from pathlib import Path

from PIL import Image
import pytest

from turtlesim_image_painter import PaintingPipeline


def test_pipeline_writes_ordered_json_and_representative_preview(tmp_path):
    """One run returns a plan and writes inspectable JSON and PNG files."""
    source_path = Path(tmp_path) / 'colors.png'
    image = Image.new('RGB', (4, 2), (255, 0, 0))
    for y in range(2):
        for x in range(2, 4):
            image.putpixel((x, y), (0, 0, 255))
    image.save(source_path)

    result = PaintingPipeline().run(
        source_path,
        max_width=4,
        max_height=2,
        palette_size=4,
        background_threshold=0.75,
        path_order='snake',
    )

    plan_path = Path(result.plan_path)
    preview_path = Path(result.preview_path)
    assert plan_path == tmp_path / 'colors_plan.json'
    assert preview_path == tmp_path / 'colors_preview.png'

    document = json.loads(plan_path.read_text(encoding='utf-8'))
    assert document['image'] == {
        'width': 4,
        'height': 2,
        'background': None,
    }
    assert document['strategies'] == {
        'color_order': 'largest_first',
        'path_order': 'snake',
    }
    assert document['statistics']['stroke_count'] == len(
        document['strokes'])
    assert document['statistics']['total_distance'] == (
        document['statistics']['paint_distance']
        + document['statistics']['travel_distance']
    )
    assert [stroke['color'] for stroke in document['strokes'][:2]] == [
        [0, 0, 255], [0, 0, 255],
    ]

    with Image.open(preview_path) as preview:
        assert preview.format == 'PNG'
        assert preview.size == (1100, 700)
        colors = set(preview.convert('RGB').getdata())
    assert (255, 0, 0) in colors
    assert (0, 0, 255) in colors


def test_pipeline_rejects_wrong_artifact_suffixes_before_writing(tmp_path):
    """Artifact validation fails clearly without leaving a partial plan."""
    source_path = Path(tmp_path) / 'source.png'
    plan_path = Path(tmp_path) / 'plan.json'
    Image.new('RGB', (1, 1), 'red').save(source_path)

    try:
        PaintingPipeline().run(
            source_path,
            plan_output=plan_path,
            preview_output=tmp_path / 'preview.jpg',
        )
    except ValueError as error:
        assert '.png suffix' in str(error)
    else:
        raise AssertionError('invalid preview suffix was accepted')
    assert not plan_path.exists()


def test_pipeline_rejects_preview_that_aliases_source_image(tmp_path):
    """An output override cannot replace the user's source PNG."""
    source_path = Path(tmp_path) / 'source.png'
    plan_path = Path(tmp_path) / 'plan.json'
    Image.new('RGB', (2, 1), 'red').save(source_path)
    original_bytes = source_path.read_bytes()

    with pytest.raises(ValueError, match='must not overwrite'):
        PaintingPipeline().run(
            source_path,
            plan_output=plan_path,
            preview_output=source_path,
        )

    assert source_path.read_bytes() == original_bytes
    assert not plan_path.exists()


def test_pipeline_rejects_hard_link_to_source_as_output(tmp_path):
    """Filesystem aliases are rejected even when path strings differ."""
    source_path = Path(tmp_path) / 'source.png'
    alias_path = Path(tmp_path) / 'preview.png'
    Image.new('RGB', (2, 1), 'red').save(source_path)
    alias_path.hardlink_to(source_path)

    with pytest.raises(ValueError, match='must not overwrite'):
        PaintingPipeline().run(source_path, preview_output=alias_path)


def test_preview_failure_leaves_destination_artifacts_untouched(
    tmp_path, monkeypatch,
):
    """Both outputs remain unchanged until both temporary files are ready."""
    source_path = Path(tmp_path) / 'source.png'
    plan_path = Path(tmp_path) / 'plan.json'
    preview_path = Path(tmp_path) / 'preview.png'
    Image.new('RGB', (2, 1), 'red').save(source_path)
    plan_path.write_text('existing plan\n', encoding='utf-8')
    Image.new('RGB', (1, 1), 'blue').save(preview_path)
    original_preview = preview_path.read_bytes()
    pipeline = PaintingPipeline()

    def fail_preview(*args, **kwargs):
        raise OSError('simulated preview failure')

    monkeypatch.setattr(pipeline.preview_generator, 'generate', fail_preview)

    with pytest.raises(OSError, match='simulated preview failure'):
        pipeline.run(
            source_path,
            plan_output=plan_path,
            preview_output=preview_path,
        )

    assert plan_path.read_text(encoding='utf-8') == 'existing plan\n'
    assert preview_path.read_bytes() == original_preview
    assert not list(tmp_path.glob('.*-*'))
