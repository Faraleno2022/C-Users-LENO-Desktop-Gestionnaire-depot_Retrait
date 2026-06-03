"""Test fumée — vérifie le coeur métier sans démarrer Qt."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def main() -> int:
    # Rediriger DB_PATH vers un fichier temporaire
    import app.config as cfg
    tmp = Path(tempfile.mkdtemp(prefix="gestionnaire_test_"))
    cfg.DATA_DIR = tmp
    cfg.BACKUP_DIR = tmp / "backups"
    cfg.DB_PATH = tmp / "test.db"
    cfg.EXPORT_DIR = tmp / "exports"
    cfg.LOG_DIR = tmp / "logs"
    cfg.ensure_directories()

    # Re-importer database avec nouvelle config
    from app.db import database as db
    db._local.conn = None
    from app.db.database import init_database, close_connection
    init_database()

    from app.services import user_service, transaction_service, auth_service, backup_service
    from app.models.user import User

    # 1. ensure_super_admin
    user_service.ensure_super_admin()
    admin = user_service.get_user_by_identifiant("admin")
    assert admin is not None and admin.role == "super_admin"
    print(f"OK super-admin créé : {admin.identifiant}")

    # 2. login
    u = auth_service.login("admin", "admin123")
    assert u.id == admin.id
    print("OK login admin")

    # 3. créer un caissier
    caissier = user_service.create_user(
        identifiant="cais1", password="pass123",
        nom_complet="Caissier Un", role="caissier", matricule="CAI-001",
    )
    print(f"OK caissier créé : {caissier.identifiant}")

    # 4. dépôt + retrait
    tx1 = transaction_service.create_transaction(
        matricule="MAT-001", telephone="700000001", type_="depot",
        montant=10000, agent=caissier,
    )
    assert tx1.solde_apres == 10000
    print(f"OK dépôt : solde={tx1.solde_apres}")

    tx2 = transaction_service.create_transaction(
        matricule="MAT-001", telephone="700000001", type_="retrait",
        montant=3000, agent=caissier,
    )
    assert tx2.solde_apres == 7000
    print(f"OK retrait : solde={tx2.solde_apres}")

    # 5. retrait excessif
    try:
        transaction_service.create_transaction(
            matricule="MAT-001", telephone="", type_="retrait",
            montant=99999, agent=caissier,
        )
        print("ECHEC: retrait excessif aurait dû être refusé")
        return 1
    except transaction_service.TransactionError as e:
        print(f"OK retrait excessif refusé : {e}")

    # 6. global balance + counts
    solde = transaction_service.get_global_balance()
    assert solde == 7000
    depots, retraits, n, m = transaction_service.totals()
    assert depots == 10000 and retraits == 3000 and n == 2
    print(f"OK totals : dépôts={depots} retraits={retraits} n={n}")

    # 7. sync statuses
    counts = transaction_service.sync_status_counts()
    assert counts.get("pending") == 2
    print(f"OK sync counts : {counts}")

    # 8. recherche avec filtres
    found = transaction_service.search_transactions(matricule="MAT-001")
    assert len(found) == 2
    print(f"OK search : {len(found)} résultats")

    # 8b. produits / stock / ventes
    from app.services import product_service, sale_service

    prod = product_service.create_product(
        nom="Ciment 50kg", prix_unitaire=4000, reference="CIM-50",
        quantite_initiale=10, seuil_alerte=3,
    )
    assert prod.quantite_stock == 10
    print(f"OK produit créé : {prod.nom} stock={prod.quantite_stock}")

    prod = product_service.adjust_stock(prod.id, "entree", 5, motif="Réappro")
    assert prod.quantite_stock == 15
    print(f"OK entrée stock : {prod.quantite_stock}")

    prod = product_service.adjust_stock(prod.id, "sortie", 2, motif="Casse")
    assert prod.quantite_stock == 13
    print(f"OK sortie stock : {prod.quantite_stock}")

    # vente : MAT-001 a 7000, achat de 1 x 4000 -> solde 3000, stock 12
    sale = sale_service.create_sale(
        matricule="MAT-001", product_id=prod.id, quantite=1, agent=caissier,
    )
    assert sale.montant_total == 4000 and sale.solde_apres == 3000
    assert product_service.get_product(prod.id).quantite_stock == 12
    assert transaction_service.get_matricule_balance("MAT-001") == 3000
    print(f"OK vente : montant={sale.montant_total} solde={sale.solde_apres}")

    # vente refusée : solde insuffisant (3000 < 4000)
    try:
        sale_service.create_sale("MAT-001", prod.id, 1, caissier)
        print("ECHEC: vente solde insuffisant aurait dû être refusée")
        return 1
    except sale_service.SaleError as e:
        print(f"OK vente refusée (solde) : {e}")

    # vente refusée : stock insuffisant
    try:
        sale_service.create_sale("MAT-002", prod.id, 999, caissier)
        print("ECHEC: vente stock insuffisant aurait dû être refusée")
        return 1
    except sale_service.SaleError as e:
        print(f"OK vente refusée (stock) : {e}")

    # annulation : restitue stock (13) et solde (7000)
    sale_service.cancel_sale(sale.id)
    assert product_service.get_product(prod.id).quantite_stock == 13
    assert transaction_service.get_matricule_balance("MAT-001") == 7000
    print("OK annulation vente : stock et solde restitués")

    # rapports ventes + stock
    from app.services import report_service as _rs
    sales_pdf = _rs.generate_report("daily", *_rs.today_period(), fmt="pdf", dataset="sales")
    assert sales_pdf.exists() and sales_pdf.stat().st_size > 0
    stock_xlsx = _rs.generate_report("daily", *_rs.today_period(), fmt="xlsx", dataset="stock")
    assert stock_xlsx.exists() and stock_xlsx.stat().st_size > 0
    print("OK rapports ventes (PDF) + stock (Excel)")

    # 9. rapport (PDF + Excel)
    from app.services import report_service
    pdf = report_service.generate_report("daily", *report_service.today_period(), fmt="pdf")
    assert pdf.exists() and pdf.stat().st_size > 0
    print(f"OK rapport PDF : {pdf.stat().st_size} octets")
    xlsx = report_service.generate_report("daily", *report_service.today_period(), fmt="xlsx")
    assert xlsx.exists() and xlsx.stat().st_size > 0
    print(f"OK rapport Excel : {xlsx.stat().st_size} octets")

    # 10. backup
    bpath = backup_service.create_backup(kind="manual", note="test")
    assert bpath.exists() and bpath.stat().st_size > 0
    print(f"OK backup : {bpath.name}")

    # 11. wipe + restore
    backup_service.wipe_data()
    assert transaction_service.get_global_balance() == 0
    print("OK wipe")
    backup_service.restore_backup(bpath)
    # après restore on doit retrouver le solde
    bal = transaction_service.get_global_balance()
    assert bal == 7000, f"après restore, solde attendu 7000, obtenu {bal}"
    print(f"OK restore : solde={bal}")

    # 12. audit
    from app.services import audit_service
    logs = audit_service.list_logs(limit=50)
    assert len(logs) > 0
    print(f"OK audit : {len(logs)} entrées")

    # 13. clients : MAT-001 apparaît même sans fiche, puis fiche enrichie
    from app.services import client_service
    rows = client_service.list_clients()
    mat = next((r for r in rows if r.matricule == "MAT-001"), None)
    assert mat is not None, "MAT-001 devrait apparaître dans la liste des clients"
    assert mat.enregistre is False and mat.solde == 7000
    print(f"OK client implicite : {mat.matricule} solde={mat.solde} ops={mat.nb_operations}")

    fiche = client_service.create_client(
        matricule="MAT-001", nom="Awa Diop", telephone="770000000", note="VIP",
    )
    assert fiche.id is not None and fiche.nom == "Awa Diop"
    rows = client_service.list_clients(query="awa")
    assert any(r.matricule == "MAT-001" and r.enregistre for r in rows)
    print(f"OK fiche client créée et recherchée : {fiche.nom}")

    # fiche en double refusée
    try:
        client_service.create_client(matricule="MAT-001")
        print("ECHEC: fiche en double aurait dû être refusée")
        return 1
    except client_service.ClientError as e:
        print(f"OK fiche en double refusée : {e}")

    ops = client_service.client_operations("MAT-001")
    assert len(ops) >= 2, "l'historique du client doit contenir ses opérations"
    print(f"OK historique client : {len(ops)} opération(s)")

    # 14. sauvegarde planifiée
    from app.services import settings_service
    settings_service.set_auto_backup_config(enabled=True, interval_days=1, keep=3)
    first = backup_service.run_auto_backup_if_due()
    assert first is not None and first.exists(), "1ère sauvegarde auto attendue"
    print(f"OK sauvegarde auto créée : {first.name}")
    # Immédiatement après : pas encore due
    second = backup_service.run_auto_backup_if_due()
    assert second is None, "ne doit pas re-sauvegarder avant l'échéance"
    print("OK pas de double sauvegarde avant échéance")
    # Désactivée -> None
    settings_service.set_auto_backup_config(enabled=False, interval_days=1)
    assert backup_service.run_auto_backup_if_due() is None
    print("OK sauvegarde auto désactivée respectée")
    # Élagage : on garde au plus 2 sauvegardes auto
    for _ in range(4):
        backup_service.create_backup(kind="auto", note="test élagage")
    backup_service.prune_auto_backups(2)
    autos = [b for b in backup_service.list_backups() if b["kind"] == "auto"]
    assert len(autos) == 2, f"attendu 2 sauvegardes auto après élagage, obtenu {len(autos)}"
    print(f"OK élagage sauvegardes auto : {len(autos)} conservée(s)")

    close_connection()
    print("\nTous les tests sont OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
