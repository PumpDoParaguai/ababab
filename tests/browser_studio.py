"""UI navigation, view preferences, responsive layout and motion; offline API."""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright,expect

out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/studio');out.mkdir(parents=True,exist_ok=True)
state={'configured':True,'auth_set':True,'user_id':42,'username':'Teste','slug':'creaturesofsonaria','policy':{},'auto_relist':False,'saved':None}
listings=[{'id':i+1,'item_id':100+i,'item':name,'amount':1,'category':'slots' if i==0 else 'species','eligible':i%2==0,'availability_known':True,'updated':'2026-10-16T00:00:00Z','url':'https://traderie.com/creaturesofsonaria/listing/1','image_url':None,'properties':{'mode':{'name':'Species or Slot?','value':'Slot','type':'string'},'Corrupt':{'name':'Corrupt','value':'True','type':'bool'}} if i==0 else {}} for i,name in enumerate(['Keruku','Aereis','Mijusuima','Ghartokus'])]
routines=[{'id':'r1','item_name':'Keruku','enabled':True,'interval_minutes':37,'template':{'item':'100','amount':'1','makeOffer':True},'cycles':2,'next_run':None,'last_result':'Aguardando próximo ciclo.'}]

def route_api(route):
    path=urlsplit(route.request.url).path
    if path=='/api/state':d={'ok':True,'state':state}
    elif path=='/api/listings':d={'ok':True,'listings':listings,'checked_at':'2026-10-16T00:00:00Z'}
    elif path=='/api/inbox':d={'ok':True,'offers':[],'notifications':[],'counter_supported':True,'sources':{}}
    elif path=='/api/rotation-routines':d={'ok':True,'routines':routines}
    elif path=='/api/catalog/search':d={'ok':True,'items':[{'id':100,'name':'Keruku','category':'species','item_type':'Creatures','properties':[]}],'total':1}
    else:d={'ok':True,'images':{},'items':[]}
    route.fulfill(json=d)

with sync_playwright() as p:
    b=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    page=b.new_page(viewport={'width':1440,'height':1050},reduced_motion='no-preference')
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/api/**',route_api);page.route('https://**/*',lambda r:r.abort())
    page.goto('http://127.0.0.1:8765');page.locator('#btn-listings').click()
    expect(page.locator('.listing-card')).to_have_count(4)
    expect(page.locator('#metric-listings')).to_have_text('4');expect(page.locator('#metric-ready')).to_have_text('2')
    page.locator('#filter-ready').click();expect(page.locator('.listing-card')).to_have_count(2)
    expect(page.locator('#metric-listings')).to_have_text('4')
    page.locator('#filter-ready').click();expect(page.locator('.listing-card')).to_have_count(4)
    page.locator('#view-list').click();expect(page.locator('#listings')).to_have_attribute('data-layout','list')
    page.reload();page.locator('#btn-listings').click()
    expect(page.locator('#view-list')).to_have_attribute('aria-pressed','true')
    page.locator('#view-cards').click()
    page.locator('#nav-schedules').click();expect(page.locator('#panel-routines')).to_be_visible()
    expect(page.locator('#nav-schedules')).to_have_attribute('aria-current','page')
    page.locator('[data-page="account"]').click();expect(page.locator('[data-view="account"]')).to_be_visible()
    page.locator('#tab-listings').click();expect(page.locator('#market-listings')).to_be_visible()
    expect(page.locator('#metric-schedules')).to_have_text('1')
    page.keyboard.press('/');expect(page.locator('#listfilter')).to_be_focused()
    page.keyboard.type('n');expect(page.locator('#editor-backdrop')).to_be_hidden()
    page.locator('#listfilter').fill('');page.locator('#view-cards').focus()
    page.keyboard.press('n');expect(page.locator('#editor-backdrop')).to_be_visible()
    page.keyboard.press('Escape');expect(page.locator('#editor-backdrop')).to_be_hidden()
    page.locator('#motion-toggle').click()
    expect(page.locator('html')).to_have_attribute('data-motion','off')
    assert page.locator('.orbit-mark').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
    page.locator('#motion-toggle').click();expect(page.locator('html')).to_have_attribute('data-motion','on')
    page.emulate_media(reduced_motion='reduce');expect(page.locator('html')).to_have_attribute('data-motion','off')
    assert page.evaluate('document.fonts.check("12px Manrope")')
    page.screenshot(path=str(out/'studio-gallery-desktop.png'),full_page=True)
    page.locator('#view-list').click();page.screenshot(path=str(out/'studio-list-desktop.png'),full_page=True)
    for width in (1024,768,650,390,320):
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),width
        page.locator('#view-cards').click()
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),width
        if width==390:
            page.screenshot(path=str(out/'studio-gallery-mobile.png'),full_page=True)
            page.locator('#menu-toggle').click();expect(page.locator('#sidebar')).to_have_class('sidebar open')
            page.locator('#nav-schedules').click();expect(page.locator('#sidebar')).not_to_have_class('sidebar open')
            expect(page.locator('#panel-routines')).to_be_visible()
            page.locator('#tab-listings').click()
    assert not errors,errors
    b.close()
print('Studio passed: metrics, availability filter, persisted layouts, navigation, keyboard shortcuts, local font, reduced motion, mobile menu and 320–1440px layouts.')
