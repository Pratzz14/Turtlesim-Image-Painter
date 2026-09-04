"""Tests for the standalone image-processing command."""

import json

from PIL import Image

from process_image import main
import pytest


def test_cli_processes_an_image(tmp_path, capsys):
    """The command accepts an image path and prints a pixel matrix."""
    path = tmp_path / 'sample.png'
    Image.new('RGB', (4, 2), 'red').save(path)

    assert main([str(path)]) == 0

    output = capsys.readouterr().out
    assert 'Size: 4x2' in output
    assert 'Palette:' in output
    assert 'Pixels (hex RGB):' in output
    assert 'Total distance:' in output
    assert (tmp_path / 'sample_plan.json').is_file()
    assert (tmp_path / 'sample_preview.png').is_file()


def test_cli_writes_custom_plan_and_preview_paths(tmp_path, capsys):
    """Artifact paths and snake ordering are configurable from the CLI."""
    path = tmp_path / 'sample.png'
    plan_path = tmp_path / 'artifacts' / 'painting.json'
    preview_path = tmp_path / 'artifacts' / 'painting.png'
    image = Image.new('RGB', (4, 2), 'red')
    image.putpixel((3, 1), (0, 0, 255))
    image.save(path)

    assert main([
        str(path),
        '--colors', '2',
        '--background-tolerance', '12',
        '--stroke-orientation', 'vertical',
        '--path-order', 'snake',
        '--plan-output', str(plan_path),
        '--preview-output', str(preview_path),
    ]) == 0

    document = json.loads(plan_path.read_text(encoding='utf-8'))
    assert document['format_version'] == 1
    assert document['strategies']['path_order'] == 'snake'
    assert document['strategies']['stroke_orientation'] == 'vertical'
    assert preview_path.is_file()
    output = capsys.readouterr().out
    assert str(plan_path) in output
    assert str(preview_path) in output


def test_cli_reports_invalid_image(tmp_path, capsys):
    """The command gives a short error rather than a traceback."""
    path = tmp_path / 'missing.png'

    assert main([str(path)]) == 1
    assert 'Error: image does not exist' in capsys.readouterr().out


@pytest.mark.parametrize('palette_size', ['1', '9'])
def test_cli_rejects_palette_outside_two_to_eight(
    tmp_path, palette_size,
):
    """Argument parsing exposes the same palette bounds as the API."""
    path = tmp_path / 'sample.png'
    Image.new('RGB', (1, 1), 'red').save(path)

    with pytest.raises(SystemExit):
        main([str(path), '--colors', palette_size])


@pytest.mark.parametrize('tolerance', ['-1', '256'])
def test_cli_rejects_invalid_background_tolerance(tmp_path, tolerance):
    """CLI background cleanup uses the same bounded tolerance contract."""
    path = tmp_path / 'sample.png'
    Image.new('RGB', (1, 1), 'white').save(path)

    with pytest.raises(SystemExit):
        main([str(path), '--background-tolerance', tolerance])
