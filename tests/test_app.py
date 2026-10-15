import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as appmod  # noqa: E402
import traderie  # noqa: E402

HOST = {"Host": "127.0.0.1:8765"}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        patches = [mock.patch.object(appmod, "CONFIG_FILE", tmp / "config.json"),
                   mock.patch.object(appmod, "POLICY_FILE", tmp / "endpoint_auth.json")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        appmod.S.__init__()
        self.c = appmod.app.test_client()

    def post(self, url, data=None, **kw):
        return self.c.post(url, json=data or {}, headers=HOST, **kw)

    def get(self, url):
        return self.c.get(url, headers=HOST)

    def configure(self, token=""):
        with mock.patch.object(traderie.TraderieClient, "get_status", return_value="online"):
            return self.post("/api/config", {"slug": "creaturesofsonaria", "user_id": "42", "auth": token})

    def test_index_served(self):
        self.assertEqual(self.get("/").status_code, 200)

    def test_bad_host_and_origin_blocked(self):
        self.assertEqual(self.c.get("/api/state", headers={"Host": "evil.com"}).status_code, 403)
        r = self.c.post("/api/clear-auth", json={}, headers={**HOST, "Origin": "http://evil.com"})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/clear-auth", data="x=1", headers=HOST, content_type="application/x-www-form-urlencoded")
        self.assertEqual(r.status_code, 415)

    def test_unconfigured(self):
        self.assertEqual(self.get("/api/listings").status_code, 400)

    def test_config_without_token_is_read_only(self):
        d = self.configure("").get_json()
        self.assertTrue(d["ok"])
        self.assertFalse(d["state"]["auth_set"])
        self.assertNotIn("auth", str(d["state"]).replace("auth_set", ""))

    def test_token_never_written_to_disk(self):
        self.configure("SEGREDO123")
        for f in Path(self.tmp.name).iterdir():
            self.assertNotIn("SEGREDO123", f.read_text())
        self.assertTrue(appmod.CONFIG_FILE.exists())

    def test_saved_config_prefills_state_when_disconnected(self):
        self.configure("")
        appmod.S.__init__()  # simula reinício
        saved = self.get("/api/state").get_json()["state"]["saved"]
        self.assertEqual(saved["user_id"], 42)

    def test_write_without_token_returns_401_no_network(self):
        self.configure("")
        with mock.patch("requests.Session.request") as req:
            r = self.post("/api/relist", {"listing_id": 1})
            self.assertEqual(r.status_code, 401)
            self.assertTrue(r.get_json()["auth_required"])
            req.assert_not_called()

    def test_listings_public_sorted_with_eta(self):
        self.configure("")
        fake = {1: traderie.Listing(1, "2999-01-01T00:00:00Z", itemName="Novo", refresh_available_at="2999-01-02T00:00:00Z"),
                2: traderie.Listing(2, "2020-01-01T00:00:00Z", itemName="Velho", can_refresh=True)}
        with mock.patch.object(traderie.TraderieClient, "get_all_listings", return_value=fake):
            d = self.get("/api/listings").get_json()
        self.assertEqual([x["id"] for x in d["listings"]], [2, 1])
        self.assertTrue(d["listings"][0]["eligible"])
        self.assertFalse(d["listings"][1]["eligible"])
        self.assertGreater(d["listings"][1]["eligible_in_hours"], 0)

    def test_routine_interval_validation_and_persistence(self):
        self.configure("tok")
        r = self.post("/api/auto-relist", {"enabled": True, "check_minutes": 12})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["state"]["auto_relist"])
        self.assertEqual(r.get_json()["state"]["check_minutes"], 12)
        self.assertEqual(appmod._read_json(appmod.CONFIG_FILE)["check_minutes"], 12)
        r = self.post("/api/auto-relist", {"enabled": False, "check_minutes": 1})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(appmod.S.public()["check_minutes"], 12)

    def test_auto_relist_requires_token(self):
        d = self.configure("").get_json()
        self.assertFalse(d["state"]["auto_relist"])
        self.assertEqual(self.post("/api/auto-relist", {"enabled": True}).status_code, 401)

    def test_config_resolves_username(self):
        with mock.patch.object(traderie.TraderieClient, "search_user", return_value=77), \
             mock.patch.object(traderie.TraderieClient, "get_status", return_value="online"):
            d = self.post("/api/config", {"username": "bob"}).get_json()
        self.assertEqual(d["state"]["user_id"], 77)

    def test_config_unknown_user_404(self):
        with mock.patch.object(traderie.TraderieClient, "search_user", return_value=None):
            self.assertEqual(self.post("/api/config", {"username": "ninguem"}).status_code, 404)

    def test_config_survives_status_needing_token(self):
        with mock.patch.object(traderie.TraderieClient, "get_status", side_effect=traderie.AuthRequired("x")):
            d = self.post("/api/config", {"user_id": "1"}).get_json()
        self.assertTrue(d["ok"])
        self.assertTrue(d["state"]["configured"])

    def test_config_connection_failure(self):
        with mock.patch.object(traderie.TraderieClient, "get_status", side_effect=traderie.TraderieError("boom")):
            r = self.post("/api/config", {"user_id": "1"})
        self.assertEqual(r.status_code, 502)
        self.assertFalse(appmod.S.public()["configured"])

    def test_diagnose_updates_policy_and_persists(self):
        self.configure("")
        rows = [{"endpoint": "offers", "policy": "private", "note": "", "anon": {}, "token": None}]
        with mock.patch.object(traderie.TraderieClient, "diagnose", return_value=rows):
            d = self.post("/api/diagnose").get_json()
        self.assertTrue(d["ok"])
        self.assertIn("creaturesofsonaria", appmod._read_json(appmod.POLICY_FILE))

    def test_saved_policy_is_applied_on_connect(self):
        appmod._write_json(appmod.POLICY_FILE, {"creaturesofsonaria": {"notifications": "public"}})
        d = self.configure("").get_json()
        self.assertEqual(d["state"]["policy"]["notifications"], "public")

    def test_accept_offer_flow(self):
        self.configure("tok")
        offer = traderie.Offer("I", 1, 2, 42, "s", 4, "b", 1, 5)
        with mock.patch.object(traderie.TraderieClient, "get_offers", return_value={1: offer}), \
             mock.patch.object(traderie.TraderieClient, "accept_offer") as acc, \
             mock.patch.object(traderie.TraderieClient, "open_conversation") as conversation:
            d = self.post("/api/offers/action", {"offer_id": 1, "action": "accept", "confirm":True, "revision":appmod.offer_revision(offer)}).get_json()
        acc.assert_called_once()
        self.assertTrue(d["ok"])
        conversation.assert_not_called()

    def test_decline_offer_uses_custom_or_default_reason(self):
        self.configure("tok")
        offer = traderie.Offer("I", 1, 2, 42, "s", 4, "b", 1, 5)
        with mock.patch.object(traderie.TraderieClient, "get_offers", return_value={1: offer}), \
             mock.patch.object(traderie.TraderieClient, "decline_offer") as dec:
            self.post("/api/offers/action", {"offer_id": 1, "action": "decline", "reason": "  sold  ", "confirm":True, "revision":appmod.offer_revision(offer)})
            appmod.S.offer_actions.clear()  # independent scenario: default reason
            self.post("/api/offers/action", {"offer_id": 1, "action": "decline", "reason": "", "confirm":True, "revision":appmod.offer_revision(offer)})
        self.assertEqual(dec.call_args_list[0].args[1], "sold")
        self.assertEqual(dec.call_args_list[1].args[1], "the offer was too low")

    def test_offers_and_conversations_are_lists(self):
        self.configure("tok")
        offer = traderie.Offer("I", 1, 2, 42, "s", 4, "b", 1, 5)
        with mock.patch.object(traderie.TraderieClient, "get_offers", return_value={1: offer}):
            self.assertEqual(self.get("/api/offers?kind=received").get_json()["offers"][0]["offerID"], 1)
        convo = {9: traderie.Conversation(5, 9)}
        with mock.patch.object(traderie.TraderieClient, "get_conversations", return_value=convo):
            self.assertEqual(self.get("/api/conversations").get_json()["conversations"][0]["userID"], 9)

    def test_blocked_site_maps_to_503(self):
        self.configure("")
        with mock.patch.object(traderie.TraderieClient, "get_all_listings", side_effect=traderie.Blocked("cf")):
            r = self.get("/api/listings")
        self.assertEqual(r.status_code, 503)
        self.assertTrue(r.get_json()["blocked"])

    def test_relist_all_only_eligible_and_single_run(self):
        self.configure("tok")
        fake = {1: traderie.Listing(1, "2020-01-01T00:00:00Z", can_refresh=True), 2: traderie.Listing(2, "2999-01-01T00:00:00Z")}
        with mock.patch.object(traderie.TraderieClient, "get_all_listings", return_value=fake), \
             mock.patch.object(traderie.TraderieClient, "relist") as rel:
            d = self.post("/api/relist-all").get_json()
        rel.assert_called_once_with(1)
        self.assertEqual((d["checked"], d["relisted"]), (2, 1))
        appmod.RELIST_LOCK.acquire()
        try:
            with mock.patch.object(traderie.TraderieClient, "get_all_listings", return_value=fake):
                self.assertEqual(self.post("/api/relist-all").status_code, 502)
        finally:
            appmod.RELIST_LOCK.release()

    def test_clear_auth(self):
        self.configure("tok")
        d = self.post("/api/clear-auth").get_json()
        self.assertFalse(d["state"]["auth_set"])


if __name__ == "__main__":
    unittest.main()
