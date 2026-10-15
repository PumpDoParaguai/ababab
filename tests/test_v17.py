"""Novidades v1.7 testadas offline, sem enviar ações ao Traderie."""
from pathlib import Path
from unittest import TestCase, mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import traderie

class CatalogSearch(TestCase):
    def test_public_catalog_uses_no_token_and_parses_trait_metadata(self):
        class Resp:
            status_code=200
            headers={}
            def json(self):
                return {'items':[{'id':999,'name':'Kindeer','image':'https://cdn.example.org/k.png',
                     'properties':[{'id':850,'name':'Damage','type':'string','options':['Damage','Weight']}]},
                     {'id':20,'name':''}, {'name':'Missing id'}]}
        c=traderie.TraderieClient(auth='SECRET_STAYS_PRIVATE')
        c.MIN_INTERVAL=0
        with mock.patch.object(c._session,'get',return_value=Resp()) as get:
            items=c.search_catalog_items('Kin')
            self.assertEqual(get.call_args.kwargs['headers'],{'Accept':'application/json'})
            self.assertEqual(get.call_args.kwargs['params'],{'search':'Kin','active':'true','properties':'','variants':'','page':'0'})
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['properties'][0]['options'],['Damage','Weight'])

    def test_invalid_query_and_unavailable_catalog(self):
        c=traderie.TraderieClient()
        c.MIN_INTERVAL=0
        for bad in (None,'x'*81):
            with self.assertRaises(ValueError): c.search_catalog_items(bad)
        class Resp:
            status_code=404
            headers={}
        with mock.patch.object(c._session,'get',return_value=Resp()) as get:
            with self.assertRaises(traderie.TraderieError): c.search_catalog_items('Kindeer')
            with self.assertRaises(traderie.TraderieError): c.search_catalog_items('Kindeer')
            self.assertEqual(get.call_count,2)

    def test_malformed_properties_dont_break(self):
        class Resp:
            status_code=200
            headers={}
            def json(self): return {'items':[{'id':9,'name':'A','properties':{'wrong':1}}]}
        c=traderie.TraderieClient()
        c.MIN_INTERVAL=0
        with mock.patch.object(c._session,'get',return_value=Resp()):
            self.assertEqual(c.search_catalog_items('Name')[0]['properties'],[])

    def test_frontend_exposes_selection_and_modal(self):
        root=Path(__file__).resolve().parents[1]/'static'
        html=(root/'index.html').read_text()
        js=(root/'app.js').read_text()
        assert 'editor-species' in html and 'editor-category-tabs' in html
        assert 'offer-backdrop' in html and 'listing-offers-list' in html
        assert 'data-card-offers' in js and 'data-native-counter' in js
        assert 'listing-details"><div class="property-list always-visible' in js

try:
    import app as webapp
except ImportError:
    webapp=None
if webapp is not None:
    class OfferEndpointTests(TestCase):
        def setUp(self):
            webapp.S.__init__()
            self.client=webapp.app.test_client()
            with mock.patch.object(traderie.TraderieClient,'get_status',return_value='online'):
                self.client.post('/api/config',json={'user_id':'333','auth':'dummy'},headers={'Host':'127.0.0.1:8765'})
            self.owned = {77: traderie.Listing(77,'2026-10-14T00:00:00Z',itemName='Kindeer')}
            self.offer = traderie.Offer('Kindeer',44,77,333,'me',444,'OtherPlayer',1,9)
            self.listings=mock.patch.object(traderie.TraderieClient,'get_all_listings',return_value=self.owned)
            self.offers=mock.patch.object(traderie.TraderieClient,'get_offers',return_value={44:self.offer})
            self.listings.start();self.offers.start()
            self.addCleanup(self.listings.stop);self.addCleanup(self.offers.stop)
        def get(self,url): return self.client.get(url,headers={'Host':'127.0.0.1:8765'})
        def post(self,url,data): return self.client.post(url,json=data,headers={'Host':'127.0.0.1:8765'})
        def test_only_owned_offers(self):
            self.assertEqual(self.get('/api/listings/99/offers').status_code,404)
            info=self.get('/api/listings/77/offers').get_json()
            self.assertEqual(info['offers'][0]['buyerUsername'],'OtherPlayer')
        def test_counter_message_checks_identity_and_does_not_accept(self):
            with mock.patch.object(traderie.TraderieClient,'open_conversation') as op, mock.patch.object(traderie.TraderieClient,'send_message') as send, mock.patch.object(traderie.TraderieClient,'accept_offer') as accept:
                self.assertEqual(self.post('/api/offers/counter-message',{'offer_id':44,'message':'Ok','confirm':True}).status_code,200)
                op.assert_called_once()
                send.assert_called_once_with(444,'Ok')
                accept.assert_not_called()
            self.assertEqual(self.post('/api/offers/counter-message',{'offer_id':44,'message':'Ok'}).status_code,400)
            self.assertEqual(self.post('/api/offers/counter-message',{'offer_id':44,'message':'','confirm':True}).status_code,400)
