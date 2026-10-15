"""Activity sync, account isolation and explicit offer decisions; offline only."""
import datetime as dt
from unittest.mock import Mock
import pytest
import app as web
import traderie

HOST={'Host':'127.0.0.1:8765'}

@pytest.fixture
def setup():
    web.S.__init__()
    c=Mock(spec=traderie.TraderieClient)
    c.has_auth=True;c.slug='creaturesofsonaria';c.policy={}
    c.get_notifications.return_value=[traderie.Notification('n1','New offer','2026-10-15T12:00:00Z',7,9,11,False)]
    offer=traderie.Offer('Mijusuima',11,9,42,'Seller',7,'Buyer',1,55,
                          prices=[{'group':0,'quantity':2200000,'name':'Shooms','image_url':None}])
    c.get_offers.return_value={11:offer}
    web.S.client=c;web.S.user_id=42
    return web.app.test_client(),c,offer

def post(api,path,data):
    return api.post(path,json=data,headers=HOST)

def test_sync_receives_offers_notifications_and_reuses_cache(setup):
    api,c,o=setup
    first=api.get('/api/inbox',headers=HOST).json
    assert first['offers'][0]['prices'][0]['quantity']==2200000
    assert first['offers'][0]['revision']==web.offer_revision(o)
    assert first['notifications'][0]['offerID']==11
    assert first['unread_count']==1
    api.get('/api/inbox',headers=HOST)
    c.get_notifications.assert_called_once();c.get_offers.assert_called_once()
    c.accept_offer.assert_not_called();c.decline_offer.assert_not_called()

def test_partial_failure_retains_other_source_and_flags_stale(setup):
    api,c,o=setup
    web.refresh_inbox(c,42)
    web.S.inbox['offers']['next_check']=None
    c.get_offers.side_effect=traderie.TraderieError('Offline')
    web.refresh_inbox(c,42)
    d=web.inbox_public()
    assert len(d['offers'])==1 and d['sources']['offers']['error']=='Offline'
    assert not d['sources']['notifications']['error']


def test_rate_limit_backs_off_both_sources_even_after_retry_button(setup):
    api,c,o=setup
    e=traderie.TraderieError('Slow down',429);e.retry_after=120
    c.get_notifications.side_effect=e
    web.refresh_inbox(c,42)
    c.get_offers.assert_not_called()
    post(api,'/api/inbox/retry',{})
    web.refresh_inbox(c,42)
    c.get_notifications.assert_called_once()
    assert web.S.inbox['notifications']['next_check']>dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=110)


def test_auth_failure_pauses_until_retry_or_reconnection(setup):
    api,c,o=setup;c.get_notifications.side_effect=traderie.AuthRequired('Expired')
    web.refresh_inbox(c,42);web.refresh_inbox(c,42)
    c.get_notifications.assert_called_once()
    assert web.S.inbox['notifications']['paused']


def test_account_switch_during_response_discards_old_data(setup):
    api,c,o=setup
    def read(**kw):
        web.S.client=Mock();web.S.user_id=900
        return [traderie.Notification('secret','old account','',None,None)]
    c.get_notifications.side_effect=read
    web.refresh_inbox(c,42)
    assert web.S.inbox=={}
    c.get_offers.assert_not_called()


def test_accept_requires_exact_reviewed_revision_and_runs_once(setup):
    api,c,o=setup
    data={'offer_id':11,'action':'accept','confirm':True,'revision':web.offer_revision(o)}
    assert post(api,'/api/offers/action',data).status_code==200
    assert post(api,'/api/offers/action',data).status_code==409
    c.accept_offer.assert_called_once_with(o)
    c.open_conversation.assert_not_called();c.send_message.assert_not_called()


def test_changed_offer_cannot_be_accepted_from_old_view(setup):
    api,c,o=setup;revision=web.offer_revision(o)
    o.prices[0]['quantity']=1
    assert post(api,'/api/offers/action',{'offer_id':11,'action':'accept','confirm':True,'revision':revision}).status_code==409
    c.accept_offer.assert_not_called()


@pytest.mark.parametrize('changes,code',[({'confirm':False},400),({'offer_id':99},404),({'revision':'outdated'},409),({'action':'unknown'},400)])
def test_bad_or_stale_action_rejected(setup,changes,code):
    api,c,o=setup
    data={'offer_id':11,'action':'accept','confirm':True,'revision':web.offer_revision(o),**changes}
    assert post(api,'/api/offers/action',data).status_code==code
    c.accept_offer.assert_not_called()


def test_offer_for_other_seller_is_rejected(setup):
    api,c,o=setup;o.sellerID=77
    d=post(api,'/api/offers/action',{'offer_id':11,'action':'decline','confirm':True,'revision':web.offer_revision(o)})
    assert d.status_code==404;c.decline_offer.assert_not_called()


def test_mark_read_only_for_notifications_in_account(setup):
    api,c,o=setup;web.refresh_inbox(c,42)
    assert post(api,'/api/notifications/read',{'ids':['other']}).status_code==400
    c.mark_notifications_read.assert_not_called()
    assert post(api,'/api/notifications/read',{'ids':['n1']}).status_code==200
    assert web.inbox_public()['unread_count']==0
    c.mark_notifications_read.assert_called_once_with(['n1'])


def test_no_auth_never_fetches_inbox(setup):
    api,c,o=setup;c.has_auth=False
    assert api.get('/api/inbox',headers=HOST).status_code==401
    c.get_notifications.assert_not_called()


def test_offer_values_support_groups_currency_and_malformed_entries():
    raw={'prices':[{'group':0,'name':'Shooms','quantity':2200000},{'group':1,'item':{'name':'Aerix'},'quantity':'2'},None,{'name':'broken','quantity':float('nan')}]}
    assert [p['quantity'] for p in traderie.offer_prices(raw)]==[2200000,2]
    assert traderie.offer_prices({'currencyGroupPrices':[{'group':0,'nmt':5000,'currency':True}]})[0]['name']=='Shooms'


def test_property_uses_metadata_icon_without_renaming_internal_contract():
    p=traderie.parse_listing_property({'id':1,'property':{'name':'Corrupt','img':'https://cdn.example.com/corrupt.webp'},'type':'bool','bool':True})
    assert p.name=='Corrupt' and p.icon_url=='https://cdn.example.com/corrupt.webp'


def test_failed_offer_write_not_marked_as_success(setup):
    api,c,o=setup;c.accept_offer.side_effect=traderie.TraderieError('Uncertain response')
    data={'offer_id':11,'action':'accept','confirm':True,'revision':web.offer_revision(o)}
    assert post(api,'/api/offers/action',data).status_code==502
    assert web.S.offer_actions=={}


def test_concurrent_offer_action_rejected(setup):
    api,c,o=setup
    with web.OFFER_ACTION_LOCK:
        assert post(api,'/api/offers/action',{'offer_id':11,'action':'accept','confirm':True,'revision':web.offer_revision(o)}).status_code==409
    c.accept_offer.assert_not_called()


def test_offer_parser_preserves_offered_value_and_slot():
    raw={'id':1,'amount':2,'created_at':'2026-10-15T12:00:00Z','prices':[{'name':'Shooms','quantity':2200000,'group':0}],
         'buyer':{'id':7,'username':'Buyer','reviews':162,'rating':5},
         'listing':{'id':9,'amount':10,'seller':{'id':42,'username':'Me'},'item':{'id':55,'name':'Mijusuima'},'properties':[{'id':828,'property':'Species or Slot?','type':'string','string':'Slot'}]}}
    o=traderie.parse_offer(raw)
    assert o.amount==2 and o.prices[0]['quantity']==2200000
    assert o.buyer_reviews==162 and o.buyer_rating==5
    assert o.properties['Species or Slot?'].value=='Slot'
