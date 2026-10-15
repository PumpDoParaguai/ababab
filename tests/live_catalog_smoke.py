"""Opt-in, read-only verification against the official catalog. Run with app.py open."""
from pathlib import Path
import os
import sys
from playwright.sync_api import sync_playwright, expect

out=Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/traderie-live-browser')
out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];writes=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda req:writes.append(req.url) if req.method!='GET' else None)
    page.goto('http://127.0.0.1:8765')
    page.wait_for_function("state.configured || !document.getElementById('connect-backdrop').classList.contains('hidden')")
    if page.locator('#connect-cancel').is_visible():
        page.locator('#connect-cancel').click()
    else:
        expect(page.locator('#sidebar-user')).not_to_have_text('Desconectado',timeout=3000)
    page.locator('#btn-open-create').click()
    expect(page.locator('.editor-result')).to_have_count(24,timeout=20000)
    page.locator('#editor-more').click()
    expect(page.locator('.editor-result')).to_have_count(48,timeout=20000)
    page.locator('#editor-search').fill('Miju')
    expect(page.locator('.editor-result')).to_have_count(1,timeout=20000)
    page.locator('.editor-result').click()
    page.locator('[data-editor-category="slots"]').click()
    expect(page.locator('#editor-results')).to_have_attribute('aria-busy','false',timeout=20000)
    page.locator('#editor-prop-135').check()
    payload=page.evaluate('buildEditorTemplate()')
    assert payload['itemType']=='Creatures'
    assert any(p['id']==828 and p['string']=='Slot' for p in payload['properties'])
    assert any(p['id']==135 and p['bool'] is True for p in payload['properties'])
    assert not {'price','prices'} & payload.keys()
    page.locator('.editor-details').evaluate('(el)=>el.scrollTop=0')
    page.screenshot(path=str(out/'catalogo-real.png'))
    assert not errors,errors
    assert not writes,writes
    browser.close()
print('Live catalog passed: 24 -> 48 items; search; real species/slot and mutation properties; correct creation payload; no writes.')
