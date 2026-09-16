"""La synchronisation manuelle doit nommer sa cause, pas accuser la connexion."""
import json
from pathlib import Path
from unittest.mock import patch

import requests
from django.test import TestCase
from django.urls import reverse

from sync.replicator import ReplicationError
from web.tests import StockAndBalanceTests


class SyncNowMessageTests(TestCase):
    def setUp(self):
        StockAndBalanceTests.setUp(self)

    make_product = StockAndBalanceTests.make_product

    def call(self, exception):
        """Appelle la synchro manuelle avec un réplicateur qui lève `exception`."""
        from django.conf import settings
        data_dir = Path(settings.DATABASES["default"]["NAME"]).resolve().parent
        (data_dir / "render_sync.json").write_text(json.dumps(
            {"enabled": True, "url": "https://exemple.test", "token": "jeton-de-test"}),
            encoding="utf-8")
        with patch("sync.replicator.Replicator.run_once", side_effect=exception):
            response = self.client.post(reverse("web:sync_now"))
        return response.json()

    def test_a_server_refusal_is_reported_verbatim(self):
        body = self.call(ReplicationError("Push sales refusé (500) : valeur trop longue"))
        self.assertFalse(body["ok"])
        self.assertIn("Push sales refusé (500)", body["message"])
        self.assertIn("valeur trop longue", body["message"])
        # Le serveur a répondu : on n'accuse pas la connexion.
        self.assertNotIn("Vérifiez internet", body["message"])

    def test_a_real_network_failure_still_blames_the_link(self):
        body = self.call(requests.ConnectionError("dns introuvable"))
        self.assertFalse(body["ok"])
        self.assertIn("injoignable", body["message"])
        self.assertIn("Vérifiez internet", body["message"])

    def test_a_read_timeout_is_named_as_such(self):
        body = self.call(requests.ReadTimeout("lecture expirée"))
        self.assertIn("ReadTimeout", body["message"])
        self.assertIn("Vérifiez internet", body["message"])

    def test_an_unexpected_error_is_not_swallowed(self):
        body = self.call(ValueError("colonne inconnue"))
        self.assertFalse(body["ok"])
        self.assertIn("ValueError", body["message"])
        self.assertIn("colonne inconnue", body["message"])
        self.assertNotIn("Vérifiez internet", body["message"])
