import importlib.util
from pathlib import Path

def test_shift_command_delays_audio_without_shell():
    assert importlib.util.find_spec('scripts.diagnose_syncnet_offset') is not None
    from scripts.diagnose_syncnet_offset import shift_command
    cmd=shift_command(Path('input.mp4'),Path('output.mkv'),0.4)
    assert isinstance(cmd,list)
    assert 'adelay=400:all=1' in cmd
    assert 'copy' in cmd
