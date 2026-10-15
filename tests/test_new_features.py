"""Testes locais sem rede e sem modificar qualquer anúncio real."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import traderie


class TestCreateDeleteContract(unittest.TestCase):
    def test_observed_endpoints(self):
        self.assertEqual(traderie.ENDPOINTS['listings.create'][:2], ('POST', 'listings/create'))
        self.assertEqual(traderie.ENDPOINTS['listings.delete'][:2], ('POST', 'sell'))

    def test_creation_payload_uses_observed_defaults(self):
        model = {'item':'1002432621767', 'amount':'1', 'itemType':'sub-species',
                 'properties':[{'id':830,'name':'Species or Slot? (Slot)', 'type':'string', 'string':'Slot'}]}
        payload = traderie.validated_creation(model)
        self.assertEqual(payload['item'], model['item'])
        self.assertIs(payload['makeOffer'], True)
        self.assertIs(payload['selling'], True)
        self.assertEqual(payload['properties'], model['properties'])
        self.assertIs(payload['captchaManaged'], False)

    def test_creation_rejects_injected_or_malformed_fields(self):
        base = {'item':'1002432621767','amount':'1'}
        bad_cases = [
            {**base,'Authorization':'leak'},
            {**base,'item': 'notnumeric'},
            {**base,'amount': '0'},
            {**base,'selling':False},
            {**base,'captchaManaged':True},
            {**base,'properties':[{'id': 830, 'name':'Slot', 'type':'string'}]},
            {**base,'properties':[{'id': 830,'name':'Slot','type':'bool','bool':'true'}]},
        ]
        for bad in bad_cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                traderie.validated_creation(bad)

    def test_write_requests_send_exact_endpoints_and_payloads(self):
        c=traderie.TraderieClient('creaturesofsonaria', 'test-token')
        c.MIN_INTERVAL=0
        with mock.patch.object(c,'_request',return_value={'msg':'success','listing':{'id':'123456'}}) as request:
            lid = c.create_listing({'item':'1002432621767','amount':'1'})
            self.assertEqual(lid,123456)
            args,kwargs = request.call_args
            self.assertEqual(args, ('listings.create',))
            self.assertEqual(kwargs['body']['properties'], [])
        with mock.patch.object(c,'_request',return_value={'msg':'success'}) as request:
            c.delete_listing(123456)
            self.assertEqual(request.call_args.args, ('listings.delete',))
            self.assertEqual(request.call_args.kwargs['body'], {'listing':'123456', 'selling':True, 'remove':True, 'endTime':None})

    def test_delete_does_not_assume_ambiguous_response_success(self):
        c=traderie.TraderieClient(auth='token')
        with mock.patch.object(c,'_request',return_value={'data': {}}):
            with self.assertRaises(traderie.TraderieError):
                c.delete_listing(1)

    def test_url_and_property_types(self):
        raw={'id':4,'updated_at':'2026-10-10T00:00:00Z',
             'item':{'id':10,'name':'Creature', 'images':[{'thumbnail': '/art/creature.webp'}]},
             'properties':[{'id':831,'name':'Weight','type':'number','number':65}]}
        x=traderie.parse_listing(raw)
        self.assertEqual(x.image_url,'https://traderie.com/art/creature.webp')
        self.assertEqual(x.itemID,10)
        self.assertEqual(x.properties['Weight'].type,'number')

    def test_no_insecure_urls(self):
        for image in ['http://bad.example/icon.png','//bad.example/icon.png','javascript:alert(1)']:
            with self.subTest(image=image):
                raw={'id':1,'updated_at':'2026-10-10T00:00:00Z','item':{'name':'A','image':image}}
                self.assertIsNone(traderie.parse_listing(raw).image_url)

    def test_compact_nav_and_motion_accessibility(self):
        html=(ROOT/'static/index.html').read_text()
        css=(ROOT/'static/style.css').read_text()
        for section in ('market','account'):
            self.assertIn(f'data-view="{section}"',html)
        self.assertIn('id="panel-routines"',html)
        self.assertNotIn('data-view="trades"', html)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('image-summary',html)


if __name__ == '__main__':
    unittest.main()
