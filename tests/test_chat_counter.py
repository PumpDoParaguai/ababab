"""Native counter contracts and chat ownership/lifecycle, entirely offline."""
from unittest.mock import Mock
import pytest
import app as web
import traderie
from test_inbox import setup, post, HOST


def real_client():
    return traderie.TraderieClient('creaturesofsonaria', auth='offline-test')


def test_counter_payload_preserves_native_chain(setup):
    _,_,offer=setup
    offer.root_offer_id=3
    client=real_client();client._request=Mock(return_value={})
    client.counter_offer(offer,900000)
    client._request.assert_called_once_with('offers.create',body={
        'listing':'9','touch_trading':False,'need_materials':False,'amount':None,
        'bells':0,'nmt':0,'items':[{'group':0,'nmt':900000,'currency':True}],
        'seller':'7','parent_user':'7','parent_offer':3,'last_offer':11})
    assert traderie.ENDPOINTS['offers.create']==('POST','offers','private')


def test_first_counter_and_stock_quantity(setup):
    _,_,o=setup;o.stock=True;o.stock_available=3;o.amount=2
    c=real_client();c._request=Mock(return_value={'msg':'success'})
    c.counter_offer(o,500)
    payload=c._request.call_args.kwargs['body']
    assert payload['parent_offer']==o.offerID and payload['amount']==2
    o.stock_available=1
    with pytest.raises(ValueError):c.counter_offer(o,500)
    assert c._request.call_count==1


@pytest.mark.parametrize('value',[0,-1,1.5,True,'900000',2147483648,None])
def test_invalid_counter_never_writes(setup,value):
    api,c,o=setup
    r=post(api,'/api/offers/action',{'offer_id':11,'action':'counter','shooms':value,'confirm':True,'revision':web.offer_revision(o)})
    assert r.status_code==400;c.counter_offer.assert_not_called()


def test_native_counter_is_single_explicit_action(setup):
    api,c,o=setup
    data={'offer_id':11,'action':'counter','shooms':900000,'confirm':True,'revision':web.offer_revision(o)}
    assert post(api,'/api/offers/action',data).json['ok']
    assert post(api,'/api/offers/action',data).status_code==409
    c.counter_offer.assert_called_once_with(o,900000)
    c.send_message.assert_not_called();c.open_conversation.assert_not_called()


def test_counter_changed_or_failed_is_not_reported_as_success(setup):
    api,c,o=setup
    data={'offer_id':11,'action':'counter','shooms':900000,'confirm':True,'revision':'old'}
    assert post(api,'/api/offers/action',data).status_code==409;c.counter_offer.assert_not_called()
    data['revision']=web.offer_revision(o);c.counter_offer.side_effect=traderie.TraderieError('API refused')
    assert post(api,'/api/offers/action',data).status_code==502
    assert not web.S.offer_actions


def test_counter_rejects_upstream_error(setup):
    _,_,o=setup;c=real_client();c._request=Mock(return_value={'error':'Offer closed'})
    with pytest.raises(traderie.TraderieError):c.counter_offer(o,900000)
    c._request.assert_called_once()


def test_parse_chain_and_stock():
    o=traderie.parse_offer({'id':11,'root_offer':{'id':'3'},'amount':2,'buyer':{'id':7},
        'listing':{'id':9,'stock':True,'amount':10,'seller':{'id':42},'item':{'id':55}}})
    assert o.root_offer_id==3 and o.stock and o.stock_available==10 and o.amount==2


def chat_setup(c):
    conversation=traderie.Conversation(70,7,{'id':70,'users':['42','7'],'active':True})
    c.get_conversations.side_effect=lambda active,uid:{7:conversation} if active else {}
    c.get_messages.return_value=[traderie.Message('m1','Hello',7,42,'2026-10-15T12:00:00Z')]
    return conversation


def test_chat_continues_after_offer_closes(setup):
    api,c,o=setup;conversation=chat_setup(c)
    r=api.get('/api/offers/chat?offer_id=11',headers=HOST)
    assert r.json['conversation_id']==70 and r.json['offer']['revision']==web.offer_revision(o)
    c.get_offers.reset_mock();c.get_offers.return_value={}
    r=api.get('/api/offers/chat?conversation_id=70&user_id=7',headers=HOST)
    assert r.json['messages'][0]['text']=='Hello';c.get_offers.assert_not_called()
    assert post(api,'/api/offers/chat',{'conversation_id':70,'user_id':7,'action':'send','message':'Obrigado'}).json['ok']
    c.send_message.assert_called_once_with(7,'Obrigado',conversation)


def test_wrong_conversation_or_account_never_sends(setup):
    api,c,o=setup;chat_setup(c)
    assert post(api,'/api/offers/chat',{'conversation_id':999,'user_id':7,'action':'send','message':'Test'}).status_code==400
    o.sellerID=100
    assert api.get('/api/offers/chat?offer_id=11',headers=HOST).status_code==400
    c.send_message.assert_not_called()


def test_chat_rejects_overlong_text(setup):
    api,c,o=setup;chat_setup(c)
    assert post(api,'/api/offers/chat',{'conversation_id':70,'user_id':7,'action':'send','message':'a'*501}).status_code==400
    c.send_message.assert_not_called()


def test_chat_account_switched_during_fetch(setup):
    api,c,o=setup;chat_setup(c)
    def messages(*args):web.S.user_id=90;return []
    c.get_messages.side_effect=messages
    assert api.get('/api/offers/chat?offer_id=11',headers=HOST).status_code==409


def test_message_contract_and_chronological_order():
    c=real_client();conversation=traderie.Conversation(70,7,{'id':70,'users':['42','7']})
    c._request=Mock(return_value={'messageId':'new'})
    c.send_message(7,'Olá',conversation)
    c._request.assert_called_once_with('messages.send',body={'body':{'to':'7','content':'Olá','conversation':conversation.payload}})
    c._request=Mock(return_value={'messages':[
        {'id':'second','content':'2','from':'7','to':'42','created_at':'2026-10-15T12:01:00Z'},
        {'id':'first','content':'1','from':'42','to':'7','created_at':'2026-10-15T12:00:00Z'}]})
    assert [m.msgID for m in c.get_messages(7,70)]==['first','second']


def test_conversation_membership_checked_on_raw_response():
    c=real_client();c._request=Mock(return_value={'conversations':[
        {'id':70,'users':['42','7']},{'id':80,'users':['99','8']}]})
    assert list(c.get_conversations(True,42))==[7]


def test_verified_offer_chat_can_start_after_counter_closed_offer(setup):
    api,c,o=setup;c.get_conversations.return_value={};c.get_messages.return_value=[]
    assert api.get('/api/offers/chat?offer_id=11',headers=HOST).json['ok']
    c.get_offers.return_value={}
    assert post(api,'/api/offers/chat',{'offer_id':11,'action':'start','confirm':True}).json['ok']
    c.open_conversation.assert_called_once_with(7,'Buyer',11)
    web.S.chat_partners={}
    assert post(api,'/api/offers/chat',{'offer_id':11,'action':'start','confirm':True}).status_code==400
    c.open_conversation.assert_called_once()
