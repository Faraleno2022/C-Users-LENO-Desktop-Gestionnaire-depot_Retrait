"""Génération de rapports."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from app.config import DATE_FMT, EXPORT_DIR
from app.db.database import get_connection
from app.utils.exporters import export_to_excel, export_to_pdf
from app.utils.helpers import format_money


def _period_label(date_from: str, date_to: str) -> str:
    return f"Du {date_from} au {date_to}"


def fetch_period_rows(date_from: str, date_to: str, agent_id: Optional[int] = None) -> List[Sequence]:
    conn = get_connection()
    sql = """SELECT id, created_at, matricule, telephone, type, montant, solde_apres,
                    agent_nom, sync_status
             FROM transactions
             WHERE deleted = 0 AND created_at >= ? AND created_at <= ?"""
    params: list = [f"{date_from} 00:00:00", f"{date_to} 23:59:59"]
    if agent_id is not None:
        sql += " AND agent_id = ?"
        params.append(agent_id)
    sql += " ORDER BY id ASC"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append([
            r["id"],
            r["created_at"],
            r["matricule"],
            r["telephone"] or "",
            "Dépôt" if r["type"] == "depot" else "Retrait",
            format_money(r["montant"]) if r["type"] == "depot" else "",
            format_money(r["montant"]) if r["type"] == "retrait" else "",
            format_money(r["solde_apres"]),
            r["agent_nom"],
            r["sync_status"],
        ])
    return out


REPORT_HEADERS = [
    "ID", "Date", "Matricule", "Téléphone", "Type",
    "Dépôt", "Retrait", "Solde après", "Agent", "Sync",
]

SALES_HEADERS = [
    "ID", "Date", "Matricule", "Produit", "Quantité",
    "Prix unitaire", "Montant", "Solde après", "Agent",
]

STOCK_HEADERS = [
    "ID", "Référence", "Produit", "Prix unitaire", "Stock",
    "Seuil", "Valeur", "Statut",
]


def fetch_sales_rows(date_from: str, date_to: str, agent_id: Optional[int] = None) -> List[Sequence]:
    conn = get_connection()
    sql = """SELECT id, created_at, matricule, product_nom, quantite, prix_unitaire,
                    montant_total, solde_apres, agent_nom
             FROM sales
             WHERE deleted = 0 AND created_at >= ? AND created_at <= ?"""
    params: list = [f"{date_from} 00:00:00", f"{date_to} 23:59:59"]
    if agent_id is not None:
        sql += " AND agent_id = ?"
        params.append(agent_id)
    sql += " ORDER BY id ASC"
    rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append([
            r["id"],
            r["created_at"],
            r["matricule"],
            r["product_nom"],
            f"{r['quantite']:g}",
            format_money(r["prix_unitaire"]),
            format_money(r["montant_total"]),
            format_money(r["solde_apres"]),
            r["agent_nom"],
        ])
    return out


def fetch_stock_rows() -> List[Sequence]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, reference, nom, prix_unitaire, quantite_stock, seuil_alerte, actif
           FROM products ORDER BY nom ASC"""
    ).fetchall()
    out = []
    for r in rows:
        if not r["actif"]:
            statut = "Inactif"
        elif r["quantite_stock"] <= r["seuil_alerte"]:
            statut = "Stock bas"
        else:
            statut = "OK"
        out.append([
            r["id"],
            r["reference"] or "",
            r["nom"],
            format_money(r["prix_unitaire"]),
            f"{r['quantite_stock']:g}",
            f"{r['seuil_alerte']:g}",
            format_money(r["quantite_stock"] * r["prix_unitaire"]),
            statut,
        ])
    return out


def generate_report(
    kind: str,
    date_from: str,
    date_to: str,
    agent_id: Optional[int] = None,
    fmt: str = "pdf",
    dataset: str = "transactions",
) -> Path:
    """Génère un rapport et retourne le chemin du fichier.

    dataset : 'transactions', 'sales' ou 'stock'.
    """
    if dataset == "sales":
        rows = fetch_sales_rows(date_from, date_to, agent_id=agent_id)
        headers = SALES_HEADERS
        base_title = "Rapport des ventes"
    elif dataset == "stock":
        rows = fetch_stock_rows()
        headers = STOCK_HEADERS
        base_title = "État du stock"
    else:
        rows = fetch_period_rows(date_from, date_to, agent_id=agent_id)
        headers = REPORT_HEADERS
        base_title = None

    title_map = {
        "daily": "Rapport journalier",
        "monthly": "Rapport mensuel",
        "annual": "Rapport annuel",
        "agent": "Rapport par agent",
        "custom": "Rapport personnalisé",
    }
    title = base_title or title_map.get(kind, "Rapport")
    if dataset == "stock":
        subtitle = f"Au {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    else:
        subtitle = _period_label(date_from, date_to)
        if agent_id is not None:
            subtitle += f" — Agent #{agent_id}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_kind = f"{dataset}_{kind}".replace(" ", "_")
    if fmt == "xlsx":
        path = EXPORT_DIR / f"rapport_{safe_kind}_{timestamp}.xlsx"
        return export_to_excel(path, f"{title} - {subtitle}", headers, rows)
    path = EXPORT_DIR / f"rapport_{safe_kind}_{timestamp}.pdf"
    return export_to_pdf(path, title, headers, rows, subtitle=subtitle)


def today_period() -> Tuple[str, str]:
    today = date.today().strftime(DATE_FMT)
    return today, today


def month_period(reference: Optional[date] = None) -> Tuple[str, str]:
    ref = reference or date.today()
    start = ref.replace(day=1)
    if ref.month == 12:
        next_month = ref.replace(year=ref.year + 1, month=1, day=1)
    else:
        next_month = ref.replace(month=ref.month + 1, day=1)
    end = next_month - timedelta(days=1)
    return start.strftime(DATE_FMT), end.strftime(DATE_FMT)


def year_period(reference: Optional[date] = None) -> Tuple[str, str]:
    ref = reference or date.today()
    return f"{ref.year}-01-01", f"{ref.year}-12-31"
