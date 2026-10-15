import datetime as dt
import os
import time
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402
import traderie  # noqa: E402
from traderie import AuthRequired, Blocked, TraderieClient, TraderieError  # noqa: E402


def fake_response(status=200, data=None, text="", headers=None):
    r = mock.Mock(spec=requests.Response)
    r.status_code = status
    r.reason = "x"
    r.headers = headers or {}
    r.text = text
    if data is None and text:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = data
    return r


def make_client(token="", **kw):
    c = TraderieClient("creaturesofsonaria", token, **kw)
    c.MIN_INTERVAL = 0
    c.GET_RETRIES = 0
    return c


def listing_raw(i, updated="2026-01-01T00:00:00.000Z"):
    return {"id": i, "updated_at": updated, "make_offer": False, "prices": None,
            "item": {"name": "Foo"}, "amount": 1, "properties": [{"id": 1, "property": "Age", "type": "string", "string": "Adult"}]}


JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk"


class PureFunctions(unittest.TestCase):
    def test_relistable_and_eta(self):
        now = dt.datetime(2026, 3, 27, 21, 30, 1, tzinfo=dt.timezone.utc)
        mk = lambda **kw: traderie.Listing(1, "2020-01-01T00:00:00Z", **kw)
        # Antiguidade não é prova da disponibilidade real.
        self.assertFalse(traderie.is_listing_relistable(mk(), now))
        self.assertIsNone(traderie.relist_eta(mk(), now))
        self.assertTrue(traderie.is_listing_relistable(mk(can_refresh=True), now))
        self.assertEqual(traderie.relist_eta(mk(can_refresh=True), now), dt.timedelta(0))
        self.assertFalse(traderie.is_listing_relistable(mk(can_refresh=False), now))
        self.assertTrue(traderie.is_listing_relistable(mk(refresh_available_at="2026-03-27T20:30:01Z"), now))
        self.assertFalse(traderie.is_listing_relistable(mk(refresh_available_at="2026-03-27T22:30:01Z"), now))
        self.assertEqual(traderie.relist_eta(mk(refresh_available_at="2026-03-27T22:30:01Z"), now), dt.timedelta(hours=1))

    def test_refresh_signals_and_average_must_be_explicit(self):
        raw = listing_raw(99)
        raw["updated_at"] = "2020-01-01T00:00:00Z"
        raw["can_refresh"] = True
        raw["item"] = {"id": 44, "name": "Kindeer", "averagePrice": 1800}
        parsed = traderie.parse_listing(raw)
        self.assertTrue(parsed.can_refresh)
        self.assertFalse(hasattr(parsed, "average_value"))
        raw.pop("can_refresh")
        raw["item"].pop("averagePrice")
        raw["prices"] = [{"name": "Shooms", "quantity": 6000, "group": 1}]
        parsed = traderie.parse_listing(raw)
        self.assertIsNone(parsed.can_refresh)
        self.assertFalse(hasattr(parsed, "average_value"))
        raw["nextRefreshAt"] = "2026-03-28T00:00:00Z"
        parsed = traderie.parse_listing(raw)
        self.assertEqual(parsed.refresh_available_at, "2026-03-28T00:00:00Z")

    def test_clean_token_and_jwt(self):
        self.assertEqual(traderie.clean_token('  Authorization: abc.def  '), "abc.def")
        self.assertEqual(traderie.clean_token(None), "")
        self.assertTrue(traderie.looks_like_bare_jwt(JWT))
        self.assertFalse(traderie.looks_like_bare_jwt("Bearer " + JWT))
        self.assertFalse(traderie.looks_like_bare_jwt("abc"))

    def test_clean_slug(self):
        self.assertEqual(traderie.clean_slug("Creatures-Of Sonaria"), "creaturesofsonaria")
        with self.assertRaises(ValueError):
            traderie.clean_slug("--")

    def test_parse_listing_prices_and_props(self):
        raw = listing_raw(5)
        raw["prices"] = [{"group": 1, "quantity": 2, "name": "A"}, {"group": 1, "quantity": 1, "name": "B"}, {"group": 2, "quantity": 3, "name": "C"}]
        l = traderie.parse_listing(raw)
        self.assertFalse(hasattr(l, "price"))
        self.assertEqual(l.properties["Age"].value, "Adult")
        self.assertEqual(l.itemName, "Foo")

    def test_parse_listing_defaults_and_garbage(self):
        self.assertEqual(traderie.parse_listing({"id": 1, "updated_at": "x", "make_offer": True}).listingID, 1)
        self.assertFalse(hasattr(traderie.parse_listing({"id": 1, "updated_at": "x"}), "price"))
        self.assertIsNone(traderie.parse_listing({"id": "abc"}))

    def test_policy_defaults_cover_all_endpoints(self):
        pol = traderie.default_policy()
        self.assertEqual(set(pol), set(traderie.ENDPOINTS))
        for key, (method, _p, _pol) in traderie.ENDPOINTS.items():
            if method != "GET":
                self.assertEqual(pol[key], "private", key)


class ClientBehaviour(unittest.TestCase):
    def test_private_call_without_token_makes_no_request(self):
        c = make_client()
        with mock.patch.object(c._session, "request") as req:
            with self.assertRaises(AuthRequired):
                c.relist(1)
            with self.assertRaises(AuthRequired):
                c.get_notifications()
            req.assert_not_called()

    def test_public_read_sends_no_authorization_header(self):
        c = make_client()
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"user": {"status": "online"}})) as req:
            self.assertEqual(c.get_status(7), "online")
            self.assertNotIn("Authorization", req.call_args.kwargs["headers"])

    def test_token_is_sent_when_set(self):
        c = make_client("tok")
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"msg": "success"})) as req:
            c.relist(9)
            self.assertEqual(req.call_args.kwargs["headers"]["Authorization"], "tok")
            self.assertEqual(req.call_args.kwargs["json"], {"listing": "9"})

    def test_bare_jwt_retries_with_bearer_and_remembers(self):
        c = make_client(JWT)
        seq = [fake_response(401), fake_response(data={"msg": "success"}), fake_response(data={"msg": "success"})]
        with mock.patch.object(c._session, "request", side_effect=seq) as req:
            c.relist(1)
            self.assertEqual(req.call_args_list[0].kwargs["headers"]["Authorization"], JWT)
            self.assertEqual(req.call_args_list[1].kwargs["headers"]["Authorization"], "Bearer " + JWT)
            c.relist(2)  # lembra do formato que funcionou
            self.assertEqual(req.call_args_list[2].kwargs["headers"]["Authorization"], "Bearer " + JWT)

    def test_non_jwt_token_is_not_modified_on_401(self):
        c = make_client("Bearer " + JWT)
        with mock.patch.object(c._session, "request", return_value=fake_response(401)) as req:
            with self.assertRaises(AuthRequired):
                c.relist(1)
            self.assertEqual(req.call_count, 1)

    def test_http_errors(self):
        c = make_client()
        for status, exc in ((401, AuthRequired), (403, AuthRequired), (404, TraderieError), (500, TraderieError)):
            with mock.patch.object(c._session, "request", return_value=fake_response(status)):
                with self.assertRaises(exc):
                    c.get_status(1)

    def test_antibot_page_is_not_reported_as_auth_error(self):
        c = make_client("tok")
        page = fake_response(403, text="<html><title>Just a moment...</title>", headers={"Content-Type": "text/html"})
        with mock.patch.object(c._session, "request", return_value=page):
            with self.assertRaises(Blocked):
                c.get_status(1)
        challenge = fake_response(403, text="x", headers={"cf-mitigated": "challenge"})
        with mock.patch.object(c._session, "request", return_value=challenge):
            with self.assertRaises(Blocked):
                c.get_status(1)

    def test_non_json_response(self):
        c = make_client()
        with mock.patch.object(c._session, "request", return_value=fake_response(200, text="<html>")):
            with self.assertRaises(TraderieError):
                c.get_status(1)

    def test_network_error_becomes_traderie_error(self):
        c = make_client()
        with mock.patch.object(c._session, "request", side_effect=requests.ConnectionError("down")), mock.patch("time.sleep"):
            with self.assertRaises(TraderieError):
                c.get_status(1)

    def test_get_retries_then_succeeds(self):
        c = make_client()
        c.GET_RETRIES = 2
        seq = [fake_response(503), fake_response(200, {"user": {"status": "offline"}})]
        with mock.patch.object(c._session, "request", side_effect=seq), mock.patch("time.sleep"):
            self.assertEqual(c.get_status(1), "offline")

    def test_write_error_payload(self):
        c = make_client("t")
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"error": "nope"})):
            with self.assertRaisesRegex(TraderieError, "nope"):
                c.relist(1)
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"foo": 1})):
            with self.assertRaises(TraderieError):
                c.relist(1)

    def test_pagination_any_page_size(self):
        """Não assume 50 por página: 20+20+5 anúncios devem vir completos."""
        c = make_client()
        c._refresh_profile = (1, time.monotonic(), {"reviews":0,"roles":[]})
        pages = [
            fake_response(data={"listings": [listing_raw(i) for i in range(0, 20)]}),
            fake_response(data={"listings": [listing_raw(i) for i in range(20, 40)]}),
            fake_response(data={"listings": [listing_raw(i) for i in range(40, 45)]}),
            fake_response(data={"listings": []}),
        ]
        with mock.patch.object(c._session, "request", side_effect=pages) as req:
            self.assertEqual(len(c.get_all_listings(1)), 45)
            self.assertEqual(req.call_count, 4)

    def test_pagination_stops_if_api_ignores_page(self):
        c = make_client()
        c._refresh_profile = (1, time.monotonic(), {"reviews":0,"roles":[]})
        same = lambda *a, **k: fake_response(data={"listings": [listing_raw(i) for i in range(50)]})
        with mock.patch.object(c._session, "request", side_effect=same) as req:
            self.assertEqual(len(c.get_all_listings(1)), 50)
            self.assertEqual(req.call_count, 2)  # sem loop infinito

    def test_get_listing_empty(self):
        c = make_client()
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"listings": []})):
            self.assertIsNone(c.get_listing(1))

    def test_notification_without_from_user(self):
        c = make_client("t")
        raw = {"notifications": [{"id": "n1", "message": "hi", "created_at": "x"}, "lixo"]}
        with mock.patch.object(c._session, "request", return_value=fake_response(data=raw)):
            n = c.get_notifications()
            self.assertEqual(len(n), 1)
            self.assertEqual((n[0].fromUserID, n[0].listingID), (None, None))

    def test_offers_parse_and_arg_validation(self):
        c = make_client("t")
        raw = {"offers": [{"id": 1, "prices": [{"group": 1, "quantity": 1, "name": "A"}], "buyer": {"id": 2, "username": "b"},
                           "listing": {"id": 3, "amount": 1, "item": {"id": 4, "name": "I"}, "seller": {"id": 5, "username": "s"}}},
                          {"id": 9}]}
        with mock.patch.object(c._session, "request", return_value=fake_response(data=raw)):
            offers = c.get_offers(to_seller=5)
            self.assertEqual(list(offers), [1])  # a oferta malformada é ignorada
            self.assertFalse(hasattr(offers[1], "offer"))
        with self.assertRaises(ValueError):
            c.get_offers()

    def test_search_user_case_insensitive(self):
        c = make_client()
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"users": [{"username": "Bob", "id": "12"}]})):
            self.assertEqual(c.search_user("bob"), 12)
            self.assertIsNone(c.search_user("alice"))


class PolicyAndDiagnose(unittest.TestCase):
    def test_public_override_allows_anonymous_read(self):
        c = make_client(policy={"notifications": "public"})
        self.assertTrue(c.available("notifications"))
        with mock.patch.object(c._session, "request", return_value=fake_response(data={"notifications": []})) as req:
            self.assertEqual(c.get_notifications(), [])
            req.assert_called_once()

    def test_writes_cannot_be_made_public(self):
        c = make_client(policy={"listings.refresh": "public", "accounts.update": "public"})
        self.assertEqual(c.policy["listings.refresh"], "private")
        self.assertFalse(c.available("accounts.update"))
        with mock.patch.object(c._session, "request") as req:
            with self.assertRaises(AuthRequired):
                c.relist(1)
            req.assert_not_called()

    def _diag(self, anon, tok=None, token=""):
        c = make_client(token)
        by_token = {"": anon}
        if token:
            by_token[token] = tok

        def get(url, params=None, headers=None, timeout=None):
            return by_token[(headers or {}).get("Authorization", "")]()
        with mock.patch.object(c._session, "get", side_effect=get):
            return c, {r["endpoint"]: r for r in c.diagnose(1)}

    def test_diagnose_anonymous_401_marks_private(self):
        c, rows = self._diag(lambda: fake_response(401))
        self.assertEqual(rows["offers"]["policy"], "private")
        self.assertEqual(rows["offers"]["anon"]["verdict"], "auth")
        self.assertIsNone(rows["offers"]["token"])

    def test_diagnose_anonymous_ok_without_token_keeps_policy(self):
        c, rows = self._diag(lambda: fake_response(data={"notifications": []}))
        self.assertEqual(rows["notifications"]["policy"], "private")  # 200 vazio não prova nada

    def test_diagnose_equal_results_with_token_marks_public(self):
        ok = lambda: fake_response(data={"notifications": [1, 2], "listings": [1, 2], "offers": [1, 2],
                                         "conversations": [1, 2], "user": {"status": "online"}})
        c, rows = self._diag(ok, ok, token="tok")
        self.assertEqual(rows["notifications"]["policy"], "public")
        self.assertTrue(c.available("notifications"))

    def test_diagnose_incomplete_anonymous_data_stays_private(self):
        anon = lambda: fake_response(data={"offers": []})
        tok = lambda: fake_response(data={"offers": [1, 2, 3]})
        c, rows = self._diag(anon, tok, token="tok")
        self.assertEqual(rows["offers"]["policy"], "private")
        self.assertIn("incompleto", rows["offers"]["note"])

    def test_diagnose_reports_antibot_and_network(self):
        c, rows = self._diag(lambda: fake_response(403, text="Just a moment", headers={"Content-Type": "text/html"}))
        self.assertEqual(rows["accounts"]["anon"]["verdict"], "blocked")
        c2 = make_client()
        with mock.patch.object(c2._session, "get", side_effect=requests.ConnectionError("down")):
            self.assertEqual(c2.diagnose(1)[0]["anon"]["verdict"], "network")


class VisualParsingV14(unittest.TestCase):
    def test_nested_https_image_and_traits(self):
        raw = {"id": 2, "updated_at": "2026-10-14T00:00:00Z", "make_offer": True,
               "item": {"name": "Stored creature", "images": [{"thumbnail": {"url": "https://cdn.example.test/a.png"}}]},
               "properties": [{"property": "Trait 1", "type": "string", "string": "Speed", "id": 8},
                              {"property": "Slot", "type": "number", "number": 2, "id": 9}]}
        listing = traderie.parse_listing(raw)
        self.assertEqual(listing.image_url, "https://cdn.example.test/a.png")
        self.assertEqual(listing.properties["Trait 1"].value, "Speed")
        self.assertEqual(listing.properties["Slot"].value, "2")

    def test_bad_properties_and_prices_do_not_crash(self):
        raw = {"id": 4, "updated_at": "2026-10-14T00:00:00Z", "item": None,
               "prices": [None, "unexpected", {"name": "Moon Pearl", "quantity": 2}],
               "properties": [None, "unexpected", {"type": "string", "property": "Mutation", "string": "Glowtail"}]}
        listing = traderie.parse_listing(raw)
        self.assertFalse(hasattr(listing, "price"))
        self.assertEqual(listing.properties["Mutation"].value, "Glowtail")
        self.assertIsNone(traderie.parse_listing(None))

    def test_insecure_or_absent_image_has_no_url(self):
        raw = {"id": 7, "updated_at": "2026-10-14T00:00:00Z", "item": {"image": "http://example.test/a.png"}}
        self.assertIsNone(traderie.parse_listing(raw).image_url)


if __name__ == "__main__":
    unittest.main()
