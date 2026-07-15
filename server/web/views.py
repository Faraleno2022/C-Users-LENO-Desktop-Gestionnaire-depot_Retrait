"""Vues de la console web : consultation + édition catalogue/clients/comptes."""
from __future__ import annotations

import json
import uuid as uuid_mod
from datetime import date, datetime, time, timedelta
from functools import wraps

import bcrypt
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from sync.models import (
    AuditLog, Client, Device, Product, RemoteUser, Sale, StockEntryRequest,
    StockMovement, Transaction,
)
from web import reports as web_reports
from web.reports import build_excel, build_pdf, _fmt_money, _fmt_num


def _export_response(fmt: str, slug: str, title: str, headers, rows, subtitle: str = ""):
    """Construit une réponse HTTP de téléchargement Excel (xlsx) ou PDF.

    `fmt` vaut "xlsx" ou "pdf". `slug` sert de base au nom de fichier.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "xlsx":
        excel_title = f"{title} ({subtitle})" if subtitle else title
        content = build_excel(excel_title, headers, rows)
        resp = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="{slug}_{ts}.xlsx"'
        return resp
    content = build_pdf(title, headers, rows, subtitle=subtitle)
    resp = HttpResponse(content, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{slug}_{ts}.pdf"'
    return resp


PAGE_SIZE = 50
ROLES = ("super_admin", "admin", "superviseur", "caissier")
ROLE_LABELS = {
    "super_admin": "Super administrateur",
    "admin": "Administrateur",
    "superviseur": "Superviseur",
    "caissier": "Caissier",
}


def role_required(*allowed_roles):
    """Décorateur : exige que session.remote_user.role soit dans allowed_roles."""
    def wrap(view):
        @wraps(view)
        def inner(request, *args, **kwargs):
            r = request.session.get("remote_user") or {}
            if r.get("role") not in allowed_roles:
                return HttpResponseForbidden(
                    "Accès refusé : cette page est réservée à : "
                    + ", ".join(ROLE_LABELS.get(x, x) for x in allowed_roles)
                )
            return view(request, *args, **kwargs)
        return inner
    return wrap


def _can_delete(remote) -> bool:
    """Vrai si l'utilisateur courant peut supprimer/restaurer des opérations.

    Les super_admin / admin l'ont d'office. Un autre rôle ne l'a que si le flag
    `can_delete` a été activé sur sa fiche (responsable autorisé).
    """
    remote = remote or {}
    if remote.get("role") in ("super_admin", "admin"):
        return True
    ident = remote.get("identifiant")
    if ident:
        u = RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()
        if u and getattr(u, "can_delete", False):
            return True
    return False


def delete_required(view):
    """Décorateur : exige la permission de suppression (admin ou responsable autorisé)."""
    @wraps(view)
    def inner(request, *args, **kwargs):
        if not _can_delete(request.session.get("remote_user") or {}):
            return HttpResponseForbidden(
                "Suppression réservée aux administrateurs et aux responsables autorisés."
            )
        return view(request, *args, **kwargs)
    return inner


def _iso_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _limit(value: str, max_len: int, label: str) -> str:
    """Refuse une saisie plus longue que la colonne en base.

    SQLite (console locale) accepte les dépassements mais PostgreSQL (site en
    ligne) répond par une erreur 500 : on renvoie plutôt un message clair.
    """
    if len(value) > max_len:
        raise ValueError(
            f"{label} : {max_len} caractères maximum "
            f"(saisie actuelle : {len(value)})."
        )
    return value


def _log_audit(request, action: str, target_type: str = "", target_id: str = "", details: str = "") -> None:
    """Crée une entrée d'audit web. Sera synchronisée au poste au prochain pull."""
    r = request.session.get("remote_user") or {}
    AuditLog.objects.create(
        uuid=str(uuid_mod.uuid4()),
        user_uuid=r.get("identifiant") and (
            # Récupère le vrai uuid via lookup ; fallback ""
            (RemoteUser.objects.filter(identifiant=r.get("identifiant")).values_list("uuid", flat=True).first() or "")
        ) or "",
        user_identifiant=r.get("identifiant") or "",
        action=f"web.{action}",
        target_type=target_type or "",
        target_id=str(target_id) if target_id else "",
        details=details or "",
        created_at=_iso_now(),
    )
    # Réveille la boucle de réplication de la console locale : le changement
    # (client, opération…) part TOUT DE SUITE vers le serveur en ligne, sans
    # attendre le prochain cycle. No-op sur le serveur en ligne (Render).
    try:
        from sync.livesync import request_sync
        request_sync()
    except Exception:
        pass


def _remote(request):
    return request.session.get("remote_user") or {}


def login_view(request):
    if request.user.is_authenticated:
        return redirect("web:dashboard")
    error = None
    if request.method == "POST":
        username = (request.POST.get("identifiant") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("web:dashboard")
        error = "Identifiant ou mot de passe incorrect."
    return render(request, "web/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("web:login")


def _today_range():
    today = date.today()
    start = datetime.combine(today, time.min).isoformat(sep=" ")
    end = datetime.combine(today, time.max).isoformat(sep=" ")
    return start, end


def _month_range():
    today = date.today()
    first = today.replace(day=1)
    start = datetime.combine(first, time.min).isoformat(sep=" ")
    end = datetime.combine(today, time.max).isoformat(sep=" ")
    return start, end


def _dashboard_stats() -> dict:
    """Chiffres du tableau de bord (valeurs brutes). Partagé par la page et l'API."""
    tx = Transaction.objects.filter(deleted=False)
    depots = tx.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    retraits = tx.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0
    ventes_all = Sale.objects.filter(deleted=False).aggregate(s=Sum("montant_total"))["s"] or 0
    # Solde global = dépôts − retraits − ventes (cohérent avec le solde par client).
    solde = float(depots) - float(retraits) - float(ventes_all)

    today_from, today_to = _today_range()
    tx_today = tx.filter(created_at__gte=today_from, created_at__lte=today_to)
    depots_today = tx_today.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    retraits_today = tx_today.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0
    n_today = tx_today.count()

    month_from, month_to = _month_range()
    tx_month = tx.filter(created_at__gte=month_from, created_at__lte=month_to)
    depots_month = tx_month.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    retraits_month = tx_month.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0

    sales = Sale.objects.filter(deleted=False)
    sales_today = sales.filter(created_at__gte=today_from, created_at__lte=today_to)
    sales_month = sales.filter(created_at__gte=month_from, created_at__lte=month_to)
    s_today = sales_today.aggregate(s=Sum("montant_total"))["s"] or 0
    n_sales_today = sales_today.count()
    s_month = sales_month.aggregate(s=Sum("montant_total"))["s"] or 0

    products = Product.objects.filter(actif=True)
    n_products = products.count()
    stock_value = sum((p.quantite_stock or 0) * (p.prix_unitaire or 0) for p in products)
    n_low_stock = sum(1 for p in products if (p.quantite_stock or 0) <= (p.seuil_alerte or 0))

    return {
        "solde": solde,
        "depots_today": depots_today,
        # « Sorties » = retraits d'espèces + ventes de produits (tout ce qui sort).
        "sorties_today": float(retraits_today) + float(s_today),
        "sorties_month": float(retraits_month) + float(s_month),
        "n_today": n_today,
        "depots_month": depots_month,
        "sales_today_total": s_today,
        "sales_today_count": n_sales_today,
        "sales_month_total": s_month,
        "n_products": n_products,
        "stock_value": stock_value,
        "n_low_stock": n_low_stock,
        "n_clients": Client.objects.filter(actif=True).count(),
    }


@login_required(login_url="web:login")
def dashboard(request):
    ctx = _dashboard_stats()
    ctx["recent_tx"] = Transaction.objects.filter(deleted=False).order_by("-created_at")[:10]
    ctx["remote"] = _remote(request)
    return render(request, "web/dashboard.html", ctx)


@login_required(login_url="web:login")
def sync_now(request):
    """Force une synchronisation immédiate avec le serveur en ligne (console locale).

    Importe les nouveautés du serveur ET envoie les opérations locales, sans
    attendre le cycle automatique. N'a d'effet que sur une console locale
    (base SQLite) configurée pour la réplication ; sur le serveur central
    (Postgres), il n'y a rien à synchroniser.
    """
    from pathlib import Path as _Path

    from django.conf import settings as _settings

    db = _settings.DATABASES.get("default", {})
    if "sqlite" not in (db.get("ENGINE") or ""):
        return JsonResponse({
            "ok": False,
            "message": "Vous êtes sur le serveur central : les données y sont déjà à jour.",
        })

    data_dir = _Path(db.get("NAME")).resolve().parent
    cfg_path = data_dir / "render_sync.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return JsonResponse({
            "ok": False,
            "message": "Synchronisation en ligne non configurée sur ce poste.",
        })

    url = (cfg.get("url") or "").strip()
    token = (cfg.get("token") or "").strip()
    if not (cfg.get("enabled") and url and token and "COLLEZ-ICI" not in token):
        return JsonResponse({
            "ok": False,
            "message": "Synchronisation en ligne désactivée sur ce poste.",
        })

    # Synchronisation MANUELLE = re-synchronisation complète : on oublie les
    # filigranes de pull pour re-télécharger TOUTES les données du serveur.
    # Cela rattrape tout décalage si la sync automatique avait pris du retard
    # (filigrane bloqué). On garde les filigranes de push pour ne pas tout
    # ré-envoyer ; les enregistrements sont de toute façon idempotents (uuid).
    state_path = data_dir / "render_sync_state.json"
    try:
        st = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
        st = {k: v for k, v in st.items() if not str(k).startswith("pull_")}
        state_path.write_text(json.dumps(st), encoding="utf-8")
    except (OSError, ValueError):
        pass

    try:
        from sync.replicator import Replicator
        summary = Replicator(url, token, state_path).run_once()
    except Exception as e:
        return JsonResponse({
            "ok": False,
            "message": f"Serveur en ligne injoignable ({type(e).__name__}). Vérifiez internet.",
        })

    received = sum(v["inserted"] + v["updated"] for v in summary.values())
    sent = sum(v["pushed"] for v in summary.values())
    _log_audit(request, "sync_manual", target_type="sync",
               details=f"recu={received} envoye={sent}")
    return JsonResponse({
        "ok": True,
        "received": received,
        "sent": sent,
        "message": f"Synchronisé : {received} reçu(s), {sent} envoyé(s).",
    })


@login_required(login_url="web:login")
def dashboard_stats_api(request):
    """Renvoie les chiffres du tableau de bord en JSON (rafraîchissement auto)."""
    s = _dashboard_stats()
    money_keys = {
        "solde", "depots_today", "sorties_today", "depots_month",
        "sorties_month", "sales_today_total", "sales_month_total", "stock_value",
    }
    out = {}
    for k, v in s.items():
        out[k] = _fmt_money(v) if k in money_keys else v
    return JsonResponse(out)


def _paginate(request, qs, per_page=PAGE_SIZE):
    page = request.GET.get("page") or 1
    paginator = Paginator(qs, per_page)
    return paginator.get_page(page)


def _matricule_balance(matricule: str) -> float:
    """Solde courant côté serveur pour un matricule."""
    tx = Transaction.objects.filter(matricule=matricule, deleted=False)
    depots = tx.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    retraits = tx.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0
    ventes = Sale.objects.filter(matricule=matricule, deleted=False).aggregate(s=Sum("montant_total"))["s"] or 0
    return float(depots) - float(retraits) - float(ventes)


def _normalize_name(s: str) -> str:
    """Nom comparable : minuscules, espaces multiples réduits."""
    return " ".join((s or "").lower().split())


def _find_duplicate_product(nom: str, reference: str = ""):
    """Produit actif au nom (ou référence) équivalent, sinon None."""
    norm = _normalize_name(nom)
    ref = (reference or "").strip().lower()
    for p in Product.objects.filter(actif=True):
        if _normalize_name(p.nom) == norm:
            return p
        if ref and (p.reference or "").strip().lower() == ref:
            return p
    return None


@login_required(login_url="web:login")
def deposit_new(request):
    """Créer un dépôt depuis le web. Tous rôles autorisés (caissier compris).

    NB: les retraits et ventes restent réservés au poste pour éviter les
    doubles débits avec d'éventuelles opérations offline non synchronisées.
    """
    r = _remote(request)
    error = None
    last_receipt = None

    if request.method == "POST":
        try:
            matricule = (request.POST.get("matricule") or "").strip()
            if not matricule:
                raise ValueError("Le matricule est obligatoire.")
            telephone = (request.POST.get("telephone") or "").strip()
            note = (request.POST.get("note") or "").strip()
            montant_raw = (request.POST.get("montant") or "").strip().replace(" ", "")
            montant = float(montant_raw)
            if montant <= 0:
                raise ValueError("Le montant doit être strictement positif.")

            # Solde après opération côté serveur (snapshot à l'instant t).
            current = _matricule_balance(matricule)
            new_balance = current + montant

            # Retrouve le RemoteUser courant (par identifiant en session) pour
            # alimenter agent_uuid/agent_id/agent_nom.
            agent = None
            ident = r.get("identifiant")
            if ident:
                agent = RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()

            tx = Transaction.objects.create(
                uuid=str(uuid_mod.uuid4()),
                matricule=matricule,
                telephone=telephone,
                type="depot",
                montant=montant,
                solde_apres=new_balance,
                agent_id=(agent.id if agent else None),
                agent_uuid=(agent.uuid if agent else ""),
                agent_nom=(agent.nom_complet if agent else r.get("nom_complet") or ""),
                note=note,
                created_at=_iso_now(),
                deleted=False,
            )
            _log_audit(
                request, "depot_create", target_type="transaction", target_id=tx.uuid,
                details=f"matricule={matricule} montant={montant:.0f} solde_apres={new_balance:.0f}",
            )
            messages.success(
                request,
                f"Dépôt de {montant:,.0f} GNF enregistré pour {matricule}. "
                f"Nouveau solde : {new_balance:,.0f} GNF.",
            )
            last_receipt = {
                "id": tx.id,
                "matricule": matricule,
                "telephone": telephone,
                "montant": montant,
                "solde_apres": new_balance,
                "created_at": tx.created_at,
                "agent_nom": tx.agent_nom,
            }
            # On vide le formulaire en redirigeant (PRG pattern).
            request.session["last_deposit"] = last_receipt
            return redirect("web:deposit_new")
        except (ValueError, TypeError) as e:
            error = str(e)

    # On conserve le reçu en session (sans le retirer) pour permettre
    # l'impression du ticket de caisse.
    last_receipt = request.session.get("last_deposit")
    return render(request, "web/deposit_form.html", {
        "error": error,
        "remote": r,
        "last_receipt": last_receipt,
    })


@login_required(login_url="web:login")
def withdrawal_new(request):
    """Créer un retrait depuis le web — opération risquée (avertissement explicite).

    Risque : si le poste a fait des opérations sur ce matricule hors-ligne,
    le solde serveur ne les reflète pas, et le retrait pourrait amener le
    solde réel en négatif après réconciliation.
    """
    r = _remote(request)
    error = None
    # On conserve la dernière opération en session (sans la retirer) pour
    # permettre le téléchargement de la facture PDF et l'affichage de la fiche.
    last_receipt = request.session.get("last_withdrawal")
    products = Product.objects.filter(actif=True).order_by("nom")

    balance_preview = None
    matricule_preview = (request.GET.get("matricule") or "").strip()
    if matricule_preview:
        balance_preview = _matricule_balance(matricule_preview)

    if request.method == "POST":
        try:
            matricule = (request.POST.get("matricule") or "").strip()
            if not matricule:
                raise ValueError("Le matricule est obligatoire.")
            telephone = (request.POST.get("telephone") or "").strip()
            note = (request.POST.get("note") or "").strip()
            confirmed = request.POST.get("confirmed") == "1"
            if not confirmed:
                raise ValueError(
                    "Vous devez confirmer avoir vérifié le solde réel avec le poste "
                    "avant de valider un retrait en ligne."
                )

            # --- Lignes de produits (optionnelles) ---
            # Les champs prod_id / prod_qte sont envoyés en tableaux parallèles.
            prod_ids = request.POST.getlist("prod_id")
            prod_qtes = request.POST.getlist("prod_qte")
            lines = []           # données affichables sur la fiche
            products_total = 0.0
            for pid, q in zip(prod_ids, prod_qtes):
                pid = (pid or "").strip()
                q = (q or "").strip().replace(" ", "")
                if not pid:
                    continue
                quantite = float(q or 0)
                if quantite <= 0:
                    continue
                product = Product.objects.filter(pk=int(pid), actif=True).first()
                if product is None:
                    raise ValueError("Un produit sélectionné est invalide ou inactif.")
                stock = float(product.quantite_stock or 0)
                if quantite > stock:
                    raise ValueError(
                        f"Stock insuffisant pour « {product.nom} » : "
                        f"{stock:g} disponible, {quantite:g} demandé."
                    )
                prix = float(product.prix_unitaire or 0)
                line_total = prix * quantite
                products_total += line_total
                lines.append({
                    "product": product, "product_nom": product.nom,
                    "quantite": quantite, "prix": prix, "total": line_total,
                })

            # Montant global : piloté par les produits si présents, sinon saisie manuelle.
            montant_raw = (request.POST.get("montant") or "").strip().replace(" ", "")
            manual_montant = float(montant_raw) if montant_raw else 0.0
            montant = products_total if lines else manual_montant
            if montant <= 0:
                raise ValueError(
                    "Ajoutez au moins un produit ou saisissez un montant positif."
                )

            current = _matricule_balance(matricule)
            if montant > current:
                raise ValueError(
                    f"Solde insuffisant côté serveur : disponible {current:.0f} GNF, "
                    f"demande {montant:.0f} GNF."
                )
            new_balance = current - montant

            agent = None
            ident = r.get("identifiant")
            if ident:
                agent = RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()
            agent_id = agent.id if agent else None
            agent_uuid = agent.uuid if agent else ""
            agent_nom = agent.nom_complet if agent else (r.get("nom_complet") or "")

            # Note enrichie avec le détail des produits.
            detail = ", ".join(f"{l['product_nom']} x{l['quantite']:g}" for l in lines)
            note_full = note
            if detail:
                note_full = (f"{note} | " if note else "") + f"Produits: {detail}"

            # Avec produits : on enregistre une VENTE par produit (débit du
            # solde + décrément du stock). Ces ventes apparaissent dans /ventes/
            # et sont annulables — l'annulation rétablit le stock et le solde.
            # Sans produit : c'est un retrait d'espèces (transaction retrait).
            if lines:
                running = current
                first_id = None
                for l in lines:
                    product = l["product"]
                    running -= l["total"]
                    new_stock = float(product.quantite_stock or 0) - l["quantite"]
                    sale = Sale.objects.create(
                        uuid=str(uuid_mod.uuid4()),
                        matricule=matricule, telephone=telephone,
                        product_id=product.id, product_uuid=product.uuid,
                        product_nom=product.nom,
                        quantite=l["quantite"], prix_unitaire=l["prix"],
                        montant_total=l["total"], solde_apres=running,
                        agent_id=agent_id, agent_uuid=agent_uuid, agent_nom=agent_nom,
                        note=note, created_at=_iso_now(), deleted=False,
                    )
                    product.quantite_stock = new_stock
                    product.updated_at = _iso_now()
                    product.save()
                    StockMovement.objects.create(
                        uuid=str(uuid_mod.uuid4()),
                        product_id=product.id, product_uuid=product.uuid,
                        product_nom=product.nom,
                        type="sortie", quantite=l["quantite"], stock_apres=new_stock,
                        motif=f"Vente {matricule}", sale_id=sale.id,
                        agent_id=agent_id, agent_uuid=agent_uuid, agent_nom=agent_nom,
                        created_at=_iso_now(),
                    )
                    if first_id is None:
                        first_id = sale.id
                _log_audit(
                    request, "sale_create", target_type="sale",
                    target_id=str(first_id or ""),
                    details=f"matricule={matricule} montant={montant:.0f} "
                            f"solde_apres={new_balance:.0f} produits=[{detail}]",
                )
                messages.success(
                    request,
                    f"Vente de {montant:,.0f} GNF enregistrée pour {matricule}. "
                    f"Nouveau solde : {new_balance:,.0f} GNF.",
                )
                receipt_id, receipt_at = first_id, _iso_now()
            else:
                tx = Transaction.objects.create(
                    uuid=str(uuid_mod.uuid4()),
                    matricule=matricule, telephone=telephone, type="retrait",
                    montant=montant, solde_apres=new_balance,
                    agent_id=agent_id, agent_uuid=agent_uuid, agent_nom=agent_nom,
                    note=note_full, created_at=_iso_now(), deleted=False,
                )
                _log_audit(
                    request, "retrait_create", target_type="transaction", target_id=tx.uuid,
                    details=f"matricule={matricule} montant={montant:.0f} "
                            f"solde_apres={new_balance:.0f}",
                )
                messages.success(
                    request,
                    f"Retrait de {montant:,.0f} GNF enregistré pour {matricule}. "
                    f"Nouveau solde : {new_balance:,.0f} GNF.",
                )
                receipt_id, receipt_at = tx.id, tx.created_at

            request.session["last_withdrawal"] = {
                "id": receipt_id,
                "matricule": matricule,
                "telephone": telephone,
                "montant": montant,
                "solde_avant": current,
                "solde_apres": new_balance,
                "created_at": receipt_at,
                "agent_nom": agent_nom,
                "is_sale": bool(lines),
                "lines": [
                    {"product_nom": l["product_nom"], "quantite": l["quantite"],
                     "prix": l["prix"], "total": l["total"]}
                    for l in lines
                ],
            }
            return redirect("web:withdrawal_new")
        except (ValueError, TypeError) as e:
            error = str(e)

    return render(request, "web/withdrawal_form.html", {
        "error": error,
        "remote": r,
        "products": products,
        "last_receipt": last_receipt,
        "balance_preview": balance_preview,
        "matricule_preview": matricule_preview,
    })


@login_required(login_url="web:login")
def matricule_balance_api(request):
    """Renvoie en JSON le solde serveur d'un matricule (chargement temps réel)."""
    matricule = (request.GET.get("matricule") or "").strip()
    if not matricule:
        return JsonResponse({"matricule": "", "balance": 0.0, "found": False,
                             "nom": "", "telephone": ""})
    balance = _matricule_balance(matricule)
    client = Client.objects.filter(matricule=matricule).first()

    # Téléphone : priorité à la fiche client, sinon dernière opération connue
    # (le numéro est enregistré sur chaque transaction / vente).
    telephone = (client.telephone if client and client.telephone else "")
    if not telephone:
        last_tx = (
            Transaction.objects.filter(matricule=matricule)
            .exclude(telephone="").order_by("-created_at", "-id").first()
        )
        if last_tx:
            telephone = last_tx.telephone
        else:
            last_sale = (
                Sale.objects.filter(matricule=matricule)
                .exclude(telephone="").order_by("-created_at", "-id").first()
            )
            if last_sale:
                telephone = last_sale.telephone

    found = (
        client is not None
        or Transaction.objects.filter(matricule=matricule, deleted=False).exists()
    )
    return JsonResponse({
        "matricule": matricule,
        "balance": balance,
        "found": found,
        "nom": client.nom if client else "",
        "telephone": telephone,
    })


@login_required(login_url="web:login")
def withdrawal_invoice(request):
    """Télécharge la facture PDF du dernier retrait enregistré (depuis la session)."""
    data = request.session.get("last_withdrawal")
    if not data:
        messages.warning(request, "Aucune facture récente à télécharger.")
        return redirect("web:withdrawal_new")
    content = web_reports.build_withdrawal_invoice(data)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    mat = (data.get("matricule") or "client").replace(" ", "_")
    resp = HttpResponse(content, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="facture_{mat}_{ts}.pdf"'
    return resp


@login_required(login_url="web:login")
def print_ticket(request):
    """Reçu au format ticket pour imprimante thermique de caisse (rouleau 58/80 mm).

    Lit la dernière opération en session (dépôt ou retrait/vente) et l'affiche
    en HTML optimisé pour l'impression sur rouleau. Le navigateur envoie le rendu
    à l'imprimante thermique installée comme imprimante Windows.
    """
    kind = (request.GET.get("kind") or "retrait").strip()
    width = "58" if (request.GET.get("w") or "80").strip() == "58" else "80"
    auto = request.GET.get("auto") == "1"

    if kind == "depot":
        data = request.session.get("last_deposit")
    else:
        data = request.session.get("last_withdrawal")
    if not data:
        messages.warning(request, "Aucun reçu récent à imprimer.")
        return redirect("web:deposit_new" if kind == "depot" else "web:withdrawal_new")

    montant = float(data.get("montant") or 0)
    solde_apres = float(data.get("solde_apres") or 0)
    if kind == "depot":
        solde_avant = solde_apres - montant
        titre, signe = "REÇU DE DÉPÔT", "+"
    else:
        solde_avant = float(data.get("solde_avant", solde_apres + montant))
        titre = "FACTURE DE VENTE" if data.get("is_sale") else "REÇU DE RETRAIT"
        signe = "−"

    try:
        from web.ticket_logo import TICKET_LOGO_DATA_URI as logo
    except Exception:
        logo = ""

    return render(request, "web/receipt_ticket.html", {
        "r": data,
        "kind": kind,
        "width": width,
        "auto": auto,
        "titre": titre,
        "signe": signe,
        "montant": montant,
        "solde_avant": solde_avant,
        "solde_apres": solde_apres,
        "company_name": "EMAB GROUP",
        "logo_uri": logo,
    })


@login_required(login_url="web:login")
def sale_new(request):
    """Obsolète : la vente de produits se fait désormais au niveau du retrait.

    On redirige vers la page de retrait (qui gère les produits + facture).
    """
    return redirect("web:withdrawal_new")


@login_required(login_url="web:login")
def transactions(request):
    qs = Transaction.objects.filter(deleted=False)
    matricule = (request.GET.get("matricule") or "").strip()
    type_ = (request.GET.get("type") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    agent = (request.GET.get("agent") or "").strip()

    if matricule:
        qs = qs.filter(matricule__icontains=matricule)
    if type_ in ("depot", "retrait"):
        qs = qs.filter(type=type_)
    if date_from:
        qs = qs.filter(created_at__gte=f"{date_from} 00:00:00")
    if date_to:
        qs = qs.filter(created_at__lte=f"{date_to} 23:59:59")
    if agent:
        qs = qs.filter(agent_nom__icontains=agent)

    qs = qs.order_by("-created_at")

    export = (request.GET.get("export") or "").strip()
    if export in ("xlsx", "pdf"):
        headers = ["Date", "Matricule", "Téléphone", "Type", "Montant",
                   "Solde après", "Agent", "Note"]
        rows = [[
            t.created_at, t.matricule, t.telephone or "",
            "Dépôt" if t.type == "depot" else "Retrait",
            _fmt_money(t.montant), _fmt_money(t.solde_apres),
            t.agent_nom or "", t.note or "",
        ] for t in qs]
        sub = "Dépôts / Retraits"
        if date_from or date_to:
            sub += f" — du {date_from or '…'} au {date_to or '…'}"
        return _export_response(export, "depots_retraits", "Dépôts / Retraits",
                                headers, rows, subtitle=sub)

    total_depots = qs.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    total_retraits = qs.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0
    n_total = qs.count()
    page_obj = _paginate(request, qs)

    return render(request, "web/transactions.html", {
        "page_obj": page_obj,
        "n_total": n_total,
        "total_depots": total_depots,
        "total_retraits": total_retraits,
        "filters": {
            "matricule": matricule,
            "type": type_,
            "date_from": date_from,
            "date_to": date_to,
            "agent": agent,
        },
        "remote": _remote(request),
        "can_delete": _can_delete(_remote(request)),
    })


@login_required(login_url="web:login")
def sales(request):
    qs = Sale.objects.filter(deleted=False)
    matricule = (request.GET.get("matricule") or "").strip()
    product = (request.GET.get("product") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()

    if matricule:
        qs = qs.filter(matricule__icontains=matricule)
    if product:
        qs = qs.filter(product_nom__icontains=product)
    if date_from:
        qs = qs.filter(created_at__gte=f"{date_from} 00:00:00")
    if date_to:
        qs = qs.filter(created_at__lte=f"{date_to} 23:59:59")

    qs = qs.order_by("-created_at")

    export = (request.GET.get("export") or "").strip()
    if export in ("xlsx", "pdf"):
        headers = ["Date", "Matricule", "Produit", "Qté", "Prix unit.",
                   "Total", "Solde après", "Agent"]
        rows = [[
            s.created_at, s.matricule, s.product_nom, _fmt_num(s.quantite),
            _fmt_money(s.prix_unitaire), _fmt_money(s.montant_total),
            _fmt_money(s.solde_apres), s.agent_nom or "",
        ] for s in qs]
        sub = "Ventes"
        if date_from or date_to:
            sub += f" — du {date_from or '…'} au {date_to or '…'}"
        return _export_response(export, "ventes", "Ventes", headers, rows, subtitle=sub)

    total = qs.aggregate(s=Sum("montant_total"))["s"] or 0
    n_total = qs.count()
    page_obj = _paginate(request, qs)

    return render(request, "web/sales.html", {
        "page_obj": page_obj,
        "n_total": n_total,
        "total": total,
        "filters": {
            "matricule": matricule,
            "product": product,
            "date_from": date_from,
            "date_to": date_to,
        },
        "remote": _remote(request),
        "can_delete": _can_delete(_remote(request)),
    })


@login_required(login_url="web:login")
def products(request):
    qs = Product.objects.all()
    search = (request.GET.get("q") or "").strip()
    only_low = request.GET.get("low") == "1"
    if search:
        qs = qs.filter(Q(nom__icontains=search) | Q(reference__icontains=search))
    if only_low:
        qs = qs.filter(quantite_stock__lte=F("seuil_alerte"))
    qs = qs.order_by("nom")

    export = (request.GET.get("export") or "").strip()
    if export in ("xlsx", "pdf"):
        headers = ["Référence", "Nom", "Prix unit.", "Stock", "Seuil",
                   "Valeur", "Statut"]
        rows = []
        for p in qs:
            if not p.actif:
                statut = "Inactif"
            elif (p.quantite_stock or 0) <= (p.seuil_alerte or 0):
                statut = "Stock bas"
            else:
                statut = "OK"
            rows.append([
                p.reference or "", p.nom, _fmt_money(p.prix_unitaire),
                _fmt_num(p.quantite_stock), _fmt_num(p.seuil_alerte),
                _fmt_money((p.quantite_stock or 0) * (p.prix_unitaire or 0)), statut,
            ])
        return _export_response(export, "produits_stock", "Produits & Stock",
                                headers, rows,
                                subtitle=f"Au {_iso_now()}")

    page_obj = _paginate(request, qs)
    # Pré-calcule la valeur stock (quantite × prix) car le filtre money ne sait pas multiplier.
    for p in page_obj:
        p.valeur = (p.quantite_stock or 0) * (p.prix_unitaire or 0)

    r = _remote(request)
    can_edit = r.get("role") in ("super_admin", "admin")
    return render(request, "web/products.html", {
        "page_obj": page_obj,
        "search": search,
        "only_low": only_low,
        "remote": r,
        "can_edit": can_edit,
        # Les agents (non-admin) ne saisissent pas directement : ils demandent
        # une entrée, qu'un admin valide ensuite.
        "can_request": not can_edit,
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def product_new(request):
    error = None
    if request.method == "POST":
        try:
            nom = _limit((request.POST.get("nom") or "").strip(), 200, "Nom du produit")
            if not nom:
                raise ValueError("Le nom est obligatoire.")
            reference = _limit((request.POST.get("reference") or "").strip(), 80, "Référence")
            # Anti-doublon : refuse un nom déjà utilisé (insensible à la casse et
            # aux espaces) ou une référence déjà prise, sauf si on force.
            force = request.POST.get("force_create") == "1"
            if not force:
                dup = _find_duplicate_product(nom, reference)
                if dup is not None:
                    raise ValueError(
                        f"Un produit identique semble déjà exister : « {dup.nom} »"
                        + (f" (réf. {dup.reference})" if dup.reference else "")
                        + ". Modifiez-le, ou cochez « créer quand même » si c'est"
                        " bien un produit différent."
                    )
            description = (request.POST.get("description") or "").strip()
            categorie = _limit((request.POST.get("categorie") or "").strip(), 120, "Catégorie")
            unite = _limit((request.POST.get("unite") or "").strip(), 40, "Unité")
            prix_achat = float(request.POST.get("prix_achat") or 0)
            prix = float(request.POST.get("prix_unitaire") or 0)
            if prix < 0:
                raise ValueError("Le prix doit être positif ou nul.")
            seuil = float(request.POST.get("seuil_alerte") or 0)
            stock_max = float(request.POST.get("stock_max") or 0)
            emplacement = _limit((request.POST.get("emplacement") or "").strip(), 120, "Emplacement")
            qte = float(request.POST.get("quantite_stock") or 0)
            now = _iso_now()
            p = Product.objects.create(
                uuid=str(uuid_mod.uuid4()),
                reference=reference,
                nom=nom,
                description=description,
                categorie=categorie,
                unite=unite,
                prix_achat=prix_achat,
                prix_unitaire=prix,
                quantite_stock=qte,
                seuil_alerte=seuil,
                stock_max=stock_max,
                emplacement=emplacement,
                actif=True,
                created_at=now,
                updated_at=now,
            )
            _log_audit(request, "product_create", target_type="product", target_id=p.uuid, details=nom)
            messages.success(request, f"Produit « {nom} » créé.")
            return redirect("web:products")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/product_form.html", {
        "product": None,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
def product_search_api(request):
    """Suggestions de produits existants pour éviter les doublons à la saisie."""
    q = _normalize_name(request.GET.get("q") or "")
    results = []
    if len(q) >= 2:
        words = [w for w in q.split() if len(w) >= 3]
        for p in Product.objects.filter(actif=True).order_by("nom"):
            name = _normalize_name(p.nom)
            if q in name or name in q or any(w in name for w in words):
                results.append({
                    "id": p.id,
                    "nom": p.nom,
                    "reference": p.reference or "",
                    "prix": _fmt_money(p.prix_unitaire),
                    "stock": _fmt_num(p.quantite_stock),
                })
            if len(results) >= 6:
                break
    return JsonResponse({"results": results})


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    error = None
    if request.method == "POST":
        try:
            nom = (request.POST.get("nom") or "").strip()
            if not nom:
                raise ValueError("Le nom est obligatoire.")
            prix = float(request.POST.get("prix_unitaire") or 0)
            if prix < 0:
                raise ValueError("Le prix doit être positif ou nul.")
            seuil = float(request.POST.get("seuil_alerte") or 0)
            prix_achat = float(request.POST.get("prix_achat") or 0)
            stock_max = float(request.POST.get("stock_max") or 0)
            actif = request.POST.get("actif") == "on"
            product.nom = _limit(nom, 200, "Nom du produit")
            product.reference = _limit((request.POST.get("reference") or "").strip(), 80, "Référence")
            product.description = (request.POST.get("description") or "").strip()
            product.categorie = _limit((request.POST.get("categorie") or "").strip(), 120, "Catégorie")
            product.unite = _limit((request.POST.get("unite") or "").strip(), 40, "Unité")
            product.prix_achat = prix_achat
            product.prix_unitaire = prix
            product.seuil_alerte = seuil
            product.stock_max = stock_max
            product.emplacement = _limit((request.POST.get("emplacement") or "").strip(), 120, "Emplacement")
            product.actif = actif
            product.updated_at = _iso_now()
            product.save()
            _log_audit(request, "product_update", target_type="product", target_id=product.uuid, details=nom)
            messages.success(request, f"Produit « {nom} » mis à jour.")
            return redirect("web:products")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/product_form.html", {
        "product": product,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def stock_adjust(request, pk):
    """Ajuste le stock d'un produit (entrée ou sortie). Crée un stock_movement.

    Limitation connue : si le poste a vendu offline depuis ce produit, le stock
    actuel côté serveur ne reflète pas cette vente. L'ajustement reste valide
    en absolu (delta), mais la quantité finale converge seulement à la prochaine
    sync. C'est une conséquence du modèle offline-first.
    """
    product = get_object_or_404(Product, pk=pk)
    error = None
    if request.method == "POST":
        try:
            type_ = (request.POST.get("type") or "").strip()
            if type_ not in ("entree", "sortie"):
                raise ValueError("Type de mouvement invalide.")
            qte_raw = (request.POST.get("quantite") or "").strip().replace(" ", "")
            quantite = float(qte_raw)
            if quantite <= 0:
                raise ValueError("La quantité doit être strictement positive.")
            motif = _limit((request.POST.get("motif") or "").strip(), 255, "Motif")

            current_stock = float(product.quantite_stock or 0)
            if type_ == "entree":
                new_stock = current_stock + quantite
            else:
                if quantite > current_stock:
                    raise ValueError(
                        f"Stock insuffisant : {current_stock:g} disponible, "
                        f"sortie demandée {quantite:g}."
                    )
                new_stock = current_stock - quantite

            # Agent (web)
            r = _remote(request)
            agent = None
            ident = r.get("identifiant")
            if ident:
                agent = RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()

            # Crée le mouvement
            mv = StockMovement.objects.create(
                uuid=str(uuid_mod.uuid4()),
                product_id=product.id,           # id serveur (sera traduit au pull)
                product_uuid=product.uuid,
                product_nom=product.nom,
                type=type_,
                quantite=quantite,
                stock_apres=new_stock,
                motif=motif,
                sale_id=None,
                agent_id=(agent.id if agent else None),
                agent_uuid=(agent.uuid if agent else ""),
                agent_nom=(agent.nom_complet if agent else r.get("nom_complet") or ""),
                created_at=_iso_now(),
            )
            # Met à jour le produit
            product.quantite_stock = new_stock
            product.updated_at = _iso_now()
            product.save()

            _log_audit(
                request,
                "stock_entree" if type_ == "entree" else "stock_sortie",
                target_type="product", target_id=product.uuid,
                details=f"{product.nom} : {type_} {quantite:g} → {new_stock:g}"
                + (f" — {motif}" if motif else ""),
            )

            messages.success(
                request,
                f"{'Entrée' if type_ == 'entree' else 'Sortie'} de {quantite:g} "
                f"unités enregistrée pour « {product.nom} ». Stock : {new_stock:g}.",
            )
            return redirect("web:products")
        except (ValueError, TypeError) as e:
            error = str(e)

    return render(request, "web/stock_form.html", {
        "product": product,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def product_toggle(request, pk):
    """Active/désactive un produit (équivalent suppression douce)."""
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        product.actif = not product.actif
        product.updated_at = _iso_now()
        product.save()
        _log_audit(
            request,
            "product_activate" if product.actif else "product_deactivate",
            target_type="product", target_id=product.uuid, details=product.nom,
        )
        messages.success(
            request,
            f"Produit « {product.nom} » {'activé' if product.actif else 'désactivé'}.",
        )
    return redirect("web:products")


# --- Circuit de validation des entrées de stock (agent saisit → admin valide) -

def _current_remote_user(request):
    """Fiche RemoteUser (la plus récente) correspondant à l'utilisateur connecté."""
    ident = _remote(request).get("identifiant")
    if not ident:
        return None
    return RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()


@login_required(login_url="web:login")
def stock_entry_request(request, pk):
    """Un agent (ou un admin) demande une ENTRÉE de stock pour un produit.

    La demande est enregistrée « en attente » : elle n'affecte PAS le stock réel
    tant qu'un administrateur ne l'a pas validée (cf. stock_request_validate).
    """
    product = get_object_or_404(Product, pk=pk)
    error = None
    if request.method == "POST":
        try:
            qte_raw = (request.POST.get("quantite") or "").strip().replace(" ", "")
            quantite = float(qte_raw)
            if quantite <= 0:
                raise ValueError("La quantité doit être strictement positive.")
            motif = _limit((request.POST.get("motif") or "").strip(), 255, "Motif")
            agent = _current_remote_user(request)
            r = _remote(request)
            StockEntryRequest.objects.create(
                uuid=str(uuid_mod.uuid4()),
                kind="entree",
                product_uuid=product.uuid,
                product_nom=product.nom,
                quantite=quantite,
                motif=motif,
                statut="en_attente",
                requested_by_identifiant=r.get("identifiant") or "",
                requested_by_nom=(agent.nom_complet if agent else r.get("nom_complet") or ""),
                requested_by_uuid=(agent.uuid if agent else ""),
                created_at=_iso_now(),
            )
            _log_audit(
                request, "stock_entry_request", target_type="product",
                target_id=product.uuid,
                details=f"{product.nom} : demande entrée {quantite:g}"
                + (f" — {motif}" if motif else ""),
            )
            messages.success(
                request,
                f"Demande d'entrée de {quantite:g} pour « {product.nom} » envoyée. "
                "Elle sera effective après validation par un administrateur.",
            )
            return redirect("web:products")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/stock_entry_request.html", {
        "product": product,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
def product_request_new(request):
    """Un agent propose la création d'un NOUVEAU produit.

    La proposition est « en attente » : le produit n'existe PAS tant qu'un
    administrateur ne l'a pas validée (cf. stock_request_validate). À la
    validation, le produit est créé et sa quantité initiale enregistrée comme
    mouvement d'entrée.
    """
    error = None
    if request.method == "POST":
        try:
            nom = _limit((request.POST.get("nom") or "").strip(), 200, "Nom du produit")
            if not nom:
                raise ValueError("Le nom du produit est obligatoire.")
            reference = _limit((request.POST.get("reference") or "").strip(), 80, "Référence")
            prix = float(request.POST.get("prix_unitaire") or 0)
            if prix < 0:
                raise ValueError("Le prix doit être positif ou nul.")
            seuil = float(request.POST.get("seuil_alerte") or 0)
            qte = float((request.POST.get("quantite") or "0").strip().replace(" ", ""))
            if qte < 0:
                raise ValueError("La quantité initiale doit être positive ou nulle.")
            description = (request.POST.get("description") or "").strip()
            motif = _limit((request.POST.get("motif") or "").strip(), 255, "Motif")
            # Anti-doublon : si un produit du même nom existe déjà, orienter vers
            # une simple demande d'entrée (sauf si l'agent force).
            if request.POST.get("force_create") != "1":
                dup = _find_duplicate_product(nom, reference)
                if dup is not None:
                    raise ValueError(
                        f"Un produit « {dup.nom} » semble déjà exister. Faites plutôt "
                        "une « demande d'entrée » dessus, ou cochez « proposer quand "
                        "même » si c'est réellement un autre produit."
                    )
            agent = _current_remote_user(request)
            r = _remote(request)
            StockEntryRequest.objects.create(
                uuid=str(uuid_mod.uuid4()),
                kind="nouveau_produit",
                product_uuid="",
                product_nom=nom,
                quantite=qte,
                new_reference=reference,
                new_prix_unitaire=prix,
                new_seuil_alerte=seuil,
                new_description=description,
                motif=motif,
                statut="en_attente",
                requested_by_identifiant=r.get("identifiant") or "",
                requested_by_nom=(agent.nom_complet if agent else r.get("nom_complet") or ""),
                requested_by_uuid=(agent.uuid if agent else ""),
                created_at=_iso_now(),
            )
            _log_audit(
                request, "product_request_new", target_type="product", target_id="",
                details=f"Proposition nouveau produit : {nom} (qté initiale {qte:g})",
            )
            messages.success(
                request,
                f"Proposition du produit « {nom} » envoyée. Il sera créé après "
                "validation par un administrateur.",
            )
            return redirect("web:products")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/product_request_form.html", {
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def stock_validations(request):
    """Liste des demandes d'entrée de stock à valider (admin)."""
    statut = (request.GET.get("statut") or "en_attente").strip()
    qs = StockEntryRequest.objects.all()
    if statut in ("en_attente", "valide", "rejete"):
        qs = qs.filter(statut=statut)
    page_obj = _paginate(request, qs)
    return render(request, "web/stock_validations.html", {
        "page_obj": page_obj,
        "statut": statut,
        "pending_count": StockEntryRequest.objects.filter(statut="en_attente").count(),
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def stock_request_validate(request, pk):
    """Valide une demande : crée le mouvement d'entrée et incrémente le stock réel."""
    req = get_object_or_404(StockEntryRequest, pk=pk)
    if request.method != "POST":
        return redirect("web:stock_validations")
    if req.statut != "en_attente":
        messages.warning(request, "Cette demande a déjà été traitée.")
        return redirect("web:stock_validations")

    now = _iso_now()
    if req.kind == "nouveau_produit":
        # Création du produit proposé par l'agent (refus de doublon strict).
        if _find_duplicate_product(req.product_nom, req.new_reference) is not None:
            messages.warning(
                request,
                f"Un produit « {req.product_nom} » existe déjà : validation annulée. "
                "Rejetez cette proposition et faites une entrée sur le produit existant.",
            )
            return redirect("web:stock_validations")
        product = Product.objects.create(
            uuid=str(uuid_mod.uuid4()),
            reference=req.new_reference,
            nom=req.product_nom,
            description=req.new_description,
            prix_unitaire=req.new_prix_unitaire,
            quantite_stock=0,
            seuil_alerte=req.new_seuil_alerte,
            actif=True,
            created_at=now,
            updated_at=now,
        )
    else:
        product = Product.objects.filter(uuid=req.product_uuid).first()
        if product is None:
            messages.warning(request, "Produit introuvable pour cette demande.")
            return redirect("web:stock_validations")

    current_stock = float(product.quantite_stock or 0)
    entree = float(req.quantite or 0)
    new_stock = current_stock + entree

    # Mouvement d'entrée (crédité à l'agent demandeur) — seulement si quantité > 0.
    mv_uuid = ""
    if entree > 0:
        mv = StockMovement.objects.create(
            uuid=str(uuid_mod.uuid4()),
            product_id=product.id,
            product_uuid=product.uuid,
            product_nom=product.nom,
            type="entree",
            quantite=entree,
            stock_apres=new_stock,
            motif=(req.motif or ("Stock initial (nouveau produit)"
                   if req.kind == "nouveau_produit" else "Entrée validée")),
            sale_id=None,
            agent_id=None,
            agent_uuid=req.requested_by_uuid,
            agent_nom=req.requested_by_nom or "—",
            created_at=now,
        )
        mv_uuid = mv.uuid
        product.quantite_stock = new_stock
        product.updated_at = now
        product.save()

    r = _remote(request)
    req.statut = "valide"
    req.product_uuid = product.uuid  # rattache le produit (cas nouveau produit)
    req.validated_by_identifiant = r.get("identifiant") or ""
    req.validated_by_nom = r.get("nom_complet") or ""
    req.validated_at = now
    req.resulting_movement_uuid = mv_uuid
    req.save()

    if req.kind == "nouveau_produit":
        _log_audit(
            request, "product_request_validate", target_type="product",
            target_id=product.uuid,
            details=f"Nouveau produit créé « {product.nom} » (stock initial {entree:g}) "
            f"— proposé par {req.requested_by_nom or '—'}",
        )
        messages.success(
            request,
            f"Produit « {product.nom} » créé et validé. Stock initial : {new_stock:g}.",
        )
    else:
        _log_audit(
            request, "stock_entry_validate", target_type="product",
            target_id=product.uuid,
            details=f"{product.nom} : entrée validée {entree:g} → {new_stock:g} "
            f"(demandée par {req.requested_by_nom or '—'})",
        )
        messages.success(
            request,
            f"Entrée de {entree:g} validée pour « {product.nom} ». "
            f"Stock réel : {new_stock:g}.",
        )
    return redirect("web:stock_validations")


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def stock_request_reject(request, pk):
    """Rejette une demande : aucune incidence sur le stock."""
    req = get_object_or_404(StockEntryRequest, pk=pk)
    if request.method != "POST":
        return redirect("web:stock_validations")
    if req.statut != "en_attente":
        messages.warning(request, "Cette demande a déjà été traitée.")
        return redirect("web:stock_validations")

    r = _remote(request)
    req.statut = "rejete"
    req.decision_motif = (request.POST.get("motif") or "").strip()
    req.validated_by_identifiant = r.get("identifiant") or ""
    req.validated_by_nom = r.get("nom_complet") or ""
    req.validated_at = _iso_now()
    req.save()

    est_nouveau = req.kind == "nouveau_produit"
    _log_audit(
        request, "product_request_reject" if est_nouveau else "stock_entry_reject",
        target_type="product",
        target_id=req.product_uuid,
        details=(f"Nouveau produit refusé : {req.product_nom}" if est_nouveau
                 else f"{req.product_nom} : entrée refusée {req.quantite:g}")
        + (f" — {req.decision_motif}" if req.decision_motif else ""),
    )
    if est_nouveau:
        messages.info(
            request,
            f"Proposition du produit « {req.product_nom} » rejetée. "
            "Aucun produit n'a été créé.",
        )
    else:
        messages.info(
            request,
            f"Demande d'entrée de {req.quantite:g} pour « {req.product_nom} » rejetée. "
            "Le stock n'a pas été modifié.",
        )
    return redirect("web:stock_validations")


@login_required(login_url="web:login")
def pending_stock_api(request):
    """Compteur des demandes de stock en attente (produits/entrées proposés par
    les agents). Utilisé par la cloche de notification de la barre du haut pour
    prévenir l'admin en temps réel, sans recharger la page.
    """
    r = _remote(request)
    if r.get("role") not in ("super_admin", "admin"):
        return JsonResponse({"count": 0})
    count = StockEntryRequest.objects.filter(statut="en_attente").count()
    return JsonResponse({"count": count})


@login_required(login_url="web:login")
@delete_required
def transaction_delete(request, pk):
    """Suppression douce d'une transaction (dépôt/retrait) → corbeille."""
    tx = get_object_or_404(Transaction, pk=pk, deleted=False)
    if request.method == "POST":
        tx.deleted = True
        tx.save()
        _log_audit(
            request, "transaction_delete", target_type="transaction", target_id=tx.uuid,
            details=f"{tx.type} matricule={tx.matricule} montant={tx.montant:.0f}",
        )
        messages.success(
            request,
            f"{'Dépôt' if tx.type == 'depot' else 'Retrait'} de {tx.montant:,.0f} GNF "
            f"({tx.matricule}) envoyé à la corbeille. Le solde du client est recalculé.",
        )
    return redirect(request.POST.get("next") or "web:transactions")


@login_required(login_url="web:login")
@delete_required
def transaction_restore(request, pk):
    """Restaure une transaction depuis la corbeille."""
    tx = get_object_or_404(Transaction, pk=pk, deleted=True)
    if request.method == "POST":
        tx.deleted = False
        tx.save()
        _log_audit(
            request, "transaction_restore", target_type="transaction", target_id=tx.uuid,
            details=f"{tx.type} matricule={tx.matricule} montant={tx.montant:.0f}",
        )
        messages.success(
            request,
            f"{'Dépôt' if tx.type == 'depot' else 'Retrait'} de {tx.montant:,.0f} GNF "
            f"({tx.matricule}) restauré.",
        )
    return redirect("web:trash")


def _sale_product(sale):
    """Retrouve le produit d'une vente (par uuid d'abord, sinon id serveur)."""
    if sale.product_uuid:
        p = Product.objects.filter(uuid=sale.product_uuid).first()
        if p:
            return p
    return Product.objects.filter(pk=sale.product_id).first()


@login_required(login_url="web:login")
@delete_required
def sale_delete(request, pk):
    """Suppression douce d'une vente → corbeille. Le stock du produit est rendu."""
    sale = get_object_or_404(Sale, pk=pk, deleted=False)
    if request.method == "POST":
        sale.deleted = True
        sale.save()
        # Rend la quantité au stock (mouvement d'annulation, traçable).
        product = _sale_product(sale)
        if product:
            new_stock = float(product.quantite_stock or 0) + float(sale.quantite or 0)
            product.quantite_stock = new_stock
            product.updated_at = _iso_now()
            product.save()
            r = _remote(request)
            StockMovement.objects.create(
                uuid=str(uuid_mod.uuid4()),
                product_id=product.id, product_uuid=product.uuid, product_nom=product.nom,
                type="entree", quantite=float(sale.quantite or 0), stock_apres=new_stock,
                motif=f"Annulation vente N°{sale.id} ({sale.matricule})", sale_id=sale.id,
                agent_id=None, agent_uuid="", agent_nom=r.get("nom_complet") or "",
                created_at=_iso_now(),
            )
        _log_audit(
            request, "sale_delete", target_type="sale", target_id=sale.uuid,
            details=f"{sale.product_nom} x{sale.quantite:g} matricule={sale.matricule} "
                    f"montant={sale.montant_total:.0f}",
        )
        messages.success(
            request,
            f"Vente « {sale.product_nom} » ({sale.matricule}) envoyée à la corbeille. "
            f"Stock rendu et solde recalculé.",
        )
    return redirect(request.POST.get("next") or "web:sales")


@login_required(login_url="web:login")
@delete_required
def sale_restore(request, pk):
    """Restaure une vente depuis la corbeille. Le stock est de nouveau décrémenté."""
    sale = get_object_or_404(Sale, pk=pk, deleted=True)
    if request.method == "POST":
        sale.deleted = False
        sale.save()
        product = _sale_product(sale)
        if product:
            new_stock = float(product.quantite_stock or 0) - float(sale.quantite or 0)
            product.quantite_stock = new_stock
            product.updated_at = _iso_now()
            product.save()
            r = _remote(request)
            StockMovement.objects.create(
                uuid=str(uuid_mod.uuid4()),
                product_id=product.id, product_uuid=product.uuid, product_nom=product.nom,
                type="sortie", quantite=float(sale.quantite or 0), stock_apres=new_stock,
                motif=f"Rétablissement vente N°{sale.id} ({sale.matricule})", sale_id=sale.id,
                agent_id=None, agent_uuid="", agent_nom=r.get("nom_complet") or "",
                created_at=_iso_now(),
            )
        _log_audit(
            request, "sale_restore", target_type="sale", target_id=sale.uuid,
            details=f"{sale.product_nom} x{sale.quantite:g} matricule={sale.matricule}",
        )
        messages.success(request, f"Vente « {sale.product_nom} » ({sale.matricule}) restaurée.")
    return redirect("web:trash")


@login_required(login_url="web:login")
@delete_required
def stock_movement_restore(request, pk):
    movement = get_object_or_404(StockMovement, pk=pk, deleted=True)
    if request.method == "POST":
        movement.deleted = False
        movement.save()
        _log_audit(
            request, "stock_movement_restore",
            target_type="stock_movement", target_id=movement.uuid,
            details=f"{movement.product_nom} {movement.type} {movement.quantite:g}",
        )
        messages.success(request, f"Mouvement de stock « {movement.product_nom} » restauré.")
    return redirect("web:trash")


@login_required(login_url="web:login")
@delete_required
def product_restore(request, pk):
    product = get_object_or_404(Product, pk=pk, actif=False)
    if request.method == "POST":
        product.actif = True
        product.updated_at = _iso_now()
        product.save()
        _log_audit(
            request, "product_restore", target_type="product",
            target_id=product.uuid, details=product.nom,
        )
        messages.success(request, f"Produit « {product.nom} » restauré.")
    return redirect("web:trash")


@login_required(login_url="web:login")
@delete_required
def client_restore(request, pk):
    client = get_object_or_404(Client, pk=pk, actif=False)
    if request.method == "POST":
        client.actif = True
        client.updated_at = _iso_now()
        client.save()
        _log_audit(
            request, "client_restore", target_type="client",
            target_id=client.uuid, details=client.matricule,
        )
        messages.success(request, f"Fiche client « {client.matricule} » restaurée.")
    return redirect("web:trash")


@login_required(login_url="web:login")
@delete_required
def trash_all_active_data(request):
    if request.method == "POST":
        now = _iso_now()
        received_at = timezone.now()
        n_tx = Transaction.objects.filter(deleted=False).update(
            deleted=True, received_at=received_at,
        )
        n_sales = Sale.objects.filter(deleted=False).update(
            deleted=True, received_at=received_at,
        )
        n_moves = StockMovement.objects.filter(deleted=False).update(
            deleted=True, received_at=received_at,
        )
        n_products = Product.objects.filter(actif=True).update(
            actif=False, updated_at=now, received_at=received_at,
        )
        n_clients = Client.objects.filter(actif=True).update(
            actif=False, updated_at=now, received_at=received_at,
        )
        _log_audit(
            request, "trash_all_active_data", target_type="database",
            target_id="active",
            details=(
                f"tx={n_tx}, sales={n_sales}, movements={n_moves}, "
                f"products={n_products}, clients={n_clients}"
            ),
        )
        messages.success(
            request,
            "Base active vidée : les données métier ont été envoyées à la corbeille.",
        )
    return redirect("web:trash")


@login_required(login_url="web:login")
@delete_required
def trash(request):
    """Corbeille : transactions et ventes supprimées, restaurables."""
    deleted_tx = Transaction.objects.filter(deleted=True).order_by("-created_at", "-id")[:100]
    deleted_sales = Sale.objects.filter(deleted=True).order_by("-created_at", "-id")[:100]
    deleted_moves = StockMovement.objects.filter(deleted=True).order_by("-created_at", "-id")[:100]
    deleted_products = Product.objects.filter(actif=False).order_by("nom", "id")[:100]
    deleted_clients = Client.objects.filter(actif=False).order_by("matricule", "id")[:100]
    return render(request, "web/trash.html", {
        "deleted_tx": deleted_tx,
        "deleted_sales": deleted_sales,
        "deleted_moves": deleted_moves,
        "deleted_products": deleted_products,
        "deleted_clients": deleted_clients,
        "n_tx": Transaction.objects.filter(deleted=True).count(),
        "n_sales": Sale.objects.filter(deleted=True).count(),
        "n_moves": StockMovement.objects.filter(deleted=True).count(),
        "n_products": Product.objects.filter(actif=False).count(),
        "n_clients": Client.objects.filter(actif=False).count(),
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
def stock_movements(request):
    """Journal des mouvements de stock (entrées / sorties), lecture seule.

    Trace toutes les variations de stock : réapprovisionnements, ventes,
    retraits de produits, ajustements d'inventaire, pertes/casses.
    """
    qs = StockMovement.objects.filter(deleted=False)
    product = (request.GET.get("product") or "").strip()
    type_ = (request.GET.get("type") or "").strip()
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    agent = (request.GET.get("agent") or "").strip()

    if product:
        qs = qs.filter(product_nom__icontains=product)
    if type_ in ("entree", "sortie"):
        qs = qs.filter(type=type_)
    if date_from:
        qs = qs.filter(created_at__gte=f"{date_from} 00:00:00")
    if date_to:
        qs = qs.filter(created_at__lte=f"{date_to} 23:59:59")
    if agent:
        qs = qs.filter(agent_nom__icontains=agent)

    qs = qs.order_by("-created_at", "-id")

    export = (request.GET.get("export") or "").strip()
    if export in ("xlsx", "pdf"):
        headers = ["Date", "Produit", "Type", "Quantité", "Stock après",
                   "Motif", "Agent"]
        rows = [[
            m.created_at, m.product_nom,
            "Entrée" if m.type == "entree" else "Sortie",
            _fmt_num(m.quantite), _fmt_num(m.stock_apres),
            m.motif or "", m.agent_nom or "",
        ] for m in qs]
        sub = "Mouvements de stock"
        if date_from or date_to:
            sub += f" — du {date_from or '…'} au {date_to or '…'}"
        return _export_response(export, "mouvements_stock", "Mouvements de stock",
                                headers, rows, subtitle=sub)

    total_entrees = qs.filter(type="entree").aggregate(s=Sum("quantite"))["s"] or 0
    total_sorties = qs.filter(type="sortie").aggregate(s=Sum("quantite"))["s"] or 0
    n_total = qs.count()
    page_obj = _paginate(request, qs)

    return render(request, "web/stock_movements.html", {
        "page_obj": page_obj,
        "n_total": n_total,
        "total_entrees": total_entrees,
        "total_sorties": total_sorties,
        "filters": {
            "product": product, "type": type_,
            "date_from": date_from, "date_to": date_to, "agent": agent,
        },
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def inventory(request):
    """Inventaire physique : saisie du stock réel compté par produit.

    Pour chaque produit dont la quantité comptée diffère du stock théorique,
    on crée un mouvement d'ajustement (entrée si surplus, sortie si manque)
    et on aligne le stock du produit sur la valeur comptée.
    """
    products = list(Product.objects.filter(actif=True).order_by("nom"))
    error = None

    if request.method == "POST":
        try:
            motif = (request.POST.get("motif") or "").strip() or "Inventaire physique"

            r = _remote(request)
            agent = None
            ident = r.get("identifiant")
            if ident:
                agent = RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()
            agent_id = agent.id if agent else None
            agent_uuid = agent.uuid if agent else ""
            agent_nom = agent.nom_complet if agent else (r.get("nom_complet") or "")

            adjustments = []
            for p in products:
                raw = request.POST.get(f"count_{p.id}")
                if raw is None or raw.strip() == "":
                    continue  # produit non compté → ignoré
                counted = float(raw.strip().replace(" ", ""))
                if counted < 0:
                    raise ValueError(f"Quantité comptée invalide pour « {p.nom} ».")
                theoretical = float(p.quantite_stock or 0)
                ecart = counted - theoretical
                if ecart == 0:
                    continue  # pas d'écart → rien à faire
                mv_type = "entree" if ecart > 0 else "sortie"
                StockMovement.objects.create(
                    uuid=str(uuid_mod.uuid4()),
                    product_id=p.id, product_uuid=p.uuid, product_nom=p.nom,
                    type=mv_type, quantite=abs(ecart), stock_apres=counted,
                    motif=motif, sale_id=None,
                    agent_id=agent_id, agent_uuid=agent_uuid, agent_nom=agent_nom,
                    created_at=_iso_now(),
                )
                p.quantite_stock = counted
                p.updated_at = _iso_now()
                p.save()
                adjustments.append((p.nom, theoretical, counted, ecart))

            if not adjustments:
                messages.info(request, "Aucun écart : tous les stocks comptés sont conformes.")
            else:
                detail = "; ".join(
                    f"{nom}: {theo:g}→{cnt:g} ({'+' if ec > 0 else ''}{ec:g})"
                    for nom, theo, cnt, ec in adjustments
                )
                _log_audit(
                    request, "inventory_adjust", target_type="stock",
                    target_id="", details=f"motif={motif} | {detail}",
                )
                messages.success(
                    request,
                    f"Inventaire enregistré : {len(adjustments)} produit(s) ajusté(s).",
                )
            return redirect("web:inventory")
        except (ValueError, TypeError) as e:
            error = str(e)

    # Export de la feuille de comptage (stock théorique + colonnes à remplir).
    export = (request.GET.get("export") or "").strip()
    if export in ("xlsx", "pdf"):
        headers = ["Référence", "Produit", "Prix unit.", "Stock théorique",
                   "Stock compté", "Écart", "Valeur"]
        rows = [[
            p.reference or "", p.nom, _fmt_money(p.prix_unitaire),
            _fmt_num(p.quantite_stock), "", "",
            _fmt_money((p.quantite_stock or 0) * (p.prix_unitaire or 0)),
        ] for p in products]
        return _export_response(export, "inventaire", "Feuille d'inventaire",
                                headers, rows, subtitle=f"Au {_iso_now()}")

    # Valorisation courante du stock.
    for p in products:
        p.valeur = (p.quantite_stock or 0) * (p.prix_unitaire or 0)
    total_value = sum(p.valeur for p in products)
    total_units = sum((p.quantite_stock or 0) for p in products)

    return render(request, "web/inventory.html", {
        "products": products,
        "total_value": total_value,
        "total_units": total_units,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
def clients(request):
    qs = Client.objects.filter(actif=True)
    search = (request.GET.get("q") or "").strip()
    if search:
        qs = qs.filter(Q(matricule__icontains=search) | Q(nom__icontains=search))
    qs = qs.order_by("matricule")

    # Solde et nb opérations par matricule (à la volée)
    rows = []
    for c in qs[:500]:  # garde-fou : on calcule au plus 500 soldes par page de recherche
        tx = Transaction.objects.filter(matricule=c.matricule, deleted=False)
        depots = tx.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
        retraits = tx.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0
        ventes = Sale.objects.filter(matricule=c.matricule, deleted=False).aggregate(s=Sum("montant_total"))["s"] or 0
        solde = float(depots) - float(retraits) - float(ventes)
        n_ops = tx.count() + Sale.objects.filter(matricule=c.matricule, deleted=False).count()
        rows.append({"client": c, "solde": solde, "n_ops": n_ops})

    r = _remote(request)
    can_edit = r.get("role") in ("super_admin", "admin")
    return render(request, "web/clients.html", {
        "rows": rows,
        "search": search,
        "remote": r,
        "can_edit": can_edit,
        # Creation ouverte a tous les utilisateurs connectes (agents inclus).
        "can_create": True,
    })


def _client_form_post(request, client=None):
    matricule = (request.POST.get("matricule") or "").strip()
    if not matricule:
        raise ValueError("Le matricule est obligatoire.")
    nom = (request.POST.get("nom") or "").strip()
    telephone = (request.POST.get("telephone") or "").strip()
    note = (request.POST.get("note") or "").strip()
    now = _iso_now()
    if client is None:
        if Client.objects.filter(matricule=matricule).exists():
            raise ValueError(f"Un client avec le matricule « {matricule} » existe déjà.")
        Client.objects.create(
            uuid=str(uuid_mod.uuid4()),
            matricule=matricule, nom=nom, telephone=telephone, note=note,
            actif=True, created_at=now, updated_at=now,
        )
    else:
        # Si le matricule change, vérifier qu'il n'entre pas en conflit.
        if matricule != client.matricule and Client.objects.filter(matricule=matricule).exists():
            raise ValueError(f"Un autre client a déjà le matricule « {matricule} ».")
        client.matricule = matricule
        client.nom = nom
        client.telephone = telephone
        client.note = note
        client.updated_at = now
        client.save()


@login_required(login_url="web:login")
def client_new(request):
    # Ouvert a tous les roles : un agent peut enregistrer un nouveau client
    # (matricule) directement, pour ne pas bloquer une operation. La
    # modification/desactivation d'une fiche reste reservee aux admins.
    error = None
    if request.method == "POST":
        try:
            _client_form_post(request)
            _log_audit(
                request, "client_create", target_type="client",
                target_id=request.POST.get("matricule") or "",
                details=(request.POST.get("nom") or "").strip(),
            )
            messages.success(request, "Fiche client créée.")
            return redirect("web:clients")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/client_form.html", {
        "client": None,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    error = None
    if request.method == "POST":
        try:
            _client_form_post(request, client=client)
            _log_audit(
                request, "client_update", target_type="client",
                target_id=client.matricule, details=client.nom or "",
            )
            messages.success(request, "Fiche client mise à jour.")
            return redirect("web:clients")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/client_form.html", {
        "client": client,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def client_toggle(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == "POST":
        client.actif = not client.actif
        client.updated_at = _iso_now()
        client.save()
        _log_audit(
            request,
            "client_activate" if client.actif else "client_deactivate",
            target_type="client", target_id=client.matricule, details=client.nom or "",
        )
        messages.success(
            request,
            f"Fiche « {client.matricule} » {'activée' if client.actif else 'désactivée'}.",
        )
    return redirect("web:clients")


# ====================================================================
# Gestion des utilisateurs (super_admin uniquement, sauf les caissiers
# qui peuvent être créés par un admin).
# ====================================================================

def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


@login_required(login_url="web:login")
def reports_view(request):
    """Affichage du formulaire + génération du rapport.

    Tous les rôles peuvent générer un rapport (lecture seule).
    """
    r = _remote(request)
    error = None

    # Pré-remplissage par défaut : mois courant en mode mensuel
    today = date.today()
    default_from, default_to = web_reports.month_period()

    if request.method == "POST":
        try:
            dataset = (request.POST.get("dataset") or "transactions").strip()
            kind = (request.POST.get("kind") or "custom").strip()
            fmt = (request.POST.get("format") or "pdf").strip()
            agent = (request.POST.get("agent") or "").strip() or None
            date_from = (request.POST.get("date_from") or default_from).strip()
            date_to = (request.POST.get("date_to") or default_to).strip()

            # Ajuste les dates selon kind si on veut "rapport journalier d'aujourd'hui"
            if kind == "daily":
                date_from, date_to = web_reports.today_period()
            elif kind == "monthly":
                date_from, date_to = web_reports.month_period()
            elif kind == "annual":
                date_from, date_to = web_reports.year_period()

            filename, mime, content = web_reports.generate(
                dataset=dataset, kind=kind,
                date_from=date_from, date_to=date_to,
                agent=agent, fmt=fmt,
            )

            _log_audit(
                request, "report_generate", target_type="report",
                target_id=f"{dataset}/{kind}",
                details=f"format={fmt} from={date_from} to={date_to}",
            )

            resp = HttpResponse(content, content_type=mime)
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            return resp
        except Exception as e:
            error = f"Génération impossible : {e}"

    # Stats rapides comme sur le poste
    tx_today = Transaction.objects.filter(deleted=False).filter(
        created_at__gte=f"{today.strftime('%Y-%m-%d')} 00:00:00",
        created_at__lte=f"{today.strftime('%Y-%m-%d')} 23:59:59",
    )
    today_depots = tx_today.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    today_retraits = tx_today.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0

    mfrom, mto = web_reports.month_period()
    tx_month = Transaction.objects.filter(
        deleted=False, created_at__gte=f"{mfrom} 00:00:00", created_at__lte=f"{mto} 23:59:59",
    )
    month_depots = tx_month.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    month_retraits = tx_month.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0

    yfrom, yto = web_reports.year_period()
    tx_year = Transaction.objects.filter(
        deleted=False, created_at__gte=f"{yfrom} 00:00:00", created_at__lte=f"{yto} 23:59:59",
    )
    year_depots = tx_year.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    year_retraits = tx_year.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0

    return render(request, "web/reports.html", {
        "error": error,
        "remote": r,
        "default_from": default_from,
        "default_to": default_to,
        "stats": {
            "today_depots": today_depots,
            "today_retraits": today_retraits,
            "month_depots": month_depots,
            "month_retraits": month_retraits,
            "year_depots": year_depots,
            "year_retraits": year_retraits,
        },
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def audit_journal(request):
    """Consultation du journal d'audit. Filtrable par utilisateur, action, dates."""
    qs = AuditLog.objects.all()
    user_q = (request.GET.get("user") or "").strip()
    action_q = (request.GET.get("action") or "").strip()
    target_q = (request.GET.get("target") or "").strip()
    source = (request.GET.get("source") or "").strip()  # "web" | "poste" | ""
    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()

    if user_q:
        qs = qs.filter(user_identifiant__icontains=user_q)
    if action_q:
        qs = qs.filter(action__icontains=action_q)
    if target_q:
        qs = qs.filter(Q(target_type__icontains=target_q) | Q(target_id__icontains=target_q))
    if source == "web":
        qs = qs.filter(action__startswith="web.")
    elif source == "poste":
        qs = qs.exclude(action__startswith="web.")
    if date_from:
        qs = qs.filter(created_at__gte=f"{date_from} 00:00:00")
    if date_to:
        qs = qs.filter(created_at__lte=f"{date_to} 23:59:59")

    qs = qs.order_by("-created_at", "-id")
    n_total = qs.count()
    page_obj = _paginate(request, qs)

    return render(request, "web/journal.html", {
        "page_obj": page_obj,
        "n_total": n_total,
        "filters": {
            "user": user_q, "action": action_q, "target": target_q,
            "source": source, "date_from": date_from, "date_to": date_to,
        },
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def devices_list(request):
    """Gestion des postes de synchronisation (jetons Device).

    Permet de créer un jeton pour un poste de caisse ou pour la console
    locale, sans passer par l'admin Django.
    """
    error = None
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "create":
            name = (request.POST.get("name") or "").strip()
            if not name:
                error = "Le nom du poste est obligatoire."
            elif Device.objects.filter(name=name).exists():
                error = f"Un poste nommé « {name} » existe déjà."
            else:
                device = Device.objects.create(name=name)
                _log_audit(request, "device_create", target_type="device",
                           target_id=str(device.id), details=name)
                messages.success(request, f"Poste « {name} » créé. Copiez son jeton ci-dessous.")
                return redirect("web:devices")
        elif action == "toggle":
            device = get_object_or_404(Device, pk=request.POST.get("pk"))
            device.active = not device.active
            device.save()
            _log_audit(
                request,
                "device_activate" if device.active else "device_deactivate",
                target_type="device", target_id=str(device.id), details=device.name,
            )
            messages.success(
                request,
                f"Poste « {device.name} » {'activé' if device.active else 'désactivé'}.",
            )
            return redirect("web:devices")

    devices = Device.objects.all().order_by("name")
    return render(request, "web/devices.html", {
        "devices": devices,
        "error": error,
        "remote": _remote(request),
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def users_list(request):
    qs = RemoteUser.objects.all()
    search = (request.GET.get("q") or "").strip()
    role_filter = (request.GET.get("role") or "").strip()
    if search:
        qs = qs.filter(
            Q(identifiant__icontains=search) | Q(nom_complet__icontains=search) | Q(matricule__icontains=search)
        )
    if role_filter in ROLES:
        qs = qs.filter(role=role_filter)
    qs = qs.order_by("role", "identifiant")
    r = _remote(request)
    # Un admin ne peut gérer que caissier/superviseur.
    return render(request, "web/users.html", {
        "users": qs,
        "search": search,
        "role_filter": role_filter,
        "remote": r,
        "is_super": r.get("role") == "super_admin",
        "role_labels": ROLE_LABELS,
    })


def _allowed_target_roles_for(remote_role: str):
    if remote_role == "super_admin":
        return ROLES  # peut créer/éditer n'importe quel rôle
    if remote_role == "admin":
        return ("superviseur", "caissier")
    return ()


def _user_form_post(request, user=None):
    remote_role = (request.session.get("remote_user") or {}).get("role")
    allowed = _allowed_target_roles_for(remote_role)

    identifiant = (request.POST.get("identifiant") or "").strip()
    nom_complet = (request.POST.get("nom_complet") or "").strip()
    matricule = (request.POST.get("matricule") or "").strip()
    telephone = (request.POST.get("telephone") or "").strip()
    role = (request.POST.get("role") or "").strip()
    password = request.POST.get("password") or ""
    can_delete = request.POST.get("can_delete") == "on"

    if not identifiant or not nom_complet:
        raise ValueError("Identifiant et nom complet sont obligatoires.")
    if role not in allowed:
        raise ValueError(f"Rôle non autorisé pour votre profil : {role}.")

    now = _iso_now()
    if user is None:
        if not password:
            raise ValueError("Le mot de passe est obligatoire à la création.")
        if RemoteUser.objects.filter(identifiant=identifiant).exists():
            raise ValueError(f"L'identifiant « {identifiant} » existe déjà.")
        RemoteUser.objects.create(
            uuid=str(uuid_mod.uuid4()),
            identifiant=identifiant, nom_complet=nom_complet, matricule=matricule,
            telephone=telephone, role=role, actif=True,
            can_delete=can_delete,
            password_hash=_hash_password(password),
            created_at=now, updated_at=now,
        )
    else:
        if user.role not in allowed:
            raise ValueError("Vous n'avez pas le droit de modifier ce compte.")
        # Si l'identifiant change, vérifier l'unicité.
        if identifiant != user.identifiant and RemoteUser.objects.filter(identifiant=identifiant).exists():
            raise ValueError(f"L'identifiant « {identifiant} » est déjà utilisé.")
        user.identifiant = identifiant
        user.nom_complet = nom_complet
        user.matricule = matricule
        user.telephone = telephone
        user.role = role
        user.can_delete = can_delete
        if password:
            user.password_hash = _hash_password(password)
        user.updated_at = now
        user.save()


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def user_new(request):
    error = None
    r = _remote(request)
    allowed = _allowed_target_roles_for(r.get("role"))
    if request.method == "POST":
        try:
            _user_form_post(request)
            _log_audit(
                request, "user_create", target_type="user",
                target_id=request.POST.get("identifiant") or "",
                details=f"role={request.POST.get('role') or ''}",
            )
            messages.success(request, "Utilisateur créé.")
            return redirect("web:users")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/user_form.html", {
        "target_user": None,
        "error": error,
        "remote": r,
        "allowed_roles": [(x, ROLE_LABELS[x]) for x in allowed],
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def user_edit(request, pk):
    target = get_object_or_404(RemoteUser, pk=pk)
    r = _remote(request)
    allowed = _allowed_target_roles_for(r.get("role"))
    if target.role not in allowed:
        return HttpResponseForbidden("Vous ne pouvez pas modifier ce compte.")
    error = None
    if request.method == "POST":
        try:
            _user_form_post(request, user=target)
            _log_audit(
                request, "user_update", target_type="user",
                target_id=target.identifiant, details=f"role={target.role}",
            )
            messages.success(request, "Utilisateur mis à jour.")
            return redirect("web:users")
        except (ValueError, TypeError) as e:
            error = str(e)
    return render(request, "web/user_form.html", {
        "target_user": target,
        "error": error,
        "remote": r,
        "allowed_roles": [(x, ROLE_LABELS[x]) for x in allowed],
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def user_toggle(request, pk):
    target = get_object_or_404(RemoteUser, pk=pk)
    r = _remote(request)
    allowed = _allowed_target_roles_for(r.get("role"))
    if target.role not in allowed:
        return HttpResponseForbidden("Vous ne pouvez pas modifier ce compte.")
    # Garde-fou : on n'autodésactive pas le compte avec lequel on est connecté
    if target.identifiant == r.get("identifiant"):
        messages.warning(request, "Vous ne pouvez pas désactiver votre propre compte.")
        return redirect("web:users")
    if request.method == "POST":
        target.actif = not target.actif
        target.updated_at = _iso_now()
        target.save()
        _log_audit(
            request,
            "user_activate" if target.actif else "user_deactivate",
            target_type="user", target_id=target.identifiant,
        )
        messages.success(
            request,
            f"Compte « {target.identifiant} » {'activé' if target.actif else 'désactivé'}.",
        )
    return redirect("web:users")


@login_required
def quit_app(request):
    """Arrête complètement la console locale (serveur + synchronisation).

    Disponible UNIQUEMENT sur la console locale : console_web.py positionne la
    variable d'environnement EMAB_LOCAL_CONSOLE=1. Sur le serveur en ligne
    (Render), cette vue est interdite — il ne faut surtout pas y arrêter le
    serveur partagé.
    """
    import os

    if os.environ.get("EMAB_LOCAL_CONSOLE") != "1":
        return HttpResponseForbidden("Indisponible sur le serveur en ligne.")
    if request.method != "POST":
        # Page de confirmation (accès direct par URL).
        return render(request, "web/quit.html", {"confirm": True})

    # Arrêt différé : on laisse le temps de renvoyer la page avant de couper
    # le processus (serveur waitress + threads de synchronisation).
    import threading
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return render(request, "web/quit.html", {"confirm": False})


@login_required(login_url="web:login")
def apply_update(request):
    """Applique MAINTENANT une mise à jour déjà téléchargée (console locale).

    Lance le script qui ferme la console, installe la nouvelle version en
    silencieux (données conservées) et relance. Réservé à la console locale.
    """
    import os
    import sys
    from pathlib import Path

    if os.environ.get("EMAB_LOCAL_CONSOLE") != "1":
        return HttpResponseForbidden("Indisponible sur le serveur en ligne.")
    data_dir = os.environ.get("EMAB_DATA_DIR")
    if request.method != "POST" or not data_dir:
        return redirect("web:dashboard")
    try:
        from updater import apply_pending_update
        launched = apply_pending_update(Path(data_dir), sys.executable)
    except Exception:
        launched = False
    if not launched:
        messages.info(request, "Aucune mise à jour prête à installer.")
        return redirect("web:dashboard")
    return render(request, "web/applying_update.html", {})
