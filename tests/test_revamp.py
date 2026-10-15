"""Behavioral coverage for catalog isolation, scheduling and price removal."""
import datetime as dt
import json
import threading
from unittest.mock import Mock, patch

import pytest
import app as web
import traderie

HOST = {'Host': '127.0.0.1:8765'}
NOW = dt.datetime.now(dt.timezone.utc)


@pytest.fixture(autouse=True)
def local_state(tmp_path, monkeypatch):
    web.S.__init__()
    web.STOP.clear()
    web.AUTO_WAKE.clear()
    for key in ('CONFIG_FILE', 'POLICY_FILE', 'ROTATIONS_FILE', 'IMAGES_FILE'):
        monkeypatch.setattr(web, key, tmp_path / (key + '.json'))
    yield
    web.STOP.clear()
    web.AUTO_WAKE.clear()


def client_with(rows):
    c = Mock(spec=traderie.TraderieClient)
    c.slug = 'creaturesofsonaria'
    c.has_auth = True
    c.get_all_listings.return_value = rows
    web.S.client, web.S.user_id = c, 42
    return c


def listing(i=1, **kw):
    return traderie.Listing(i, '2020-01-01T00:00:00Z', itemName='Creature', **kw)


def test_catalog_works_without_account_filters_categories_and_caches():
    rows = {'alpha': {'id':1,'name':'Alpha','category':'species','properties':[]},
            'plush': {'id':2,'name':'Plush','category':'plushies','properties':[]}}
    with patch.object(web.CATALOG_CLIENT,'search_catalog_items',return_value=list(rows.values())) as catalog, \
         patch.object(web.CATALOG_CLIENT,'get_all_listings',side_effect=AssertionError('Owned listings accessed')):
        c = web.app.test_client()
        result = c.get('/api/catalog/search?category=slots',headers=HOST)
        assert result.status_code == 200
        assert [x['name'] for x in result.json['items']] == ['Alpha']
        assert c.get('/api/catalog/search?category=slots',headers=HOST).json == result.json
        catalog.assert_called_once()


def test_catalog_failure_is_not_reported_as_empty_success():
    with patch.object(web.CATALOG_CLIENT,'search_catalog_items',side_effect=traderie.TraderieError('Offline')):
        r=web.app.test_client().get('/api/catalog/search',headers=HOST)
        assert r.status_code == 503
        assert r.json['catalog_available'] is False


def test_catalog_fallback_keeps_category_and_does_not_read_listings():
    c=client_with({})
    c.search_catalog_items.return_value=[{'id':1,'name':'Alpha','category':'species'},
                                        {'id':2,'name':'Alpha plush','category':'plushies'}]
    r=web.app.test_client().get('/api/catalog/search?q=Alpha&category=slots',headers=HOST)
    assert [row['id'] for row in r.json['items']] == [1]
    c.get_all_listings.assert_not_called()


def test_false_flag_preserves_deadline_but_does_not_authorize_refresh():
    deadline=(NOW+dt.timedelta(seconds=3)).isoformat()
    parsed=traderie.parse_listing({'id':1,'updated_at':NOW.isoformat(),
                                  'can_refresh':False,'next_refresh_at':deadline})
    assert parsed.refresh_available_at == deadline
    assert traderie.relist_eta(parsed,NOW) == dt.timedelta(seconds=3)
    assert not traderie.is_listing_relistable(parsed,NOW+dt.timedelta(seconds=4))
    assert web.next_availability_check({1:parsed},NOW)==NOW+dt.timedelta(seconds=3)


def test_unknown_availability_never_guesses_from_age():
    c=client_with({1:listing()})
    result=web.run_relist(c,42)
    assert result['unknown']==1
    c.relist.assert_not_called()


def test_due_deadline_refreshes_and_future_deadline_waits():
    c=client_with({1:listing(1,refresh_available_at=(NOW-dt.timedelta(seconds=1)).isoformat()),
                   2:listing(2,refresh_available_at=(NOW+dt.timedelta(hours=1)).isoformat())})
    result=web.run_relist(c,42)
    assert result['relisted']==1
    c.relist.assert_called_once_with(1)


def test_accepted_revision_is_not_repeated_and_new_revision_can_refresh():
    row=listing(can_refresh=True)
    c=client_with({1:row})
    assert web.run_relist(c,42)['relisted']==1
    assert web.run_relist(c,42)['relisted']==0
    row.updated='2021-01-01T00:00:00Z'
    web.S.relist_attempts.clear()
    assert web.run_relist(c,42)['relisted']==1
    assert c.relist.call_count==2


def test_pause_during_fetch_prevents_remaining_automatic_writes():
    c=client_with({1:listing(can_refresh=True)})
    web.S.auto_relist=True
    def fetch(_):
        web.S.auto_relist=False
        return {1:listing(can_refresh=True)}
    c.get_all_listings.side_effect=fetch
    web.run_relist(c,42,automatic=True)
    c.relist.assert_not_called()


def test_rate_limit_halts_batch_and_respects_retry_after():
    c=client_with({1:listing(1,can_refresh=True),2:listing(2,can_refresh=True)})
    error=traderie.TraderieError('Slow down',429)
    error.retry_after=120
    c.relist.side_effect=error
    result=web.run_relist(c,42)
    assert result['relisted']==0
    assert len(result['results'])==1
    assert traderie.parse_updated(result['next_check'])>=NOW+dt.timedelta(seconds=120)
    c.relist.assert_called_once()


def test_manual_refresh_uses_same_lock_and_revision_guard():
    c=client_with({1:listing(can_refresh=True)})
    web.run_relist(c,42)
    c.relist.reset_mock()
    response=web.app.test_client().post('/api/relist',headers=HOST,json={'listing_id':1})
    assert response.status_code==400
    c.relist.assert_not_called()
    with web.RELIST_LOCK:
        response=web.app.test_client().post('/api/relist',headers=HOST,json={'listing_id':1})
    assert response.status_code==502


def test_worker_executes_immediately_when_enabled():
    c=client_with({1:listing(can_refresh=True)})
    web.S.auto_relist=True
    def refresh(_):
        web.STOP.set()
    c.relist.side_effect=refresh
    worker=threading.Thread(target=web.auto_loop)
    worker.start()
    worker.join(2)
    assert not worker.is_alive()
    c.relist.assert_called_once_with(1)


def test_listing_json_contains_no_prices_and_cached_reads_reuse_snapshot():
    c=client_with({1:listing(can_refresh=True)})
    test_client=web.app.test_client()
    first=test_client.get('/api/listings',headers=HOST)
    second=test_client.get('/api/listings?cached=1',headers=HOST)
    assert first.status_code==second.status_code==200
    assert not {'price','average_value','community_value'} & first.json['listings'][0].keys()
    c.get_all_listings.assert_called_once()
    assert test_client.get('/api/market-values',headers=HOST).status_code==404


@pytest.mark.parametrize('reviews,roles,expected',[
    (None,None,1200), (999,[],1200), (1000,[],1080),
    (0,[{'title':'champion'}],360), (0,[{'title':'patron'}],360),
    (0,[{'title':'epic'}],30), (0,[{'title':'prime'}],30),
    (0,[{'title':'mod_creaturesofsonaria'}],30),
    (0,[{'title':'mod_othergame'}],1200),
    (0,[{'title':'champion_othergame'}],360),
    (0,[{'title':'mod_traderie'}],30),
])
def test_verified_site_refresh_rules(reviews,roles,expected):
    assert traderie.refresh_cooldown_minutes({'reviews':reviews,'roles':roles})==expected


def test_profile_schedule_applies_only_without_server_signals():
    import time
    c=traderie.TraderieClient()
    c._refresh_profile=(42,time.monotonic(),{'reviews':0,'roles':None})
    rows={1:listing(1),2:listing(2,can_refresh=False),3:listing(3,refresh_available_at=NOW.isoformat())}
    c.apply_refresh_schedule(rows,42)
    assert rows[1].refresh_available_at=='2020-01-01T20:00:00+00:00'
    assert rows[1].availability_source=='site_rule'
    assert rows[2].refresh_available_at is None
    assert rows[3].refresh_available_at==NOW.isoformat()


def test_profile_error_leaves_unknown_schedule():
    c=traderie.TraderieClient()
    with patch.object(c,'get_status',side_effect=traderie.TraderieError('offline')):
        rows={1:listing()}
        c.apply_refresh_schedule(rows,42)
    assert rows[1].refresh_available_at is None


def test_catalog_normalization_preserves_real_mode_groups_and_type_only():
    raw={'id':'1219367524','type':'Creatures','name':'Mijusuima','img':'https://cdn.nookazon.com/test.png',
         'buy_price':10,'prices':[{'avg':123}],
         'properties':[{'id':828,'name':'Species or Slot?','type':'string','options':['Species','Slot'],'required':True},
                       {'id':117,'name':'Mutations','type':'multiselect','format':{'limit':3}},
                       {'id':135,'name':'Glow Tail','type':'bool','format':{'group':{'name':'Mutations'}}}]}
    result=traderie.normalize_catalog_item(raw)
    assert result['item_type']=='Creatures'
    assert result['image_url']=='https://cdn.nookazon.com/test.png'
    assert not {'prices','buy_price'} & result.keys()
    assert result['properties'][0]['id']==828
    assert result['properties'][1]['group']=='Mutations'
    assert result['properties'][1]['group_limit']==3
    assert result['properties'][1]['type']=='bool'


def test_catalog_pagination_is_forwarded_and_bad_pages_rejected():
    with patch.object(web.CATALOG_CLIENT,'search_catalog_items',return_value=[]) as search:
        c=web.app.test_client()
        assert c.get('/api/catalog/search?category=plushies&page=2',headers=HOST).status_code==200
        search.assert_called_once_with('',category='plushies',page=2)
        assert c.get('/api/catalog/search?page=-1',headers=HOST).status_code==400
