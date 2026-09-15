import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from sync.models import Device, Transaction


class SyncRegressionTests(TestCase):
    def setUp(self):
        device = Device.objects.create(name="Test")
        self.auth = {"HTTP_AUTHORIZATION": f"Device {device.token}"}
        self.record = dict(uuid="t1", matricule="M", type="depot", montant=100,
                           solde_apres=100, created_at="2026-01-01 00:00:00")

    def push(self, records, auth=None):
        return self.client.post(reverse("sync-push"), json.dumps({"table": "transactions", "records": records}),
                                content_type="application/json", **(self.auth if auth is None else auth))

    def test_malformed_batch_is_rejected_atomically(self):
        response = self.push([self.record, "not-a-record"])
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Transaction.objects.exists())

    def test_nonfinite_amount_is_rejected(self):
        for value in ("nan", "inf", "-inf", "-1", "0"):
            with self.subTest(value=value):
                self.assertEqual(self.push([dict(self.record, montant=value)]).status_code, 400)
                self.assertFalse(Transaction.objects.exists())

    def test_browser_session_cannot_access_device_sync(self):
        self.client.force_login(get_user_model().objects.create_user(username="cashier"))
        self.assertEqual(self.push([self.record], auth={}).status_code, 401)
        self.assertEqual(self.client.get(reverse("sync-pull"), {"table": "users"}).status_code, 401)

    def test_equal_timestamps_do_not_lose_next_page(self):
        for index in range(3):
            self.push([dict(self.record, uuid=f"tx-{index}")])
        moment = timezone.now()
        Transaction.objects.update(received_at=moment)
        page = self.client.get(reverse("sync-pull"), {"table": "transactions", "limit": 2}, **self.auth).json()
        following = self.client.get(reverse("sync-pull"), {
            "table": "transactions", "limit": 2,
            "since": page["next_since"], "since_uuid": page.get("next_uuid", ""),
        }, **self.auth).json()
        self.assertEqual(len(page["records"]) + len(following["records"]), 3)
        self.assertFalse(following["has_more"])

    def test_invalid_timestamp_is_not_silently_full_sync(self):
        response = self.client.get(reverse("sync-pull"), {"table": "transactions", "since": "broken"}, **self.auth)
        self.assertEqual(response.status_code, 400)


    def test_invalid_json_structure_returns_validation_error(self):
        for payload in ([], {"table": [], "records": []}):
            with self.subTest(payload=payload):
                response = self.client.post(reverse("sync-push"), json.dumps(payload),
                                            content_type="application/json", **self.auth)
                self.assertEqual(response.status_code, 400)
