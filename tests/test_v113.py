"""Regressões v1.13: catálogo exclusivamente público, tela sem preços e relógio em tempo real."""
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import traderie

class RevampTests(unittest.TestCase):

    def test_new_listing_has_no_prices_ids_or_negotiation_page(self):
        html=(ROOT/'static/index.html').read_text()
        self.assertIn('id="editor-item-id" type="hidden"',html)
        self.assertNotIn('editor-pricing',html)
        self.assertNotIn('NYP',html)
        self.assertNotIn('editor-preview-value',html)
        self.assertNotIn('data-page="trades"',html)
        self.assertNotIn('data-view="trades"',html)
        self.assertIn('data-view="market"',html)


    def test_server_availability_is_authoritative(self):
        from datetime import datetime,timezone,timedelta
        now=datetime(2026,10,15,tzinfo=timezone.utc)
        def make(**kw):return traderie.Listing(listingID=1,updated='2026-10-01T00:00:00Z',**kw)
        self.assertFalse(traderie.is_listing_relistable(make(can_refresh=False),now))
        self.assertFalse(traderie.is_listing_relistable(make(),now))
        self.assertTrue(traderie.is_listing_relistable(make(can_refresh=True),now))
        self.assertTrue(traderie.is_listing_relistable(make(refresh_available_at='2026-10-14T00:00:00Z'),now))

if __name__=='__main__': unittest.main()
