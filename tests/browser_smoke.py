"""Run with the local app open. Browser API responses are fixtures, never account writes.

    .venv/bin/python tests/browser_smoke.py /workspace/outputs
"""
import datetime as dt
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import sync_playwright, expect

OUT = Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/traderie-browser')
OUT.mkdir(parents=True,exist_ok=True)
now=dt.datetime.now(dt.timezone.utc)
state={'configured':True,'auth_set':True,'user_id':42,'username':'Conta de teste',
       'policy':{},'slug':'creaturesofsonaria','auto_relist':False,'check_minutes':30,
       'availability_poll_seconds':30,'last_auto_result':None,'saved':None}
items=[{'id':1219367524,'name':'Mijusuima','category':'species','image_url':None,
        'item_type':'Creatures','properties':[{'id':828,'name':'Species or Slot?','type':'string','options':['Species','Slot']},{'id':850,'name':'Traits','type':'string','options':['Bite','Weight']}], 'source':'Catálogo oficial'},
       {'id':2358579145,'name':'Ghartokus','category':'species','properties':[]},
       {'id':900,'name':'Aerix Plushie','category':'plushies','properties':[]},
       {'id':901,'name':'Ocean Palette','category':'palettes','properties':[]}]
listings=[{'id':77,'item_id':1219367524,'item':'Mijusuima','amount':1,'category':'slots',
           'updated':(now-dt.timedelta(seconds=10)).isoformat(),'properties':{},
           'eligible':False,'refresh_available_at':(now+dt.timedelta(seconds=55)).isoformat(),
           'availability_known':True,'image_url':None,'url':'https://traderie.com/creaturesofsonaria/listing/77'},
          {'id':78,'item_id':2358579145,'item':'Ghartokus','amount':2,'category':'species',
           'updated':(now-dt.timedelta(hours=25)).isoformat(),'properties':{},
           'eligible':True,'availability_known':True,'image_url':None,'url':'https://traderie.com/creaturesofsonaria/listing/78'}]
created=[]
catalog_calls=[]
fail_catalog=False

def route_api(route):
    global fail_catalog
    req=route.request
    path=urlsplit(req.url).path
    q=parse_qs(urlsplit(req.url).query)
    if path=='/api/state': data={'ok':True,'state':state}
    elif path=='/api/listings': data={'ok':True,'listings':listings,'checked_at':now.isoformat()}
    elif path=='/api/catalog/search':
        catalog_calls.append(req.url)
        if fail_catalog:
            route.fulfill(status=503,json={'ok':False,'error':'Catálogo indisponível para este teste.'});return
        category=q.get('category',['species'])[0]
        category='species' if category=='slots' else category
        query=q.get('q',[''])[0].casefold()
        rows=[i for i in items if i['category']==category and query in i['name'].casefold()]
        data={'ok':True,'items':rows,'total':len(rows),'catalog_available':True}
    elif path=='/api/listings/create':
        created.append(req.post_data_json)
        data={'ok':True,'listing_id':123}
    elif path=='/api/item-images': data={'ok':True,'images':{},'sources':{}}
    elif path=='/api/rotation-routines': data={'ok':True,'routines':[]}
    else: data={'ok':True,'offers':[],'listings':[]}
    route.fulfill(json=data)

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000},reduced_motion='reduce')
    errors=[]
    page.on('pageerror',lambda err:errors.append(str(err)))
    page.route('**/api/**',route_api)
    page.route('https://**/*',lambda route:route.abort())
    page.goto('http://127.0.0.1:8765')
    expect(page.locator('#sidebar-user')).to_have_text('Conta de teste')
    page.locator('#btn-listings').click()
    expect(page.locator('.listing-card')).to_have_count(2)
    before=page.locator('[data-updated]').first.inner_text()
    expect(page.locator('[data-updated]').first).not_to_have_text(before,timeout=4000)
    assert page.locator('[data-page="trades"]').count()==0
    for selector in ['body','.sidebar','.listing-card','.auto-relist-bar']:
        color=page.locator(selector).first.evaluate('(el)=>getComputedStyle(el).backgroundColor')
        channels=color.removeprefix('rgb(').removesuffix(')').split(', ')
        assert len(set(channels))==1,(selector,color)
    page.screenshot(path=str(OUT/'painel-desktop.png'),full_page=True)
    page.locator('#btn-open-create').click()
    expect(page.locator('.editor-result')).to_have_count(2)
    assert '1219367524' not in page.locator('#editor-backdrop').inner_text()
    assert 'preço' not in page.locator('#editor-backdrop').inner_text().lower()
    page.locator('[data-editor-select="1219367524"]').click()
    expect(page.locator('#editor-preview-name')).to_have_text('Mijusuima')
    page.locator('[data-editor-category="slots"]').click()
    expect(page.locator('#editor-prop-850')).to_be_visible()
    assert page.locator('#editor-prop-850 option').all_text_contents()==['Não informar','Bite','Weight']
    page.locator('#editor-prop-850').select_option('Bite')
    page.locator('#editor-amount').fill('2')
    page.screenshot(path=str(OUT/'novo-anuncio-desktop.png'),full_page=True)
    page.on('dialog',lambda dialog:dialog.accept())
    page.locator('#editor-submit').click()
    expect(page.locator('#editor-backdrop')).to_be_hidden()
    assert created and created[0]['confirm'] is True
    template=created[0]['template']
    assert template['item']=='1219367524' and template['amount']=='2'
    assert template['makeOffer'] is True and template['free'] is False
    assert template['itemType']=='Creatures'
    assert template['properties'][0]['id']==828
    assert template['properties'][1]['string']=='Bite'
    assert not {'price','prices','average_value','community_value'} & template.keys()
    page.locator('#btn-open-create').click()
    page.locator('#editor-search').fill('Miju')
    page.locator('[data-editor-category="plushies"]').click()
    expect(page.locator('.editor-result')).to_have_count(0)
    page.locator('#editor-search').fill('')
    expect(page.locator('.editor-result')).to_have_count(1)
    expect(page.locator('.editor-result')).to_contain_text('Aerix Plushie')
    fail_catalog=True
    page.locator('[data-editor-category="palettes"]').click()
    expect(page.locator('#editor-retry')).to_be_visible()
    fail_catalog=False
    page.locator('#editor-retry').click()
    expect(page.locator('.editor-result')).to_contain_text('Ocean Palette')
    page.keyboard.press('Escape')
    expect(page.locator('#btn-open-create')).to_be_focused()
    page.set_viewport_size({'width':390,'height':844})
    page.locator('#btn-open-create').click()
    expect(page.locator('.editor-result')).to_have_count(2)
    page.locator('[data-editor-select="1219367524"]').click()
    page.screenshot(path=str(OUT/'novo-anuncio-mobile.png'),full_page=False)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    modal=page.locator('.editor-modal')
    assert modal.evaluate('(el)=>el.scrollWidth<=el.clientWidth')
    assert not errors,errors
    browser.close()
print('Browser passed: selection, publication payload, category isolation, retry, live clock, neutral blacks, keyboard, desktop/mobile.')
