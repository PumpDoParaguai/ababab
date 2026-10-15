"""Chat polling, draft preservation and native counter actions with offline fixtures."""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import sync_playwright,expect

out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/traderie-chat');out.mkdir(parents=True,exist_ok=True)
state={'configured':True,'auth_set':True,'user_id':42,'username':'Teste','slug':'creaturesofsonaria','policy':{},'auto_relist':False,'saved':None}
offer={'offerID':11,'listingID':9,'buyerID':7,'sellerID':42,'buyerUsername':'Comprador','itemName':'Mijusuima','amount':1,'prices':[{'group':0,'quantity':800000,'name':'Shooms'}],'properties':{},'revision':'reviewed'}
offers=[offer];messages=[{'msgID':str(i),'text':f'Mensagem {i}','fromID':7,'toID':42,'created_at':f'2026-10-15T12:{i:02}:00Z'} for i in range(20)]
sends=[];counters=[];chat_reads=[];fail_send=True;fail_counter=True;fail_read=False

def route_api(route):
    req=route.request;path=urlsplit(req.url).path;q=parse_qs(urlsplit(req.url).query)
    if path=='/api/state':d={'ok':True,'state':state}
    elif path=='/api/inbox':d={'ok':True,'offers':offers,'notifications':[],'unread_count':len(offers),'counter_supported':True,'sources':{}}
    elif path=='/api/offers/chat':
        if req.method=='POST':
            sends.append(req.post_data_json)
            if fail_send:route.fulfill(status=502,json={'ok':False,'error':'Envio recusado'});return
            messages.append({'msgID':'out','text':sends[-1]['message'],'fromID':42,'toID':7,'created_at':'2026-10-15T12:30:00Z'})
            d={'ok':True,'message':'Mensagem enviada.'}
        else:
            chat_reads.append(q)
            if fail_read:route.fulfill(status=502,json={'ok':False,'error':'Falha temporária'});return
            d={'ok':True,'user_id':7,'username':'Comprador','conversation_id':70,'offer':None if 'conversation_id' in q else offer,'messages':messages}
    elif path=='/api/offers/action':
        counters.append(req.post_data_json)
        if fail_counter:route.fulfill(status=409,json={'ok':False,'error':'A oferta mudou.'});return
        offers.clear();d={'ok':True,'message':'Contraproposta enviada.'}
    elif path=='/api/rotation-routines':d={'ok':True,'routines':[]}
    else:d={'ok':True,'items':[],'listings':[],'offers':[]}
    route.fulfill(json=d)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100},reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/api/**',route_api)
    page.route('https://**/*',lambda r:r.abort())
    page.goto('http://127.0.0.1:8765');page.locator('#btn-inbox').click()
    page.locator('[data-native-counter="11"]').click()
    expect(page.locator('#trade-counter-shooms')).to_be_focused()
    expect(page.locator('.trade-bubble')).to_have_count(20)
    expect(page.locator('.trade-bubble').first).to_contain_text('Mensagem 0')
    page.locator('#trade-chat-text').fill('Meu rascunho')
    page.locator('#trade-chat-messages').evaluate('(e)=>e.scrollTop=0')
    messages.append({'msgID':'new','text':'Nova mensagem automática','fromID':7,'toID':42,'created_at':'2026-10-15T12:29:00Z'})
    expect(page.locator('.trade-bubble')).to_have_count(21,timeout=8000)
    expect(page.locator('#trade-chat-text')).to_have_value('Meu rascunho')
    assert page.locator('#trade-chat-messages').evaluate('(e)=>e.scrollTop')==0
    assert chat_reads[-1]['conversation_id']==['70']
    page.locator('#trade-chat-send').click()
    expect(page.locator('#trade-chat-status')).to_contain_text('Envio recusado')
    expect(page.locator('#trade-chat-text')).to_have_value('Meu rascunho')
    fail_send=False;page.locator('#trade-chat-send').click()
    expect(page.locator('#trade-chat-text')).to_have_value('')
    expect(page.locator('.outgoing')).to_contain_text('Meu rascunho')
    assert sends[-1]['conversation_id']==70 and sends[-1]['user_id']==7
    page.locator('#trade-counter-shooms').fill('900000')
    page.once('dialog',lambda d:d.dismiss());page.locator('#trade-counter-send').click()
    assert not counters
    page.on('dialog',lambda d:d.accept())
    page.locator('#trade-counter-send').click()
    expect(page.locator('#trade-counter-status')).to_contain_text('A oferta mudou')
    expect(page.locator('#trade-counter-shooms')).to_have_value('900000')
    page.screenshot(path=str(out/'chat-counter-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.locator('.trade-chat-modal').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    page.screenshot(path=str(out/'chat-counter-mobile.png'),full_page=True)
    fail_counter=False;page.locator('#trade-chat-reload').click()
    expect(page.locator('#trade-chat-offer-summary')).to_contain_text('800.000')
    page.locator('#trade-counter-send').click()
    expect(page.locator('#trade-chat-status')).to_contain_text('Contraproposta enviada')
    expect(page.locator('#trade-counter-editor')).to_be_hidden()
    assert counters[-1]=={'offer_id':11,'action':'counter','shooms':900000,'confirm':True,'revision':'reviewed'}
    fail_read=True;page.locator('#trade-chat-reload').click()
    expect(page.locator('#trade-chat-status')).to_contain_text('Falha temporária')
    expect(page.locator('.trade-bubble')).to_have_count(22)
    page.keyboard.press('Escape');expect(page.locator('#trade-chat-backdrop')).to_be_hidden()
    assert not errors,errors
    browser.close()
print('Chat browser passed: automatic updates, chronological messages, draft/scroll preservation, failure recovery, native counter confirmation and mobile.')
