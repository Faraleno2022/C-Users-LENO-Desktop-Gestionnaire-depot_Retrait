"""Tests du serveur de synchronisation."""
from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse

from sync.models import Client, Device, Sale, Transaction


class SyncApiTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Poste test")
        self.auth = {"HTTP_AUTHORIZATION": f"Device {self.device.token}"}

    def test_ping_requires_token(self):
        resp = self.client.get(reverse("sync-ping"))
        self.assertEqual(resp.status_code, 401)

    def test_ping_ok(self):
        resp = self.client.get(reverse("sync-ping"), **self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(resp.json()["device"], "Poste test")

    def test_push_invalid_token(self):
        resp = self.client.post(
            reverse("sync-push"),
            data=json.dumps({"table": "transactions", "records": []}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Device wrong",
        )
        self.assertEqual(resp.status_code, 401)

    def test_push_upsert_idempotent(self):
        record = {
            "uuid": "u-1", "matricule": "MAT-1", "telephone": "700", "type": "depot",
            "montant": 5000, "solde_apres": 5000, "agent_id": 1, "agent_nom": "A",
            "note": "", "created_at": "2026-05-29 10:00:00", "deleted": 0,
        }
        payload = {"table": "transactions", "records": [record]}
        r1 = self.client.post(
            reverse("sync-push"), data=json.dumps(payload),
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["created"], 1)
        self.assertEqual(Transaction.objects.count(), 1)

        # Renvoi du même uuid avec un solde modifié -> update, pas de doublon
        record["solde_apres"] = 4000
        record["deleted"] = 1
        r2 = self.client.post(
            reverse("sync-push"), data=json.dumps(payload),
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r2.json()["updated"], 1)
        self.assertEqual(Transaction.objects.count(), 1)
        tx = Transaction.objects.get(uuid="u-1")
        self.assertEqual(tx.solde_apres, 4000)
        self.assertTrue(tx.deleted)

    def test_push_unknown_table(self):
        resp = self.client.post(
            reverse("sync-push"),
            data=json.dumps({"table": "nope", "records": []}),
            content_type="application/json", **self.auth,
        )
        self.assertEqual(resp.status_code, 400)

    def test_push_sale_and_skip_missing_uuid(self):
        payload = {"table": "sales", "records": [
            {"uuid": "s-1", "matricule": "M", "product_id": 1, "product_nom": "P",
             "quantite": 1, "prix_unitaire": 100, "montant_total": 100, "solde_apres": 0,
             "agent_id": 1, "agent_nom": "A", "created_at": "2026-05-29 10:00:00", "deleted": 0},
            {"matricule": "M2"},  # sans uuid -> ignoré
        ]}
        resp = self.client.post(
            reverse("sync-push"), data=json.dumps(payload),
            content_type="application/json", **self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["created"], 1)
        self.assertEqual(resp.json()["skipped"], 1)
        self.assertEqual(Sale.objects.count(), 1)

    def test_push_client_upsert(self):
        payload = {"table": "clients", "records": [
            {"uuid": "c-1", "matricule": "MAT-1", "nom": "Awa Diop",
             "telephone": "770000000", "note": "VIP", "actif": 1,
             "created_at": "2026-05-29 10:00:00", "updated_at": "2026-05-29 10:00:00"},
        ]}
        r1 = self.client.post(
            reverse("sync-push"), data=json.dumps(payload),
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["created"], 1)
        self.assertEqual(Client.objects.get(uuid="c-1").nom, "Awa Diop")

        payload["records"][0]["nom"] = "Awa D."
        r2 = self.client.post(
            reverse("sync-push"), data=json.dumps(payload),
            content_type="application/json", **self.auth,
        )
        self.assertEqual(r2.json()["updated"], 1)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Client.objects.get(uuid="c-1").nom, "Awa D.")
