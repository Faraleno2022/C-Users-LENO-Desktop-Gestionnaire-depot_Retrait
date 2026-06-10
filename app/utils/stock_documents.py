"""Génération des bons et documents de stock en PDF (reportlab).

Documents produits :
- Bon d'entrée    : preuve de réception d'un mouvement d'entrée
- Bon de sortie   : preuve de livraison d'un mouvement de sortie
- Fiche article   : informations + historique des mouvements d'un produit
- Inventaire      : état du stock avec colonnes de comptage physique / écart

Tous les documents portent un en-tête société configurable
(``settings_service.get_company_info``) et sont enregistrés dans
``exports/bons/``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.config import EXPORT_DIR
from app.services import settings_service
from app.utils.helpers import format_money, slugify

# Couleurs de la charte (cohérentes avec exporters.export_to_pdf)
_PRIMARY = colors.HexColor("#1F4E78")
_ENTREE = colors.HexColor("#15803d")
_SORTIE = colors.HexColor("#b91c1c")
_LIGHT = colors.HexColor("#f1f5f9")


def _bons_dir() -> Path:
    d = EXPORT_DIR / "bons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "company": ParagraphStyle(
            "company", parent=base["Title"], fontSize=16, leading=19,
            textColor=_PRIMARY, spaceAfter=0,
        ),
        "company_info": ParagraphStyle(
            "company_info", parent=base["Normal"], fontSize=8.5, leading=11,
            textColor=colors.HexColor("#475569"),
        ),
        "doc_title": ParagraphStyle(
            "doc_title", parent=base["Title"], fontSize=15, leading=18,
            alignment=TA_CENTER, spaceBefore=2, spaceAfter=2,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#475569"),
        ),
        "value": ParagraphStyle(
            "value", parent=base["Normal"], fontSize=10, leading=13,
        ),
        "normal": base["Normal"],
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontSize=8, leading=10,
            textColor=colors.HexColor("#64748b"),
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontSize=8, leading=10,
            alignment=TA_CENTER, textColor=colors.HexColor("#64748b"),
        ),
        "total": ParagraphStyle(
            "total", parent=base["Normal"], fontSize=10, leading=13,
            alignment=TA_RIGHT,
        ),
    }


def _header_story(styles: dict, doc_title: str, title_color=_PRIMARY) -> list:
    """En-tête : coordonnées société + titre du document."""
    info = settings_service.get_company_info()
    lines = [f"<b>{info['name']}</b>"]
    contact = []
    if info["address"]:
        contact.append(info["address"])
    phones = " · ".join(p for p in (info["phone"], info["email"]) if p)
    if phones:
        contact.append(phones)

    left = [Paragraph(info["name"], styles["company"])]
    for c in contact:
        left.append(Paragraph(c, styles["company_info"]))

    title_style = ParagraphStyle(
        "doc_title_colored", parent=styles["doc_title"], textColor=title_color
    )
    right = [Paragraph(doc_title, title_style)]

    head = Table([[left, right]], colWidths=[100 * mm, None])
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, -1), 1.2, title_color),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [head, Spacer(1, 5 * mm)]


def _info_block(styles: dict, pairs: Sequence[tuple]) -> Table:
    """Bloc d'informations en deux colonnes (libellé : valeur)."""
    rows = []
    for i in range(0, len(pairs), 2):
        left_lbl, left_val = pairs[i]
        cells = [
            Paragraph(f"<b>{left_lbl}</b>", styles["label"]),
            Paragraph(str(left_val), styles["value"]),
        ]
        if i + 1 < len(pairs):
            right_lbl, right_val = pairs[i + 1]
            cells += [
                Paragraph(f"<b>{right_lbl}</b>", styles["label"]),
                Paragraph(str(right_val), styles["value"]),
            ]
        else:
            cells += ["", ""]
        rows.append(cells)
    t = Table(rows, colWidths=[28 * mm, 67 * mm, 28 * mm, None])
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return t


def _lines_table(headers: Sequence[str], rows: Sequence[Sequence],
                 col_widths=None, header_color=_PRIMARY) -> Table:
    data = [list(headers)] + [list(r) for r in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
            ]
        )
    )
    return t


def _signatures(styles: dict, labels: Sequence[str]) -> Table:
    cells = [Paragraph(f"<br/><br/><br/>____________________<br/><b>{lbl}</b>",
                       styles["small"]) for lbl in labels]
    t = Table([cells], colWidths=[None] * len(labels))
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 14),
            ]
        )
    )
    return t


def _footer_story(styles: dict) -> list:
    info = settings_service.get_company_info()
    txt = info["footer"] or "Document généré automatiquement — Gestionnaire de stock"
    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    return [Spacer(1, 6 * mm), Paragraph(f"{txt} — Édité le {stamp}", styles["footer"])]


def _build(file_path: Path, story: list, page_size=A4) -> Path:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=page_size,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    doc.build(story)
    return file_path


# --- Bon d'entrée / de sortie ------------------------------------------------

def bon_mouvement_pdf(movement, product=None) -> Path:
    """Génère le bon PDF d'un mouvement de stock (entrée ou sortie)."""
    styles = _styles()
    is_entree = movement.type == "entree"
    prefix = "BE" if is_entree else "BS"
    title = "BON D'ENTRÉE" if is_entree else "BON DE SORTIE"
    color = _ENTREE if is_entree else _SORTIE
    numero = f"{prefix}-{(movement.id or 0):06d}"

    prix_unitaire = float(getattr(product, "prix_unitaire", 0) or 0)
    valeur = prix_unitaire * float(movement.quantite)

    story = _header_story(styles, title, title_color=color)
    story.append(_info_block(styles, [
        ("N° du bon", numero),
        ("Date", movement.created_at),
        ("Produit", movement.product_nom),
        ("Référence", getattr(product, "reference", "") or "—"),
        ("Type", "Entrée de stock" if is_entree else "Sortie de stock"),
        ("Agent", movement.agent_nom),
    ]))
    story.append(Spacer(1, 5 * mm))

    headers = ["Désignation", "Quantité", "Prix unitaire", "Valeur", "Stock après"]
    rows = [[
        movement.product_nom,
        f"{movement.quantite:g}",
        format_money(prix_unitaire),
        format_money(valeur),
        f"{movement.stock_apres:g}",
    ]]
    story.append(_lines_table(
        headers, rows,
        col_widths=[None, 25 * mm, 32 * mm, 35 * mm, 25 * mm],
        header_color=color,
    ))

    if movement.motif:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(f"<b>Motif :</b> {movement.motif}", styles["value"]))

    story.append(Spacer(1, 10 * mm))
    sig_left = "Le magasinier" if is_entree else "Remis par (magasinier)"
    sig_right = "Le fournisseur / réceptionnaire" if is_entree else "Reçu par (bénéficiaire)"
    story.append(_signatures(styles, [sig_left, sig_right]))
    story += _footer_story(styles)

    fname = f"{numero}_{slugify(movement.product_nom)}.pdf"
    return _build(_bons_dir() / fname, story)


# --- Fiche article -----------------------------------------------------------

def fiche_article_pdf(product, movements: Optional[List] = None) -> Path:
    """Fiche d'un produit : caractéristiques + historique des mouvements."""
    styles = _styles()
    movements = movements or []
    valeur_stock = float(product.quantite_stock) * float(product.prix_unitaire)

    story = _header_story(styles, "FICHE ARTICLE")
    story.append(_info_block(styles, [
        ("Référence", product.reference or "—"),
        ("Nom", product.nom),
        ("Prix unitaire", format_money(product.prix_unitaire)),
        ("Stock actuel", f"{product.quantite_stock:g}"),
        ("Seuil d'alerte", f"{product.seuil_alerte:g}"),
        ("Valeur du stock", format_money(valeur_stock)),
        ("Statut", "Actif" if product.actif else "Inactif"),
        ("État", "⚠ En alerte" if product.en_alerte() else "Normal"),
    ]))
    if product.description:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"<b>Description :</b> {product.description}", styles["value"]))

    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("<b>Historique des mouvements</b>", styles["value"]))
    story.append(Spacer(1, 2 * mm))

    headers = ["Date", "Type", "Quantité", "Stock après", "Motif", "Agent"]
    rows = [
        [
            m.created_at,
            "Entrée" if m.type == "entree" else "Sortie",
            f"{m.quantite:g}",
            f"{m.stock_apres:g}",
            m.motif or "—",
            m.agent_nom,
        ]
        for m in movements
    ]
    if not rows:
        rows = [["—", "—", "—", "—", "Aucun mouvement", "—"]]
    story.append(_lines_table(
        headers, rows,
        col_widths=[34 * mm, 18 * mm, 20 * mm, 22 * mm, None, 32 * mm],
    ))
    story += _footer_story(styles)

    fname = f"fiche_{slugify(product.reference or product.nom)}.pdf"
    return _build(_bons_dir() / fname, story)


# --- Inventaire --------------------------------------------------------------

def inventaire_pdf(products: Sequence, titre: str = "FICHE D'INVENTAIRE") -> Path:
    """État du stock avec colonnes vierges pour le comptage physique et l'écart."""
    styles = _styles()
    story = _header_story(styles, titre)
    stamp = datetime.now().strftime("%d/%m/%Y")
    story.append(Paragraph(f"Date de l'inventaire : <b>{stamp}</b>", styles["value"]))
    story.append(Spacer(1, 4 * mm))

    headers = ["Réf.", "Désignation", "Prix unit.", "Stock théorique",
               "Valeur", "Comptage physique", "Écart"]
    rows = []
    total_valeur = 0.0
    for p in products:
        valeur = float(p.quantite_stock) * float(p.prix_unitaire)
        total_valeur += valeur
        rows.append([
            p.reference or "—",
            p.nom,
            format_money(p.prix_unitaire),
            f"{p.quantite_stock:g}",
            format_money(valeur),
            "",   # comptage physique (à remplir à la main)
            "",   # écart
        ])
    if not rows:
        rows = [["—", "Aucun produit", "—", "—", "—", "", ""]]

    table = _lines_table(
        headers, rows,
        col_widths=[22 * mm, None, 28 * mm, 26 * mm, 30 * mm, 30 * mm, 22 * mm],
    )
    story.append(table)

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"<b>Valeur totale du stock théorique : {format_money(total_valeur)}</b>",
        styles["total"],
    ))

    story.append(Spacer(1, 10 * mm))
    story.append(_signatures(styles, ["Le magasinier", "Le contrôleur", "La direction"]))
    story += _footer_story(styles)

    fname = f"inventaire_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return _build(_bons_dir() / fname, story, page_size=landscape(A4))
