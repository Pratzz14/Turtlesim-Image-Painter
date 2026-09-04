"""Tests for the standalone image-processing command."""

from PIL import Image

from process_image import main


def test_cli_processes_an_image(tmp_path, capsys):
    """The command accepts an image path and prints a pixel matrix."""
    path = tmp_path / 'sample.png'
    Image.new('RGB', (4, 2), 'red').save(path)

    assert main([str(path)]) == 0

    output = capsys.readouterr().out
    assert 'Size: 4x2' in output
    assert 'Palette:' in output
    assert 'Pixels (hex RGB):' in output


def test_cli_reports_invalid_image(tmp_path, capsys):
    """The command gives a short error rather than a traceback."""
    path = tmp_path / 'missing.png'

    assert main([str(path)]) == 1
    assert 'Error: image does not exist' in capsys.readouterr().out
