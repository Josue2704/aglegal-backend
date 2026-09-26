"""Calendar regression tests: isolated database, fake provider, no external messages."""
from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from aglegal.db import now_iso
from api.app.services import google_calendar as gcal, calendar_sync

@pytest.fixture
def client(repo, monkeypatch):
    from api.app.main import app
    from api.app.deps import get_current_user
    from api.app.routers import sessions
    app.dependency_overrides[get_current_user] = lambda: dict(username='admin',is_admin=True,permissions=set())
    monkeypatch.setattr(sessions,'_email_notify',lambda *a,**k: None)
    monkeypatch.setattr(sessions,'_sync_create',lambda *a,**k: None)
    monkeypatch.setattr(sessions,'_sync_update',lambda *a,**k: None)
    with TestClient(app,raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    repo.delete_google_tokens('admin')
    repo.conn.execute("DELETE FROM calendar_sync_jobs WHERE provider='google'")
    repo.conn.commit()


def payload(**kw):
    return dict(dict(session_date='2034-02-04',start_time='09:00',end_time='10:00',
        consult_type='Calendar test',notes='',status='Pendiente',permitir_solape=True),**kw)


def test_failed_create_retries_same_id_and_original_owner(client,repo,monkeypatch):
    repo.save_google_tokens('admin','fake','fake','')
    create=Mock(side_effect=RuntimeError('sensitive provider response'))
    monkeypatch.setattr(gcal,'create_event',create)
    response=client.post('/sessions',json=payload())
    assert response.status_code==201,response.text
    sid=response.json()['id']
    assert response.json()['calendar_error'] and 'sensitive' not in response.text
    event_id=create.call_args.kwargs['event_id']
    create.side_effect=None; create.return_value=event_id
    assert client.post('/google-cal/retry').json()['completed']==1
    assert create.call_args.kwargs['event_id']==event_id
    assert repo.get_session(sid)['gcal_event_id']==event_id
    from api.app.main import app
    from api.app.deps import get_current_user
    app.dependency_overrides[get_current_user]=lambda:dict(username='another-user',is_admin=True,permissions=set())
    update=Mock(); monkeypatch.setattr(gcal,'update_event',update)
    assert client.put(f'/sessions/{sid}',json=payload(notes='changed')).status_code==200
    assert update.call_args.args[0]['username']=='admin'
    delete=Mock(side_effect=RuntimeError());monkeypatch.setattr(gcal,'delete_event',delete)
    assert client.delete(f'/sessions/{sid}').status_code==204
    assert not repo.get_session(sid)
    assert repo.conn.execute("SELECT 1 FROM calendar_sync_jobs WHERE session_id=%s AND operation='delete' AND status='Pendiente'",(sid,)).fetchone()
    delete.side_effect=None
    assert calendar_sync.process(repo,owner='admin')['completed']==1


def test_import_preserves_case_client_and_handles_cancel_and_multiday(client,repo,catalogo,monkeypatch):
    cid=repo.create_case(client_id=catalogo['cliente_id'],title='Calendar case',status='Abierto',priority='Media',
        opened_at='2034-01-01',created_at=now_iso(),service_id=catalogo['servicio_id'])
    sid=repo.create_session(client_id=catalogo['cliente_id'],case_id=cid,created_at=now_iso(),**payload())
    repo.conn.execute("UPDATE sessions SET gcal_event_id='imported',gcal_owner='admin' WHERE id=%s",(sid,));repo.conn.commit()
    repo.save_google_tokens('admin','fake','fake','')
    event=dict(id='imported',summary='New title',start={'dateTime':'2034-02-04T15:00:00Z'},end={'dateTime':'2034-02-04T16:00:00Z'})
    multi=dict(id='multi',summary='All day',start={'date':'2034-02-05'},end={'date':'2034-02-08'})
    monkeypatch.setattr(gcal,'list_events',lambda *a,**kw:[event,multi])
    r=client.post('/google-cal/import');assert r.status_code==200,r.text
    assert r.json()['updated']==1 and r.json()['imported']==1
    row=repo.get_session(sid)
    assert row['case_id']==cid and row['client_id']==catalogo['cliente_id'] and row['start_time']=='09:00'
    assert repo.conn.execute("SELECT end_date FROM sessions WHERE gcal_event_id='multi'").fetchone()['end_date']=='2034-02-07'
    assert client.post('/google-cal/import').json()['imported']==0
    monkeypatch.setattr(gcal,'list_events',lambda *a,**kw:[dict(id='imported',status='cancelled')])
    assert client.post('/google-cal/import').json()['cancelled']==1
    assert repo.get_session(sid)['status']=='Cancelada'


def test_import_error_is_not_reported_as_empty_success(client,repo,monkeypatch):
    repo.save_google_tokens('admin','fake','fake','')
    monkeypatch.setattr(gcal,'list_events',Mock(side_effect=RuntimeError('private')))
    response=client.post('/google-cal/import')
    assert response.status_code==502 and 'private' not in response.text
    assert client.get('/google-cal/status').json()['error']


def test_pagination_and_idempotent_deleted_event(monkeypatch):
    svc=Mock();svc.events.return_value.list.return_value.execute.side_effect=[{'items':[{'id':'1'}],'nextPageToken':'next'},{'items':[{'id':'2'}]}]
    monkeypatch.setattr(gcal,'_connected_service',lambda *a:svc)
    assert len(gcal.list_events({},datetime.now(timezone.utc),datetime.now(timezone.utc)))==2
    assert svc.events.return_value.list.call_args.kwargs['pageToken']=='next'
    from googleapiclient.errors import HttpError
    from httplib2 import Response
    svc.events.return_value.delete.return_value.execute.side_effect=HttpError(Response({'status':404}),b'{}')
    gcal.delete_event({},'missing')


def test_oauth_browser_bound_single_use(client,repo,monkeypatch):
    from api.app.services import calendar_oauth
    from fastapi import Response
    response=Response();state=calendar_oauth.begin(repo,'admin','google',response)
    exchange=Mock(return_value=('fake','fake',''))
    monkeypatch.setattr(gcal,'exchange_code',exchange)
    url=f'/google-cal/callback?code=test&state={state}'
    assert client.get(url,follow_redirects=False).status_code==400
    client.cookies.set('google_oauth',state)
    assert client.get(url,follow_redirects=False).status_code==307
    assert exchange.call_count==1
    client.cookies.set('google_oauth',state)
    assert client.get(url,follow_redirects=False).status_code==400
    assert exchange.call_count==1


def test_permissions_calendar_write(client):
    from api.app.main import app
    from api.app.deps import get_current_user
    app.dependency_overrides[get_current_user]=lambda:dict(username='admin',is_admin=False,permissions=set())
    assert client.get('/google-cal/authorize').status_code==403
    for path in ('import','retry','verify'):
        assert client.post('/google-cal/'+path).status_code==403


def test_date_and_client_validation(client,repo,catalogo):
    for changes in ({'end_time':'08:00'},{'start_time':None},{'session_date':'not-date'},{'monto_adicional':-5}):
        assert client.post('/sessions',json=payload(**changes)).status_code==422
    r=client.post('/sessions',json=payload(start_time=None,end_time=None,end_date='2034-02-07'))
    assert r.status_code==201,r.text
    sid=r.json()['id']
    assert client.put(f'/sessions/{sid}',json=payload(client_id=catalogo['cliente_id'])).status_code==200
    assert repo.get_session(sid)['client_id']==catalogo['cliente_id']


def test_keep_refresh_token_when_google_omits_it(repo):
    repo.save_google_tokens('refresh-test','first','keep','')
    repo.save_google_tokens('refresh-test','second','','')
    assert repo.get_google_tokens('refresh-test')['refresh_token']=='keep'
    repo.delete_google_tokens('refresh-test')


def test_billed_delete_never_touches_remote_calendar(client,repo,catalogo,codigo_unico,monkeypatch):
    from tests.test_integridad_facturacion import _caso,_factura
    case_id=_caso(repo,catalogo)
    sid=repo.create_session(client_id=catalogo['cliente_id'],case_id=case_id,created_at=now_iso(),
        monto_adicional_text='50',**payload(status='Finalizada'))
    _factura(repo,catalogo,case_id,'GC-'+codigo_unico,[dict(description='Session',quantity=1,unit_price=50,entity_type='session',entity_id=sid)])
    repo.conn.execute("UPDATE sessions SET gcal_owner='admin',gcal_event_id='billed' WHERE id=%s",(sid,));repo.conn.commit()
    remote=Mock();monkeypatch.setattr(gcal,'delete_event',remote)
    response=client.delete(f'/sessions/{sid}')
    assert response.status_code==422,response.text
    assert repo.get_session(sid) and not remote.called
    assert not repo.conn.execute('SELECT 1 FROM calendar_sync_jobs WHERE session_id=%s',(sid,)).fetchone()


def test_google_create_conflict_patches_without_duplicate(monkeypatch):
    from httplib2 import Response
    from googleapiclient.errors import HttpError
    svc=Mock();svc.events.return_value.insert.return_value.execute.side_effect=HttpError(Response({'status':409}),b'{}')
    monkeypatch.setattr(gcal,'_connected_service',lambda *a:svc)
    row=payload(client_name=None)
    assert gcal.create_event({},row,event_id='ag123')=='ag123'
    assert svc.events.return_value.patch.call_args.kwargs['eventId']=='ag123'
    assert svc.events.return_value.patch.call_args.kwargs['sendUpdates']=='none'


def test_refresh_persists_rotated_credentials(repo,monkeypatch):
    from datetime import timedelta
    row={'username':'rotated','access_token':'old','refresh_token':'old-refresh','expiry_at':'2000-01-01T00:00:00'}
    creds=Mock(token='new',refresh_token='new-refresh',expiry=datetime.now()+timedelta(hours=1))
    monkeypatch.setattr(gcal,'_refresh_if_needed',lambda c:creds)
    monkeypatch.setattr(gcal,'_service',lambda c:Mock())
    gcal._connected_service(row,repo)
    result=repo.get_google_tokens('rotated')
    assert result['access_token']=='new' and result['refresh_token']=='new-refresh'
    repo.delete_google_tokens('rotated')


def test_multiday_overlap_and_date_filter(repo):
    sid=repo.create_session(client_id=None,case_id=None,created_at=now_iso(),**payload(
        session_date='2041-04-01',end_date='2041-04-03',start_time='23:00',end_time='01:00'))
    assert any(r['id']==sid for r in repo.list_sessions(start_date='2041-04-02',end_date='2041-04-02'))
    with pytest.raises(ValueError,match='otra cita'):
        repo.create_session(client_id=None,case_id=None,created_at=now_iso(),**payload(session_date='2041-04-02',permitir_solape=False))


def test_cancelling_additional_session_reverses_fee_once(repo,catalogo):
    from tests.test_integridad_facturacion import _caso
    cid=_caso(repo,catalogo)
    base=repo.get_case(cid)['honorarios_contratados_cents']
    sid=repo.create_session(client_id=catalogo['cliente_id'],case_id=cid,created_at=now_iso(),
        monto_adicional_text='50',**payload())
    assert repo.get_case(cid)['honorarios_contratados_cents']==base+5000
    repo.update_session(sid,case_id=cid,**payload(status='Cancelada'))
    assert repo.get_case(cid)['honorarios_contratados_cents']==base
    repo.update_session(sid,case_id=cid,**payload(status='Pendiente'))
    assert repo.get_case(cid)['honorarios_contratados_cents']==base+5000
    repo.update_session(sid,case_id=cid,**payload(status='Cancelada'))
    repo.delete_session(sid)
    assert repo.get_case(cid)['honorarios_contratados_cents']==base
