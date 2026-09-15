import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from django.test import TestCase
from django.utils import timezone
from sync.models import Product
from sync.replicator import Replicator, ReplicationError


class ReplicatorTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.rep = Replicator("https://example.test", "test", self.path)

    def response(self, body):
        return Mock(status_code=200, json=Mock(return_value=body))

    def product(self, uuid="p1"):
        return Product.objects.create(uuid=uuid, nom="Original", quantite_stock=10)

    def test_push_equal_timestamps_sends_every_record(self):
        for i in range(3):
            self.product(f"p{i}")
        Product.objects.update(received_at=timezone.now())
        with patch("sync.replicator.BATCH", 2), patch("sync.replicator.requests.post",
                return_value=self.response({"skipped": 0})) as post:
            self.assertEqual(self.rep._push_table("products"), 3)
        self.assertEqual([len(c.kwargs["json"]["records"]) for c in post.call_args_list], [2, 1])
        self.assertEqual(self.rep.state["push_products_uuid"], "p2")

    def test_failed_push_does_not_advance_state(self):
        self.product()
        with patch("sync.replicator.requests.post", return_value=self.response({"skipped": 1})):
            with self.assertRaises(ReplicationError):
                self.rep._push_table("products")
        self.assertNotIn("push_products", self.rep.state)

    def test_pull_passes_uuid_cursor_and_updates_records(self):
        pages = [
            {"records": [{"uuid": "p1", "nom": "A"}], "next_since": "2026-01-01T00:00:00Z",
             "next_uuid": "p1", "has_more": True},
            {"records": [{"uuid": "p2", "nom": "B"}], "next_since": "2026-01-01T00:00:00Z",
             "next_uuid": "p2", "has_more": False},
        ]
        with patch("sync.replicator.requests.get", side_effect=[self.response(p) for p in pages]) as get:
            self.assertEqual(self.rep._pull_table("products"), (2, 0))
        self.assertEqual(get.call_args_list[1].kwargs["params"]["since_uuid"], "p1")
        self.assertEqual(json.loads(self.path.read_text())["pull_products_uuid"], "p2")

    def test_pull_keeps_local_edit_made_during_request(self):
        product = self.product()
        self.rep.state.update(push_products=product.received_at.isoformat(), push_products_uuid=product.uuid)
        def response(*args, **kwargs):
            product.nom = "Saisie locale récente"
            product.save()
            return self.response({"records": [{"uuid": product.uuid, "nom": "Ancien"}],
                                  "next_since": "2026-01-01T00:00:00Z", "next_uuid": product.uuid,
                                  "has_more": False})
        with patch("sync.replicator.requests.get", side_effect=response):
            self.rep._pull_table("products")
        product.refresh_from_db()
        self.assertEqual(product.nom, "Saisie locale récente")
        self.assertNotIn("pull_products", self.rep.state)

    def test_invalid_state_shape_and_other_server_are_reset(self):
        for data in ([], {"server_url": "https://old.test", "pull_products": "old"}):
            self.path.write_text(json.dumps(data))
            rep = Replicator("https://example.test", "test", self.path)
            self.assertNotIn("pull_products", rep.state)

    def test_interrupted_state_write_preserves_previous_file(self):
        self.path.write_text('{"previous": "ok"}')
        with patch("sync.replicator.json.dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.rep._save_state()
        self.assertEqual(json.loads(self.path.read_text()), {"previous": "ok"})
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
