"""Browser coverage for the personal activity center using mocked HTTP only."""
import datetime as dt
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/traderie-inbox');out.mkdir(parents=True,exist_ok=True)
now=dt.datetime.now(dt.timezone.utc).isoformat()
state={'configured':True,'auth_set':True,'user_id':42,'username':'Conta de teste','slug':'creaturesofsonaria','policy':{},'auto_relist':False,'saved':None}
properties={'corrupt':{'name':'Corrupt','value':'True','type':'bool','icon_url':'https://cdn.example.test/corrupt.webp'},'mode':{'name':'Species or Slot?','value':'Slot','type':'string'}}
offers=[{'offerID':11,'listingID':9,'buyerID':7,'sellerID':42,'buyerUsername':'Comprador A','itemName':'Mijusuima','itemID':55,'amount':1,'prices':[{'group':0,'quantity':2200000,'name':'Shooms'}],'created_at':now,'properties':properties,'revision':'rev-11','buyer_rating':5,'buyer_reviews':162}]
notifications=[{'notificationID':'n1','text':'Você recebeu uma oferta','date':now,'fromUserID':7,'listingID':9,'offerID':11,'read':False}]
actions=[];marked=[];reads=[];fail_action=False;fail_sync=False

def route_api(route):
    global fail_action
    req=route.request;path=urlsplit(req.url).path
    if path=='/api/state':data={'ok':True,'state':state}
    elif path=='/api/inbox':
        reads.append(1)
        if fail_sync:route.fulfill(status=502,json={'ok':False,'error':'Falha de conexão'});return
        data={'ok':True,'offers':offers,'notifications':notifications,'unread_count':sum(not n['read'] for n in notifications),'counter_supported':False,'sources':{'offers':{'checked_at':now,'error':None},'notifications':{'checked_at':now,'error':None}}}
    elif path=='/api/offers/action':
        payload=req.post_data_json;actions.append(payload)
        if fail_action:route.fulfill(status=409,json={'ok':False,'error':'A oferta mudou. Atualize a central.'});return
        offers[:]=[o for o in offers if o['offerID']!=payload['offer_id']]
        data={'ok':True,'message':'Oferta aceita.' if payload['action']=='accept' else 'Oferta recusada.'}
    elif path=='/api/notifications/read':
        marked.append(req.post_data_json)
        for n in notifications:
            if n['notificationID'] in marked[-1]['ids']:n['read']=True
        data={'ok':True}
    elif path=='/api/listings/9/offers':data={'ok':True,'offers':offers}
    elif path=='/api/listings':data={'ok':True,'listings':[],'checked_at':now}
    elif path=='/api/rotation-routines':data={'ok':True,'routines':[]}
    elif path=='/api/offers/chat':data={'ok':True,'messages':[],'conversation_exists':True,'partner_username':'Comprador','partner_id':7}
    else:data={'ok':True,'items':[],'offers':[]}
    route.fulfill(json=data)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/api/**',route_api)
    page.route('https://**/*',lambda r:r.abort()) # Every CDN failure must resolve to the packaged icon.
    page.goto('http://127.0.0.1:8765')
    expect(page.locator('#inbox-badge')).to_have_text('1')
    assert page.locator('.market-heading').count()==0
    page.locator('#btn-inbox').click()
    expect(page.locator('#inbox-offers .incoming-offer')).to_have_count(1)
    expect(page.locator('.offered-value')).to_have_text('2.200.000 × Shooms')
    expect(page.locator('#inbox-offers')).not_to_contain_text('Species or Slot')
    expect(page.locator('.slot-chip')).to_have_text('Slot')
    image=page.locator('.mutation-icon').first
    expect(image).to_have_attribute('src','/static/icons/corrupt.svg')
    assert image.evaluate('(img)=>img.complete&&img.naturalWidth>0')
    assert page.locator('#inbox-offers .mutation-symbol').count()==0
    page.screenshot(path=str(out/'notificacoes-desktop.png'),full_page=True)
    assert not actions
    expect(page.locator('.external-counter')).to_have_attribute('href','https://traderie.com/creaturesofsonaria/listing/9')
    assert page.locator('[data-native-counter]').count()==0
    # New notification arrives by the automatic browser poll, without reload.
    notifications.append({'notificationID':'n2','text':'Nova oferta de teste','date':now,'listingID':9,'read':False})
    expect(page.locator('.inbox-notice')).to_have_count(2,timeout=8000)
    expect(page.locator('#ui-toast')).to_contain_text('Nova atividade')
    page.locator('.notifcheck').first.check()
    page.locator('#inbox-read').click()
    expect(page.locator('.inbox-notice.unread')).to_have_count(1)
    assert marked==[{'ids':['n1']}]
    dialogs=[]
    def dialog(d):dialogs.append(d.message);d.accept()
    page.on('dialog',dialog)
    fail_action=True
    page.locator('[data-inbox-action="accept"]').click()
    expect(page.locator('[data-offer-action-status="11"]')).to_contain_text('oferta mudou')
    expect(page.locator('[data-inbox-action="accept"]')).to_be_enabled()
    assert '2.200.000' in dialogs[-1] and 'Comprador A' in dialogs[-1]
    fail_action=False
    page.locator('[data-inbox-action="accept"]').click()
    expect(page.locator('#inbox-offers .incoming-offer')).to_have_count(0)
    assert actions[-1]=={'offer_id':11,'action':'accept','confirm':True,'revision':'rev-11'}
    offers.append({'offerID':12,'listingID':9,'buyerID':8,'sellerID':42,'buyerUsername':'Comprador B','itemName':'Mijusuima','itemID':55,'amount':1,'prices':[{'group':0,'quantity':12,'name':'Shooms'}],'properties':properties,'created_at':now,'revision':'rev-12'})
    page.locator('#inbox-refresh').click()
    expect(page.locator('#inbox-offers .incoming-offer')).to_have_count(1)
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(out/'notificacoes-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    assert page.locator('.inbox-modal').evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    page.locator('[data-inbox-action="decline"]').click()
    expect(page.locator('#inbox-offers .incoming-offer')).to_have_count(0)
    assert actions[-1]['action']=='decline'
    page.keyboard.press('Escape')
    expect(page.locator('#btn-inbox')).to_be_focused()
    page.locator('#btn-inbox').click()
    fail_sync=True
    page.locator('#inbox-refresh').click()
    expect(page.locator('#inbox-status')).to_contain_text('Falha de conexão')
    assert not errors,errors
    browser.close()
print('Inbox browser passed: background updates, dedup, offer amounts, accept/decline, stale failure, mark read, local icons, simple labels, keyboard and mobile.')
