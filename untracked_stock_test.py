"""Articles vendus sans suivi de stock (plats servis, services rendus)."""
from accounting_test import DatabaseTestCase
from app.db import database as db
from app.services import cash_service as cash, product_service as products
from app.services import sale_service as sales
from server.sync.reconciliation_engine import build_plan


class UntrackedStockTests(DatabaseTestCase):
    def plate(self, nom="Plat 5.000", prix=5000):
        return products.create_product(nom, prix, suivi_stock=False)

    def test_migration_marks_and_creates_the_three_plates(self):
        """La base du poste contient les trois plats, en « sans stock »."""
        rows = db.get_connection().execute(
            "SELECT nom, prix_unitaire, suivi_stock, quantite_stock FROM products "
            "WHERE suivi_stock = 0 ORDER BY prix_unitaire"
        ).fetchall()
        self.assertEqual([r["nom"] for r in rows],
                         ["Plat 5.000", "Plat 10.000", "Plat 15.000"])
        self.assertEqual([r["prix_unitaire"] for r in rows], [5000, 10000, 15000])
        self.assertEqual({r["quantite_stock"] for r in rows}, {0})
        # L'article suivi créé par le fixture n'est pas touché.
        self.assertTrue(products.get_product(self.product.id).suivi_stock)

    def test_an_existing_plate_is_converted_rather_than_duplicated(self):
        """Un plat déjà saisi, même orthographié autrement, est basculé."""
        import app.db.database as database
        conn = db.get_connection()
        conn.execute("UPDATE products SET suivi_stock = 1, quantite_stock = 7 "
                     "WHERE nom = 'Plat 10.000'")
        conn.execute("UPDATE products SET nom = 'PLAT 10 000' WHERE nom = 'Plat 10.000'")
        conn.commit()
        database._apply_untracked_plates(conn.cursor())
        conn.commit()
        rows = conn.execute(
            "SELECT nom, suivi_stock FROM products WHERE nom LIKE '%10%'").fetchall()
        self.assertEqual(len(rows), 1, "le plat ne doit pas être dupliqué")
        self.assertEqual(rows[0]["suivi_stock"], 0)

    def test_selling_without_stock_never_runs_out(self):
        plate = self.plate()
        self.assertEqual(plate.quantite_stock, 0)
        for _ in range(3):
            sale = sales.create_sale("CLIENT", plate.id, 2, self.agent)
            self.assertEqual(sale.montant_total, 10000)
        # Ni quantité décomptée, ni mouvement de stock.
        self.assertEqual(products.get_product(plate.id).quantite_stock, 0)
        movements = db.get_connection().execute(
            "SELECT COUNT(*) AS n FROM stock_movements WHERE product_id = ?",
            (plate.id,)).fetchone()["n"]
        self.assertEqual(movements, 0)

    def test_a_tracked_product_still_runs_out(self):
        with self.assertRaisesRegex(sales.SaleError, "Stock insuffisant"):
            sales.create_sale("CLIENT", self.product.id, 11, self.agent)

    def test_cancelling_a_plate_sale_restores_nothing(self):
        plate = self.plate()
        sale = sales.create_sale("CLIENT", plate.id, 4, self.agent)
        sales.cancel_sale(sale.id)
        self.assertEqual(products.get_product(plate.id).quantite_stock, 0)
        self.assertEqual(db.get_connection().execute(
            "SELECT COUNT(*) AS n FROM stock_movements WHERE product_id = ?",
            (plate.id,)).fetchone()["n"], 0)

    def test_a_plate_can_be_sold_on_credit_and_in_cash(self):
        plate = self.plate()
        sales.create_sale("SANSSOLDE", plate.id, 1, self.agent)
        from app.services import transaction_service as tx
        self.assertEqual(tx.get_matricule_balance("SANSSOLDE"), -5000)
        sales.create_sale("", plate.id, 2, self.agent, mode_paiement="caisse")
        self.assertEqual(cash.get_balance(), 10000)

    def test_no_stock_movement_can_be_applied_to_a_plate(self):
        plate = self.plate()
        for type_ in ("entree", "sortie"):
            with self.assertRaisesRegex(products.ProductError, "sans suivi de stock"):
                products.adjust_stock(plate.id, type_, 5)

    def test_a_plate_is_never_in_alert_nor_counted_in_stock_value(self):
        plate = self.plate()
        self.assertFalse(plate.en_alerte())
        self.assertFalse(plate.en_rupture())
        self.assertFalse(plate.en_surstock())
        self.assertNotIn(plate.id, [p.id for p in products.low_stock_products()])
        # Seul l'article suivi entre dans la valeur du stock.
        self.assertEqual(products.stock_value(), 10 * self.product.prix_unitaire)

    def test_switching_a_tracked_product_to_untracked_clears_its_counters(self):
        products.adjust_stock(self.product.id, "entree", 5)
        updated = products.update_product(self.product.id, suivi_stock=False)
        self.assertFalse(updated.suivi_stock)
        self.assertEqual(updated.quantite_stock, 0)
        self.assertEqual(updated.seuil_alerte, 0)
        self.assertEqual(products.stock_value(), 0)

    def test_creating_a_plate_ignores_any_quantity_or_threshold(self):
        plate = products.create_product(
            "Service", 2000, quantite_initiale=9, seuil_alerte=3, stock_max=50,
            suivi_stock=False)
        self.assertEqual((plate.quantite_stock, plate.seuil_alerte, plate.stock_max),
                         (0, 0, 0))

    def test_plates_are_left_out_of_the_stock_recalculation(self):
        plate = self.plate()
        sales.create_sale("CLIENT", plate.id, 3, self.agent)
        conn = db.get_connection()
        data = {name: [dict(r) for r in conn.execute(f"SELECT * FROM {name} ORDER BY uuid")]
                for name in ("products", "stock_movements", "transactions", "sales", "audit_logs")}
        plan = build_plan(data["products"], data["stock_movements"], data["transactions"],
                          data["sales"], data["audit_logs"])
        touched = {c.get("uuid") for c in plan["changes"] if c.get("table") == "products"}
        self.assertNotIn(plate.uuid, touched)
        self.assertEqual([i for i in plan["issues"] if i.get("uuid") == plate.uuid], [])
        self.assertEqual([s for s in plan["stocks"] if s.get("uuid") == plate.uuid], [])

    def test_plates_are_pushed_with_their_flag(self):
        from app.services import sync_service
        self.assertIn("suivi_stock", sync_service.PUSH_TABLES["products"])
        self.assertIn("suivi_stock", sync_service.PULL_TABLES["products"])
