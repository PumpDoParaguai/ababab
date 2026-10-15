"""Regressão v1.9 — categorias, metadados, extração pública sem token."""
from pathlib import Path
import sys
from unittest import TestCase, mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import traderie


class V19Categories(TestCase):
    def test_categories_and_slots(self):
        self.assertEqual(traderie.item_category({'category': {'slug':'plushies'}}), 'plushies')
        self.assertEqual(traderie.item_category({'category': 'material palettes'}), 'palettes')
        self.assertEqual(traderie.item_category({'type':'Creatures'}), 'species')
        self.assertEqual(traderie.item_category({'name': 'Shadow Plushie'}), 'other')
        creature={'id':20,'updated_at':'2026-10-14T00:00:00Z','item':{'id':12,'name':'Geortharoc','category':'Creatures'},
          'properties':[{'id':830,'property':'Species or Slot? (Slot)','type':'string','string':'Slot'}]}
        parsed=traderie.parse_listing(creature)
        self.assertEqual(parsed.item_category,'slots')
        creature['properties'][0]['string']='Species'
        self.assertEqual(traderie.parse_listing(creature).item_category,'species')
        creature['item']={'id':12,'name':'Plushie','category':'plushies'}
        self.assertEqual(traderie.parse_listing(creature).item_category,'plushies')




    def test_catalog_preserves_category_and_values(self):
        c=traderie.TraderieClient()
        c.MIN_INTERVAL=0
        class Response:
            status_code=200
            headers={'Content-Type':'application/json'}
            def json(self):
                return {'items':[{'id':99,'name':'Test Plushie','category':'plushies', 'communityValue':120,
                    'properties':[]}]}
        with mock.patch.object(c._session,'get',return_value=Response()):
            found=c.search_catalog_items('Plushie')
        self.assertEqual(found[0]['category'],'plushies')
        self.assertNotIn('community_value',found[0])

    def test_ui_has_separate_categories_and_selects_only(self):
        root=Path(__file__).resolve().parents[1]/'static'
        html=(root/'index.html').read_text()
        js=(root/'app.js').read_text()
        for category in ('species','slots','plushies','palettes'):
            self.assertIn('data-editor-category="'+category+'"',html)
            self.assertIn('data-list-category="'+category+'"',html)
        self.assertNotIn('editor-json',html)
        self.assertIn('data-editor-prop',js)
        self.assertNotIn('valor comunitário',js)
