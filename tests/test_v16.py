"""Teste offline para a interface v1.6 e API de catálogo, sem acesso ao Traderie."""
from pathlib import Path
from unittest import TestCase, mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import traderie

class ImageTests(TestCase):
    def test_image_from_nested_item_cdn(self):
        raw = dict(id='100', updated_at='2026-10-10T00:00:00Z',
                   item={'id':'999', 'name':'Kelpie', 'assets':{'images':{'original':{'src':'https://cdn.example.org/a.webp'}}}})
        lst = traderie.parse_listing(raw)
        self.assertEqual(lst.image_url, 'https://cdn.example.org/a.webp')
        self.assertEqual(lst.itemID, 999)

    def test_relative_image_from_item(self):
        raw = dict(id='2', updated_at='2026-10-10T00:00:00Z', item={'id':22, 'image':'/assets/creature-icon'})
        self.assertEqual(traderie.parse_listing(raw).image_url, 'https://traderie.com/assets/creature-icon')

    def test_dangerous_or_not_image_urls_filtered(self):
        for url in ('http://example.com/nope', 'data:image/png;base64,123', 'https://localhost/private',
                    'https://127.0.0.1/secret', '//evil.net/a', 'javascript:alert(1)',
                    'https://user:pass@assets.example/img.png'):
            with self.subTest(url=url):
                self.assertIsNone(traderie.normalize_image_url(url))
        self.assertIsNone(traderie.find_item_image({'url':'https://example.com/not-an-image'}))

    def test_public_catalog_reading_by_id_and_no_auth_header(self):
        class Response:
            status_code = 200
            headers = {}
            def json(self):
                return {'items':[{'id':'321','name':'one','image':{'url':'https://cdn.example/a.png'}},
                                 {'id':'999','image':'https://cdn.example/b.png'}]}
        client = traderie.TraderieClient(auth='NEVER_EXPOSE_TOKEN')
        client.MIN_INTERVAL = 0
        with mock.patch.object(client._session, 'get', return_value=Response()) as req:
            self.assertEqual(client.get_catalog_image(321), 'https://cdn.example/a.png')
        self.assertEqual(req.call_args.kwargs['headers'], {'Accept':'application/json'})
        self.assertEqual(req.call_args.kwargs['params'], {'id':'321'})

    def test_unknown_catalog_response_stays_empty(self):
        class Response:
            status_code = 404
        client = traderie.TraderieClient()
        client.MIN_INTERVAL = 0
        with mock.patch.object(client._session, 'get', return_value=Response()):
            self.assertIsNone(client.get_catalog_image(11))

try:
    import app as webapp
except ImportError:
    webapp = None

if webapp is not None:
    class AppV16Tests(TestCase):
        def setUp(self):
            self.client = webapp.app.test_client()
            webapp.S.__init__()
            with mock.patch.object(traderie.TraderieClient, 'get_status', return_value='online'):
                resp=self.client.post('/api/config',json={'user_id':'7654','auth':'testtoken'},headers={'Host':'127.0.0.1:8765'})
                self.assertEqual(resp.status_code, 200)

        def post(self, url, obj):
            return self.client.post(url,json=obj,headers={'Host':'127.0.0.1:8765'})
        def get(self,url):
            return self.client.get(url,headers={'Host':'127.0.0.1:8765'})

        def test_busy_status_post(self):
            with mock.patch.object(traderie.TraderieClient, 'set_status') as status:
                self.assertEqual(self.post('/api/online', {'status':'busy'}).get_json()['status'], 'busy')
                status.assert_called_once_with('busy')
            self.assertEqual(self.post('/api/online', {'status':'unavailable'}).status_code,400)

        def test_item_image_query_cached(self):
            with mock.patch.object(traderie.TraderieClient,'get_catalog_image',return_value='https://cdn.example/a.webp') as get_image:
                a=self.get('/api/item-images?ids=321')
                b=self.get('/api/item-images?ids=321')
                self.assertEqual(a.get_json()['images']['321'],'https://cdn.example/a.webp')
                self.assertEqual(b.get_json()['images']['321'],'https://cdn.example/a.webp')
                get_image.assert_called_once_with(321)
            self.assertEqual(self.get('/api/item-images?ids=foobar').status_code,400)
