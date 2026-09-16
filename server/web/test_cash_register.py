"""Caisse côté Console Web : vente encaissée, écritures et solde progressif."""
import uuid

from django.test import TestCase
from django.urls import reverse

from sync.business_rules import business_day
from sync.models import CashEntry, RemoteUser, Sale, Transaction
from web.tests import StockAndBalanceTests
from web.views import _cash_balance, _matricule_balance


class CashRegisterWebTests(TestCase):
    def setUp(self):
        StockAndBalanceTests.setUp(self)

    make_product = StockAndBalanceTests.make_product

    def sell_cash(self, ids, quantities):
        return self.client.post(reverse("web:withdrawal_new"), {
            "mode_paiement": "caisse", "confirmed": "1", "montant": "",
            "prod_id": list(ids), "prod_qte": list(quantities),
        })

    def entry(self, sens, montant, libelle="Versement à la banque", date=""):
        return self.client.post(reverse("web:cash_entry_new"), {
            "sens": sens, "montant": str(montant), "libelle": libelle, "date": date,
        }, follow=True)

    # --- Journal ------------------------------------------------------------

    def test_progressive_balance_and_ordering(self):
        self.entry("ouverture", 100000, "Solde initial", "2026-01-01")
        self.entry("sortie", 54000, "Versement à la banque", "2026-01-01")
        self.entry("entree", 20000, "Recette annexe", "2026-01-01")
        self.entry("sortie", 40000, "Achat fournitures", "2026-01-01")
        response = self.client.get(reverse("web:caisse"))
        # La page affiche du plus récent au plus ancien.
        soldes = [row["solde"] for row in response.context["rows"]]
        self.assertEqual(soldes, [26000, 66000, 46000, 100000])
        self.assertEqual(response.context["solde"], 26000)
        self.assertEqual(response.context["total_entrees"], 120000)
        self.assertEqual(response.context["total_sorties"], 94000)

    def test_backdated_entry_is_ordered_by_its_own_date(self):
        self.entry("ouverture", 10000, "Solde initial", "2026-03-10")
        self.entry("sortie", 1000, "Sortie du 12", "2026-03-12")
        self.entry("entree", 500, "Entrée oubliée du 11", "2026-03-11")
        rows = list(reversed(self.client.get(reverse("web:caisse")).context["rows"]))
        self.assertEqual([(r["entry"].date, r["solde"]) for r in rows],
                         [("2026-03-10", 10000), ("2026-03-11", 10500), ("2026-03-12", 9500)])

    def test_filtering_keeps_the_balance_of_the_whole_journal(self):
        self.entry("ouverture", 10000, "Solde initial", "2026-03-10")
        self.entry("sortie", 4000, "Sortie", "2026-03-12")
        response = self.client.get(reverse("web:caisse"), {"date_from": "2026-03-12"})
        rows = response.context["rows"]
        self.assertEqual([r["entry"].libelle for r in rows], ["Sortie"])
        self.assertEqual(rows[0]["solde"], 6000)

    # --- Règles -------------------------------------------------------------

    def test_withdrawal_larger_than_the_drawer_is_refused(self):
        self.entry("ouverture", 1000)
        response = self.entry("sortie", 1001)
        self.assertContains(response, "insuffisant")
        self.assertEqual(_cash_balance(), 1000)

    def test_only_one_opening_entry(self):
        self.entry("ouverture", 1000)
        response = self.entry("ouverture", 2000)
        self.assertContains(response, "déjà une écriture d&#x27;ouverture")
        self.assertEqual(_cash_balance(), 1000)

    def test_invalid_entries_are_refused(self):
        for payload in (("sortie", 0), ("entree", -5)):
            self.assertEqual(CashEntry.objects.count(), 0)
            self.entry(*payload)
        self.assertContains(self.entry("entree", 100, libelle="  "), "libellé")
        self.assertContains(self.entry("entree", 100, date="2026-13-45"), "Date invalide")
        self.assertContains(
            self.client.post(reverse("web:cash_entry_new"),
                             {"sens": "virement", "montant": "10", "libelle": "X"}, follow=True),
            "une entrée, une sortie ou une ouverture")
        self.assertEqual(CashEntry.objects.count(), 0)

    def test_sale_entry_cannot_be_cancelled_on_its_own(self):
        self.sell_cash([self.product.pk], [2])
        entry = CashEntry.objects.get(source="vente")
        response = self.client.post(
            reverse("web:cash_entry_delete", args=[entry.pk]), follow=True)
        self.assertContains(response, "annulez la vente")
        entry.refresh_from_db()
        self.assertFalse(entry.deleted)

    def test_cancelling_a_manual_entry_recomputes_the_balance(self):
        self.entry("entree", 1000, "Recette")
        entry = CashEntry.objects.get(source="manuel")
        self.client.post(reverse("web:cash_entry_delete", args=[entry.pk]), follow=True)
        self.assertEqual(_cash_balance(), 0)

    def test_cancelling_an_entry_cannot_make_the_drawer_negative(self):
        self.entry("entree", 1000, "Recette")
        self.entry("sortie", 800)
        entry = CashEntry.objects.get(source="manuel", entree=1000)
        response = self.client.post(
            reverse("web:cash_entry_delete", args=[entry.pk]), follow=True)
        self.assertContains(response, "négatif")
        self.assertEqual(_cash_balance(), 200)

    def become_agent(self):
        """Bascule la session sur un profil agent, sans droit de suppression."""
        remote = RemoteUser.objects.create(
            uuid=str(uuid.uuid4()), identifiant="agent-caisse", nom_complet="Agent",
            role="caissier", can_delete=False, created_at="now", updated_at="now")
        session = self.client.session
        session["remote_user"] = {"id": remote.id, "uuid": remote.uuid,
                                  "role": "caissier", "identifiant": "agent-caisse"}
        session.save()

    def test_agent_profile_cannot_delete_a_cash_entry(self):
        self.entry("entree", 1000, "Recette")
        entry = CashEntry.objects.get(source="manuel")
        self.become_agent()
        response = self.client.post(reverse("web:cash_entry_delete", args=[entry.pk]))
        self.assertEqual(response.status_code, 403)
        entry.refresh_from_db()
        self.assertFalse(entry.deleted)
        self.assertEqual(_cash_balance(), 1000)

    def test_agent_profile_still_records_entries_but_sees_no_cancel_button(self):
        self.become_agent()
        self.entry("entree", 500, "Recette du jour")
        self.assertEqual(_cash_balance(), 500)
        page = self.client.get(reverse("web:caisse"))
        self.assertFalse(page.context["can_delete"])
        self.assertNotIn("cash_entry_delete", page.content.decode())
        self.assertNotIn(">Annuler<", page.content.decode())

    # --- Vente encaissée ----------------------------------------------------

    def test_cash_sale_feeds_the_register_without_touching_any_account(self):
        self.entry("ouverture", 5000)
        self.assertEqual(self.sell_cash([self.product.pk], [3]).status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual(sale.mode_paiement, "caisse")
        self.assertEqual((sale.matricule, sale.telephone, sale.solde_apres), ("", "", 0))
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 7)
        entry = CashEntry.objects.get(source="vente")
        self.assertEqual((entry.entree, entry.sortie, entry.date),
                         (300, 0, business_day()))
        self.assertIn("Ciment", entry.libelle)
        self.assertEqual(entry.sale_uuid, sale.uuid)
        self.assertEqual(_cash_balance(), 5300)
        # Le compte du client de référence n'a pas bougé.
        self.assertEqual(_matricule_balance("MAT-1"), 10000)

    def test_cash_sale_requires_at_least_one_product(self):
        response = self.client.post(reverse("web:withdrawal_new"), {
            "mode_paiement": "caisse", "confirmed": "1", "montant": "5000",
            "prod_id": [], "prod_qte": [],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(CashEntry.objects.count(), 0)

    def test_account_sale_never_reaches_the_register(self):
        self.client.post(reverse("web:withdrawal_new"), {
            "matricule": "MAT-1", "confirmed": "1", "montant": "",
            "prod_id": [self.product.pk], "prod_qte": [1],
        })
        self.assertEqual(Sale.objects.get().mode_paiement, "compte")
        self.assertEqual(CashEntry.objects.count(), 0)
        self.assertEqual(_matricule_balance("MAT-1"), 9900)

    def test_unknown_payment_mode_is_refused(self):
        response = self.client.post(reverse("web:withdrawal_new"), {
            "mode_paiement": "cheque", "confirmed": "1", "montant": "100",
            "prod_id": [self.product.pk], "prod_qte": [1],
        })
        self.assertContains(response, "Mode de paiement inconnu")
        self.assertEqual(Sale.objects.count(), 0)

    def test_cancelling_a_cash_sale_removes_its_encashment(self):
        self.sell_cash([self.product.pk], [2])
        sale = Sale.objects.get()
        self.assertEqual(_cash_balance(), 200)
        self.client.post(reverse("web:sale_delete", args=[sale.pk]), follow=True)
        self.assertEqual(_cash_balance(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantite_stock, 10)

    def test_restoring_a_cash_sale_restores_its_encashment(self):
        self.sell_cash([self.product.pk], [2])
        sale = Sale.objects.get()
        self.client.post(reverse("web:sale_delete", args=[sale.pk]), follow=True)
        self.assertEqual(_cash_balance(), 0)
        self.client.post(reverse("web:sale_restore", args=[sale.pk]), follow=True)
        self.assertEqual(_cash_balance(), 200)
        self.assertEqual(CashEntry.objects.filter(deleted=False).count(), 1)

    def test_sales_page_labels_a_cash_sale(self):
        self.sell_cash([self.product.pk], [1])
        page = self.client.get(reverse("web:sales")).content.decode()
        self.assertIn(">Caisse</span>", page)
        # Le libellé de confirmation ne doit pas casser l'attribut HTML.
        self.assertIn("Envoyer cette vente (Ciment — caisse)", page)
        self.assertNotIn("mode_paiement ==", page)

    def test_balance_api_ignores_cash_sales(self):
        Sale.objects.create(
            uuid=str(uuid.uuid4()), matricule="MAT-1", product_id=self.product.pk,
            product_uuid=self.product.uuid, product_nom="Ciment", quantite=1,
            prix_unitaire=100, montant_total=100, solde_apres=0,
            mode_paiement="caisse", created_at="2026-01-02 10:00:00",
        )
        preview = self.client.get(reverse("web:matricule_balance_api"),
                                  {"matricule": "MAT-1"}).json()
        self.assertEqual(preview["balance"], 10000)
        self.assertEqual(Transaction.objects.count(), 1)
