"""Tests du serveur de synchronisation."""
from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse

from sync.models import CashEntry, Client, Device, Sale, Transaction


class SyncApiTests(TestCase):
    def setUp(self):
        self.device = Device.objects.create(name="Poste test")
        self.auth = {"HTTP_AUTHORIZATION": f"Device {self.device.token}"}

    def push_transactions(self, records):
        response = self.client.post(reverse("sync-push"),
            data=json.dumps({"table": "transactions", "records": records}),
            content_type="application/json", **self.auth)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_offline_deposits_over_limit_are_kept_and_reported_idempotently(self):
        push = self.push_transactions
        first = dict(uuid="offline-1", matricule="M", type="depot", montant=30000,
                     created_at="2026-09-15 12:00:00", solde_apres=30000, deleted=False)
        second = dict(first, uuid="offline-2")
        self.assertEqual(push([first])["warnings"], [])
        result = push([second])
        self.assertEqual(result["warnings"][0]["total"], 60000)
        self.assertEqual(result["warnings"][0]["excess"], 20000)
        self.assertEqual(push([second])["warnings"], result["warnings"])
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(sum(Transaction.objects.values_list("montant", flat=True)), 60000)
        self.assertEqual(push([dict(second, deleted=True)])["warnings"], [])
        self.assertEqual(Transaction.objects.count(), 2)

    def test_long_outage_still_reports_the_day_that_was_pushed(self):
        """La fenêtre d'alerte part de la journée poussée, pas de la date du jour."""
        old = dict(uuid="vieux-1", matricule="M", type="depot", montant=30000,
                   created_at="2025-03-04 09:00:00", solde_apres=30000, deleted=False)
        self.assertEqual(self.push_transactions([old])["warnings"], [])
        result = self.push_transactions([dict(old, uuid="vieux-2")])
        self.assertEqual(result["warnings"][0]["day"], "2025-03-04")
        self.assertEqual(result["warnings"][0]["excess"], 20000)

    def test_cash_entries_travel_between_workstations(self):
        """La caisse est partagée : un poste pousse, les autres reçoivent."""
        record = dict(uuid="cash-1", date="2026-04-01", libelle="Solde initial",
                      entree=100000, sortie=0, source="ouverture", sale_uuid="",
                      created_at="2026-04-01 08:00:00.000001", deleted=False)
        response = self.client.post(reverse("sync-push"),
            data=json.dumps({"table": "cash_entries", "records": [record]}),
            content_type="application/json", **self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created"], 1)
        # Renvoyer le même enregistrement ne le duplique pas.
        self.client.post(reverse("sync-push"),
            data=json.dumps({"table": "cash_entries", "records": [record]}),
            content_type="application/json", **self.auth)
        self.assertEqual(CashEntry.objects.count(), 1)
        pulled = self.client.get(reverse("sync-pull"),
                                 {"table": "cash_entries"}, **self.auth).json()
        self.assertEqual(pulled["records"][0]["libelle"], "Solde initial")
        self.assertEqual(pulled["records"][0]["entree"], 100000)

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
