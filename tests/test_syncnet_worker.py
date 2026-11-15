from dataclasses import replace
import pytest
from server.axes import alignment
from server.axes.alignment import syncnet
from server.jobs import worker
from server.gate.types import GateResult, Segment
from tests.test_gate_worker import MEDIA, run_job
from tests.test_syncnet_adapter import fake_config

@pytest.mark.parametrize('mode,status,reason', [('ok','completed',None),('partial','insufficient_input','tracking_failed'),('empty','insufficient_input','tracking_failed'),('error','error','inference_error')])
def test_worker_real_fake_process_metrics(queue, registry, settings, monkeypatch, tmp_path, mode,status,reason):
    body = ""
    if mode == 'partial': body = "out['segments'][1].update(status='insufficient_input', tracks=None);"
    if mode == 'empty': body = "[s.update(status='insufficient_input', tracks=None) for s in out['segments']];"
    if mode == 'error': body = "out['segments'][1].update(status='error', tracks=None);"
    cfg=fake_config(tmp_path,body+"Path(a.output).write_text(json.dumps(out))")
    monkeypatch.setattr(alignment,'build_config',lambda ctx:cfg,raising=False)
    monkeypatch.setattr(worker,'run_gate_process',lambda *a,**k:GateResult(MEDIA,None,eligible_segments=(Segment(1,3),Segment(5,8))))
    monkeypatch.setattr(worker.signal_axis,'run',lambda ctx:{'status':'completed','raw_score':None,'raw_metrics':{'frame_logit':{'frames':2}}})
    received=[]
    original=syncnet.run_syncnet
    def capture(*a,**kw):
        result=original(*a,**kw);received.append(result);return result
    monkeypatch.setattr(syncnet,'run_syncnet',capture)
    _,job=run_job(queue,registry,settings)
    out=job.result['axes']['alignment']
    assert (out['status'],out['reason_code'])==(status,reason)
    assert out['lse_c'] is None and out['lse_d'] is None and not out['included_in_fusion']
    assert job.result['axes']['signal']['raw_metrics']['frame_logit']['frames']==2
    assert received
    if mode in ('ok','partial','error'):
        assert received[0]['segments'][0]['tracks'][0]=={'track_index':0,'lse_c':2.5,'lse_d':6.5,'offset_frames':-2}
    assert any(e['template_id']=='SYNCNET_UNAGGREGATED' for e in job.result['explanations']) == (mode=='ok')
    assert 'segments' not in out


def test_manual_gate_bypass_never_runs_syncnet(queue,registry,settings,monkeypatch):
    monkeypatch.setattr(syncnet,'run_syncnet',lambda *a,**k:pytest.fail('must not run'))
    _,job=run_job(queue,registry,replace(settings,dev_manual_segments=((1,3),)))
    assert job.result['axes']['alignment']['reason_code']=='speaker_unconfirmed'

@pytest.mark.parametrize('cancel',[False,True])
def test_syncnet_heartbeat_extends_lease_and_cancel_stops_job(queue,registry,settings,monkeypatch,tmp_path,cancel):
    import sqlite3
    from tests.conftest import REGISTERED_ID
    cfg=fake_config(tmp_path,"time.sleep(0.25); Path(a.output).write_text(json.dumps(out))")
    monkeypatch.setattr(alignment,'build_config',lambda ctx:cfg)
    monkeypatch.setattr(worker,'run_gate_process',lambda *a,**k:GateResult(MEDIA,None,eligible_segments=(Segment(1,3),)))
    monkeypatch.setattr(worker.signal_axis,'run',lambda ctx:{'status':'completed','raw_score':None})
    aid=queue.enqueue(REGISTERED_ID,'gate-owner',3)
    original=queue.heartbeat;leases=[]
    def heartbeat(*args):
        state=original(*args)
        with sqlite3.connect(settings.db_path) as db:
            stage,lease=db.execute('select stage,lease_expires_at from jobs where analysis_id=?',(aid,)).fetchone()
        if stage=='syncnet':
            leases.append(lease)
            if cancel and len(leases)==2:
                queue.request_cancel(aid,'gate-owner')
        return state
    monkeypatch.setattr(queue,'heartbeat',heartbeat)
    assert worker.run_once(queue,registry,replace(settings,heartbeat_interval_seconds=0.02),'sync-worker')
    job=queue.get(aid,'gate-owner')
    assert job.job_status==('cancelled' if cancel else 'finished')
    assert len(set(leases))>=2
    assert not (settings.runtime_dir/aid).exists()
