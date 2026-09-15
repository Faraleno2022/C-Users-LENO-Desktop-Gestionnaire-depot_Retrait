"""Parcours des écrans et exports sur données temporaires."""
import io
import uuid
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook
from sync.models import Client, RemoteUser, Product, Transaction
from web.reports import build_excel, build_pdf


class PageTests(TestCase):
    def setUp(self):
        self.remote = RemoteUser.objects.create(uuid=str(uuid.uuid4()), identifiant="audit-admin",
            nom_complet="Admin", role="super_admin", created_at="now", updated_at="now")
        self.client.force_login(get_user_model().objects.create_user(username="audit-admin"))
        session = self.client.session
        session["remote_user"] = {"id": self.remote.id, "uuid": self.remote.uuid, "role": "super_admin"}
        session.save()
        self.product = Product.objects.create(uuid=str(uuid.uuid4()), nom="Produit <test>", prix_unitaire=10,
            quantite_stock=5, created_at="now", updated_at="now")
        self.customer = Client.objects.create(uuid=str(uuid.uuid4()), matricule="CLIENT", created_at="now", updated_at="now")

    def test_pages_render_for_admin(self):
        names = ["dashboard", "dashboard_stats_api", "product_search_api", "transactions",
                 "trash", "deposit_new", "withdrawal_new", "matricule_balance_api", "sales",
                 "products", "product_new", "product_request_new", "stock_validations",
                 "pending_stock_api", "inventory", "stock_movements", "clients", "client_new",
                 "devices", "users", "user_new", "journal", "reports"]
        for name in names:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse("web:" + name)).status_code, 200)
        for name, pk in [("product_edit", self.product.pk), ("stock_adjust", self.product.pk),
                         ("stock_entry_request", self.product.pk), ("client_edit", self.customer.pk),
                         ("user_edit", self.remote.pk)]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse("web:" + name, args=[pk])).status_code, 200)

    def test_export_pages_return_valid_files(self):
        for page in ("transactions", "sales", "products", "stock_movements", "inventory"):
            for fmt in ("pdf", "xlsx"):
                with self.subTest(page=page, fmt=fmt):
                    response = self.client.get(reverse("web:" + page), {"export": fmt})
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.content.startswith(b"%PDF" if fmt == "pdf" else b"PK"))

    def test_report_special_characters_are_literal(self):
        data = build_excel("Dépôt / Retrait [test]", ["Nom"], [["=1+1"]])
        wb = load_workbook(io.BytesIO(data))
        self.assertEqual(wb.active["A4"].data_type, "s")
        wb.close()
        self.assertTrue(build_pdf("Société <broken>", ["Nom"], [["A & B"]], "<test").startswith(b"%PDF"))

    def test_negative_product_metadata_is_rejected(self):
        response = self.client.post(reverse("web:product_edit", args=[self.product.pk]),
             {"nom": "Produit", "prix_unitaire": 10, "prix_achat": -1, "seuil_alerte": 0, "stock_max": 0})
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.prix_achat, 0)

    def test_used_client_identifier_cannot_detach_history(self):
        Transaction.objects.create(uuid=str(uuid.uuid4()), matricule="CLIENT", type="depot",
                                   montant=10, solde_apres=10, created_at="now")
        response = self.client.post(reverse("web:client_edit", args=[self.customer.pk]),
                                    {"matricule": "OTHER", "nom": "Client"})
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.matricule, "CLIENT")


    def test_duplicate_login_name_does_not_change_operation_author(self):
        RemoteUser.objects.create(uuid=str(uuid.uuid4()), identifiant=self.remote.identifiant,
             nom_complet="Autre agent", role="caissier", created_at="now", updated_at="now")
        response = self.client.post(reverse("web:deposit_new"),
                                    {"matricule": "CLIENT", "montant": 10, "confirmed": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Transaction.objects.get().agent_uuid, self.remote.uuid)

    def test_last_superadmin_cannot_be_demoted(self):
        response = self.client.post(reverse("web:user_edit", args=[self.remote.pk]), {
            "identifiant": self.remote.identifiant, "nom_complet": "Admin", "role": "caissier",
        })
        self.assertEqual(response.status_code, 200)
        self.remote.refresh_from_db()
        self.assertEqual(self.remote.role, "super_admin")

    def test_inline_javascript_syntax(self):
        from html.parser import HTMLParser
        from pathlib import Path
        import shutil
        import subprocess
        from tempfile import TemporaryDirectory
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js non disponible pour le contrôle JavaScript.")
        class Scripts(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
                self.active = False
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "script":
                    self.active = not attrs.get("src") and attrs.get("type", "") in ("", "text/javascript", "module")
                    if self.active:
                        self.parts.append("")
            def handle_data(self, data):
                if self.active:
                    self.parts[-1] += data
            def handle_endtag(self, tag):
                if tag == "script":
                    self.active = False
        with TemporaryDirectory() as tmp:
            for page in ("dashboard", "withdrawal_new", "deposit_new", "products", "product_new", "inventory", "reports"):
                response = self.client.get(reverse("web:" + page))
                parser = Scripts()
                parser.feed(response.content.decode())
                for index, script in enumerate(parser.parts):
                    with self.subTest(page=page, script=index):
                        path = Path(tmp) / f"{page}-{index}.js"
                        path.write_text(script, encoding="utf-8")
                        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
