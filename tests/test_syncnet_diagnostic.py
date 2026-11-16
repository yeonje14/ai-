import importlib.util
from pathlib import Path

def test_shift_command_delays_audio_without_shell():
    assert importlib.util.find_spec('scripts.diagnose_syncnet_offset') is not None
    from scripts.diagnose_syncnet_offset import shift_command
    cmd=shift_command(Path('input.mp4'),Path('output.mkv'),0.4)
    assert isinstance(cmd,list)
    assert 'adelay=400:all=1' in cmd
    assert 'copy' in cmd


def test_shift_command_advances_audio_and_accepts_zero():
    from scripts.diagnose_syncnet_offset import shift_command
    cmd = shift_command(Path('in.mov'), Path('out.mkv'), -0.08)
    assert 'atrim=start=0.08,asetpts=PTS-STARTPTS' in cmd
    cmd = shift_command(Path('in.mov'), Path('out.mkv'), 0)
    assert 'anull' in cmd


def test_matrix_runs_baseline_once_and_cleans_media(tmp_path, monkeypatch, capsys):
    import json
    from scripts import diagnose_syncnet_offset as tool
    root = tmp_path / 'samples'; root.mkdir()
    (root / 'A.MOV').write_bytes(b'authorized fixture')
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'authorized_media':[
        {'youtube_video_id':'SyncNetTstA','local_path':'A.MOV'}]}))
    monkeypatch.setattr(tool, 'ROOT', tmp_path)
    shifted=[]; calls=[]
    def ffmpeg(cmd, **kwargs):
        shifted.append(cmd[cmd.index('-af')+1])
        Path(cmd[-1]).write_bytes(b'shifted fixture')
    def infer(path, segments, work):
        assert path.is_file()
        calls.append((path.name,segments))
        return {'status':'completed','segments':[]}
    monkeypatch.setattr(tool.subprocess,'run',ffmpeg)
    monkeypatch.setattr(tool,'run_syncnet',infer)
    assert tool.main(['--registry',str(registry),'--media-root',str(root),
        '--video-id','SyncNetTstA','--start','26','--end','34','--delays','-0.2','-0.08','0','0.08','0.2'])==0
    result=json.loads(capsys.readouterr().out)
    assert len(calls)==6 and calls[0]==('source.mp4',[(26.,34.)])
    assert shifted==['atrim=start=0.2,asetpts=PTS-STARTPTS','atrim=start=0.08,asetpts=PTS-STARTPTS',
                     'anull','adelay=80:all=1','adelay=200:all=1']
    assert len(result['results'])==6
    assert list((tmp_path/'data/runtime').iterdir())==[]
    assert (root/'A.MOV').read_bytes()==b'authorized fixture'
