"""Deterministic queue clocks; no account writes or real-time waits."""
import datetime as dt
from unittest.mock import Mock
import pytest
import app as web
import traderie

HOST={'Host':'127.0.0.1:8765'}
BASE=dt.datetime(2026,10,15,12,tzinfo=dt.timezone.utc)

class Clock(dt.datetime):
    current=BASE
    @classmethod
    def now(cls, tz=None):
        return cls.current if tz else cls.current.replace(tzinfo=None)

@pytest.fixture
def setup(monkeypatch):
    web.S.__init__();web.STOP.clear()
    Clock.current=BASE
    monkeypatch.setattr(web.dt,'datetime',Clock)
    c=Mock(spec=traderie.TraderieClient)
    c.has_auth=True;c.slug='creaturesofsonaria';c.policy={}
    c.get_all_listings.return_value={}
    c.create_listing.side_effect=range(100,200)
    web.S.client=c;web.S.user_id=42;web.S.rotation_owner='creaturesofsonaria:42'
    return web.app.test_client(),c

def post(api,path,data):
    return api.post('/api/rotation-routines/'+path,json=data,headers=HOST)

def batch(api,n=2,minutes=60):
    r=post(api,'batch',{'interval_minutes':minutes,'items':[{'item_name':f'Creature {i}','template':{'item':str(i+1),'amount':'2','itemType':'Creatures','properties':[{'id':828,'name':'Species or Slot?','type':'string','string':'Slot'}]}} for i in range(n)]})
    assert r.status_code==200
    return web.S.rotations

def start(api):
    assert post(api,'control',{'action':'start','confirm':True}).status_code==200

def test_initial_spacing_and_hourly_delete_before_create_with_exact_template(setup):
    api,c=setup; rows=batch(api);start(api)
    web.run_rotation_tick()
    assert rows[0]['owned_ids']==[100]
    assert rows[1]['owned_ids']==[]
    first=c.create_listing.call_args.args[0]
    Clock.current=BASE+dt.timedelta(seconds=59)
    web.run_rotation_tick();assert c.create_listing.call_count==1
    Clock.current=BASE+dt.timedelta(seconds=60)
    web.run_rotation_tick();assert rows[1]['owned_ids']==[101]
    Clock.current=BASE+dt.timedelta(minutes=59,seconds=59)
    web.run_rotation_tick();assert c.create_listing.call_count==2
    c.get_all_listings.return_value={100:Mock(),101:Mock(),999:Mock()}
    c.reset_mock()
    Clock.current=BASE+dt.timedelta(hours=1)
    web.run_rotation_tick()
    c.delete_listing.assert_called_once_with(100)
    assert c.create_listing.call_args.args[0]==first
    calls=[call[0] for call in c.mock_calls]
    assert calls.index('delete_listing')<calls.index('create_listing')
    assert rows[0]['owned_ids']==[102]
    assert rows[0]['next_run']==(BASE+dt.timedelta(hours=2)).isoformat()
    Clock.current+=dt.timedelta(seconds=60)
    web.run_rotation_tick()
    assert rows[1]['owned_ids']==[103]

def test_late_worker_never_bursts_and_keeps_queue_order(setup):
    api,c=setup;rows=batch(api,3);start(api)
    Clock.current+=dt.timedelta(minutes=5)
    for _ in range(10):web.run_rotation_tick()
    assert c.create_listing.call_count==1
    Clock.current+=dt.timedelta(seconds=60);web.run_rotation_tick()
    assert rows[1]['owned_ids']==[101]

def test_pause_before_due_preserves_listing_and_resume_respects_lifetime(setup):
    api,c=setup;rows=batch(api,1);start(api);web.run_rotation_tick()
    post(api,'control',{'action':'stop'})
    Clock.current+=dt.timedelta(minutes=5);web.run_rotation_tick()
    c.delete_listing.assert_not_called()
    start(api);web.run_rotation_tick()
    assert c.create_listing.call_count==1
    assert rows[0]['next_run']==(BASE+dt.timedelta(hours=1)).isoformat()

def test_pause_during_read_prevents_post(setup):
    api,c=setup;rows=batch(api,1);start(api)
    def read(_):
        post(api,'control',{'action':'stop'})
        return {}
    c.get_all_listings.side_effect=read
    with pytest.raises(ValueError):web.run_rotation_tick()
    c.create_listing.assert_not_called()
    assert not rows[0]['enabled']

def test_pause_during_delete_prevents_recreation(setup):
    api,c=setup;rows=batch(api,1);start(api)
    rows[0]['owned_ids']=[99]
    c.get_all_listings.return_value={99:Mock()}
    c.delete_listing.side_effect=lambda _:post(api,'control',{'action':'stop'})
    web.run_rotation_tick()
    c.create_listing.assert_not_called()
    assert rows[0]['owned_ids']==[]

def test_deletion_failure_pauses_without_creating(setup):
    api,c=setup;rows=batch(api,1);start(api);rows[0]['owned_ids']=[99]
    c.get_all_listings.return_value={99:Mock()}
    c.delete_listing.side_effect=traderie.TraderieError('Deletion uncertain')
    with pytest.raises(traderie.TraderieError):web.run_rotation_tick()
    c.create_listing.assert_not_called()
    assert rows[0]['owned_ids']==[99] and not rows[0]['enabled']

def test_ambiguous_creation_never_automatically_retries(setup):
    api,c=setup;rows=batch(api,1);start(api)
    c.create_listing.side_effect=traderie.TraderieError('Timeout after send')
    with pytest.raises(traderie.TraderieError):web.run_rotation_tick()
    Clock.current+=dt.timedelta(hours=2)
    web.run_rotation_tick();assert c.create_listing.call_count==1
    assert not rows[0]['enabled']

def test_rate_limit_defers_other_items(setup):
    api,c=setup;rows=batch(api);start(api)
    err=traderie.TraderieError('Rate limited',429);err.retry_after=180
    c.create_listing.side_effect=err
    with pytest.raises(traderie.TraderieError):web.run_rotation_tick()
    Clock.current+=dt.timedelta(seconds=120);web.run_rotation_tick()
    assert c.create_listing.call_count==1
    assert web.S.rotation_not_before==BASE+dt.timedelta(seconds=180)

def test_auth_failure_pauses_whole_queue(setup):
    api,c=setup;rows=batch(api);start(api)
    c.create_listing.side_effect=traderie.AuthRequired('Expired')
    with pytest.raises(traderie.AuthRequired):web.run_rotation_tick()
    assert not any(r['enabled'] for r in rows)

def test_batch_validation_is_atomic_and_requires_auth(setup):
    api,c=setup
    assert post(api,'batch',{'items':[{'item_name':'A','template':{'item':'1','amount':'1'}},{'item_name':'B','template':{'item':'1','amount':'0'}}]}).status_code==400
    assert web.S.rotations==[]
    c.has_auth=False
    assert post(api,'batch',{'items':[]}).status_code==401

def test_stop_works_without_auth_and_start_requires_confirmation(setup):
    api,c=setup;batch(api)
    assert post(api,'control',{'action':'start'}).status_code==400
    c.has_auth=False
    assert post(api,'control',{'action':'stop'}).status_code==200

def test_auto_refresh_waits_for_positive_signal_then_writes_in_same_check(setup):
    api,c=setup
    row=traderie.Listing(9,'2020-01-01T00:00:00Z',can_refresh=False)
    c.get_all_listings.return_value={9:row}
    web.S.auto_relist=True
    assert web.run_relist(c,42,automatic=True)['relisted']==0
    row.can_refresh=True
    assert web.run_relist(c,42,automatic=True)['relisted']==1
    c.relist.assert_called_once_with(9)

def test_queue_managed_items_not_refreshed_by_other_automation(setup):
    api,c=setup;rows=batch(api,1);start(api);rows[0]['owned_ids']=[9]
    c.get_all_listings.return_value={9:traderie.Listing(9,'2020-01-01T00:00:00Z',can_refresh=True)}
    assert web.run_relist(c,42)['relisted']==0
    c.relist.assert_not_called()

FIXED={'item':'1002485057047','amount':'1','itemType':'Creatures',
       'acceptListingPrice':True,'makeOffer':False,
       'currencyGroupPrices':[{'group':0,'nmt':10000000,'currency':True}],
       'properties':[{'id':828,'name':'Species or Slot?','type':'string','string':'Species'}]}

def test_fixed_price_matches_supplied_traderie_payload():
    model=traderie.validated_creation(FIXED)
    assert model['currencyGroupPrices']==[{'group':0,'nmt':10000000,'currency':True}]
    assert model['acceptListingPrice'] is True and model['makeOffer'] is False
    assert model['properties']==FIXED['properties']
    assert 'price' not in model and 'prices' not in model

@pytest.mark.parametrize('value',[None,0,-1,1.5,True,'100',float('nan'),1000000000])
def test_fixed_price_rejects_invalid_amounts(value):
    with pytest.raises(ValueError):
        traderie.validated_creation({**FIXED,'currencyGroupPrices':[{'group':0,'nmt':value,'currency':True}]})

@pytest.mark.parametrize('patch',[
    {'makeOffer':True},{'free':True},{'currencyGroupPrices':[]},
    {'currencyGroupPrices':[{'group':0,'nmt':20,'currency':False}]},
    {'currencyGroupPrices':[{'group':True,'nmt':20,'currency':True}]},
    {'currencyGroupPrices':[{'group':0,'nmt':20,'currency':True,'auth':'injected'}]},
    {'acceptListingPrice':False},
])
def test_inconsistent_sale_modes_rejected(patch):
    with pytest.raises(ValueError):traderie.validated_creation({**FIXED,**patch})

def test_switching_to_offers_omits_price():
    model=traderie.validated_creation({'item':'1','amount':'1','makeOffer':True,'acceptListingPrice':False})
    assert 'currencyGroupPrices' not in model


def test_fixed_price_survives_two_rotation_cycles(setup):
    api,c=setup
    assert post(api,'batch',{'items':[{'item_name':'Creature','template':FIXED}]}).status_code==200
    start(api);web.run_rotation_tick()
    first=c.create_listing.call_args.args[0]
    Clock.current+=dt.timedelta(hours=1)
    c.get_all_listings.return_value={100:Mock()}
    web.run_rotation_tick()
    assert c.create_listing.call_args.args[0]==first
    assert first['currencyGroupPrices']==FIXED['currencyGroupPrices']
    c.delete_listing.assert_called_once_with(100)


def test_bad_persisted_template_pauses_instead_of_spinning(setup):
    api,c=setup;rows=batch(api,1);start(api)
    rows[0]['template']['amount']='0'
    with pytest.raises(ValueError):web.run_rotation_tick()
    assert not rows[0]['enabled'] and not rows[0]['running']
    web.run_rotation_tick();c.create_listing.assert_not_called()


def test_pause_during_creation_tracks_result_and_disallows_removal(setup):
    api,c=setup;rows=batch(api,1);start(api)
    def create(_):
        post(api,'control',{'action':'stop'})
        result=post(api,'action',{'id':rows[0]['id'],'action':'remove','confirm':True})
        assert result.status_code==400
        return 321
    c.create_listing.side_effect=create
    web.run_rotation_tick()
    assert rows[0]['owned_ids']==[321] and not rows[0]['enabled']
    assert not rows[0]['running']


def test_restart_preserves_queue_gate_but_never_reenables(setup,monkeypatch):
    api,c=setup;rows=batch(api,1);start(api);web.run_rotation_tick()
    saved=web._read_json(web.ROTATIONS_FILE)
    assert saved['not_before']==(BASE+dt.timedelta(seconds=60)).isoformat()
    monkeypatch.setattr(web,'TraderieClient',lambda *a,**kw:c)
    c.get_status.return_value='online'
    web.S.__init__()
    web.connect('creaturesofsonaria','Test','42','fake',30,False)
    assert web.S.rotation_not_before==BASE+dt.timedelta(seconds=60)
    assert web.S.rotations[0]['owned_ids']==[100]
    assert not web.S.rotations[0]['enabled']
