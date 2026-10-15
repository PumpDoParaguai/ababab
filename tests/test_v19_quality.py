"""Testes offline de integridade das categorias e ofertas (sem conta real)."""
from pathlib import Path
from unittest import TestCase
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import traderie

class OfferClassificationTests(TestCase):
    def test_offer_with_slot_is_slot(self):
        raw={'id':1,'prices':[], 'buyer':{'id':11,'username':'peer'},
            'listing': {'id':2,'amount':1,'seller':{'id':12,'username':'me'},
                'item':{'id':99,'name':'Creature','category':'Creatures'},
                'properties':[{'id':830,'name':'Species or Slot? (Slot)','type':'string','string':'Slot'}]}}
        offer=traderie.parse_offer(raw)
        self.assertEqual(offer.item_category,'slots')
        raw['listing']['properties'][0]['string']='Species'
        self.assertEqual(traderie.parse_offer(raw).item_category,'species')
    def test_offer_category_plushies(self):
        raw={'id':1,'prices':[], 'buyer':{'id':11,'username':'peer'},
            'listing': {'id':2,'seller':{'id':12,'username':'me'},
                'item':{'id':99,'name':'Silly Plushie','category':'plushies'},'properties':[]}}
        self.assertEqual(traderie.parse_offer(raw).item_category,'plushies')
    def test_js_guard_requires_selected_item(self):
        js=(Path(__file__).resolve().parents[1]/'static/app.js').read_text()
        self.assertIn('!editorMatching(editorSelected)',js)
        self.assertIn("o.item_category && o.item_category !== 'other'",js)
        self.assertNotIn("item.category===editorCategory || item.category==='other'",js)

