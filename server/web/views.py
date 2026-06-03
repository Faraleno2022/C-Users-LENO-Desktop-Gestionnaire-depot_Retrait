"""Vues de la console web : consultation + édition catalogue/clients/comptes."""
from __future__ import annotations

import uuid as uuid_mod
from datetime import date, datetime, time, timedelta
from functools import wraps

import bcrypt
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from sync.models import AuditLog, Client, Product, RemoteUser, Sale, StockMovement, Transaction
from web import reports as web_reports


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


def _iso_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


@login_required(login_url="web:login")
def dashboard(request):
    # Solde global = sum(depots) - sum(retraits) sur les transactions non supprimées.
    tx = Transaction.objects.filter(deleted=False)
    depots = tx.filter(type="depot").aggregate(s=Sum("montant"))["s"] or 0
    retraits = tx.filter(type="retrait").aggregate(s=Sum("montant"))["s"] or 0
    solde = float(depots) - float(retraits)

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

    # Stock
    products = Product.objects.filter(actif=True)
    n_products = products.count()
    stock_value = sum((p.quantite_stock or 0) * (p.prix_unitaire or 0) for p in products)
    low_stock = [p for p in products if (p.quantite_stock or 0) <= (p.seuil_alerte or 0)]

    # Clients
    n_clients = Client.objects.filter(actif=True).count()

    # Dernières opérations
    recent_tx = tx.order_by("-created_at")[:10]

    ctx = {
        "solde": solde,
        "depots_today": depots_today,
        "retraits_today": retraits_today,
        "n_today": n_today,
        "depots_month": depots_month,
        "retraits_month": retraits_month,
        "sales_today_total": s_today,
        "sales_today_count": n_sales_today,
        "sales_month_total": s_month,
        "n_products": n_products,
        "stock_value": stock_value,
        "n_low_stock": len(low_stock),
        "n_clients": n_clients,
        "recent_tx": recent_tx,
        "remote": _remote(request),
    }
    return render(request, "web/dashboard.html", ctx)


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

    last_receipt = request.session.pop("last_deposit", None)
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
    last_receipt = request.session.pop("last_withdrawal", None)

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
            montant_raw = (request.POST.get("montant") or "").strip().replace(" ", "")
            montant = float(montant_raw)
            if montant <= 0:
                raise ValueError("Le montant doit être strictement positif.")
            confirmed = request.POST.get("confirmed") == "1"
            if not confirmed:
                raise ValueError(
                    "Vous devez confirmer avoir vérifié le solde réel avec le poste "
                    "avant de valider un retrait en ligne."
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

            tx = Transaction.objects.create(
                uuid=str(uuid_mod.uuid4()),
                matricule=matricule,
                telephone=telephone,
                type="retrait",
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
                request, "retrait_create", target_type="transaction", target_id=tx.uuid,
                details=f"matricule={matricule} montant={montant:.0f} solde_apres={new_balance:.0f}",
            )
            messages.success(
                request,
                f"Retrait de {montant:,.0f} GNF enregistré pour {matricule}. "
                f"Nouveau solde : {new_balance:,.0f} GNF.",
            )
            request.session["last_withdrawal"] = {
                "id": tx.id,
                "matricule": matricule,
                "telephone": telephone,
                "montant": montant,
                "solde_apres": new_balance,
                "created_at": tx.created_at,
                "agent_nom": tx.agent_nom,
            }
            return redirect("web:withdrawal_new")
        except (ValueError, TypeError) as e:
            error = str(e)

    return render(request, "web/withdrawal_form.html", {
        "error": error,
        "remote": r,
        "last_receipt": last_receipt,
        "balance_preview": balance_preview,
        "matricule_preview": matricule_preview,
    })


@login_required(login_url="web:login")
def sale_new(request):
    """Vente produit en ligne — décrémente stock + débit solde du matricule.

    Risque double : (a) le poste peut avoir débité le matricule offline, (b)
    le poste peut avoir vendu le même produit offline (stock divergent).
    Avertissement explicite + double confirmation.
    """
    r = _remote(request)
    error = None
    last_receipt = request.session.pop("last_sale", None)
    products = Product.objects.filter(actif=True).order_by("nom")

    if request.method == "POST":
        try:
            product_id = int(request.POST.get("product_id") or 0)
            product = Product.objects.filter(pk=product_id, actif=True).first()
            if product is None:
                raise ValueError("Produit invalide ou inactif.")
            matricule = (request.POST.get("matricule") or "").strip()
            if not matricule:
                raise ValueError("Le matricule client est obligatoire.")
            telephone = (request.POST.get("telephone") or "").strip()
            note = (request.POST.get("note") or "").strip()
            qte_raw = (request.POST.get("quantite") or "").strip()
            quantite = float(qte_raw)
            if quantite <= 0:
                raise ValueError("La quantité doit être strictement positive.")
            confirmed = request.POST.get("confirmed") == "1"
            if not confirmed:
                raise ValueError(
                    "Vous devez confirmer avoir vérifié solde et stock avec le poste."
                )

            current_stock = float(product.quantite_stock or 0)
            if quantite > current_stock:
                raise ValueError(
                    f"Stock insuffisant côté serveur : disponible {current_stock:g}, "
                    f"vente demandée {quantite:g}."
                )
            prix = float(product.prix_unitaire or 0)
            montant_total = prix * quantite

            current_balance = _matricule_balance(matricule)
            if montant_total > current_balance:
                raise ValueError(
                    f"Solde insuffisant côté serveur : disponible "
                    f"{current_balance:,.0f} GNF, vente {montant_total:,.0f} GNF."
                )
            new_balance = current_balance - montant_total
            new_stock = current_stock - quantite

            agent = None
            ident = r.get("identifiant")
            if ident:
                agent = RemoteUser.objects.filter(identifiant=ident).order_by("-id").first()

            sale = Sale.objects.create(
                uuid=str(uuid_mod.uuid4()),
                matricule=matricule, telephone=telephone,
                product_id=product.id, product_uuid=product.uuid, product_nom=product.nom,
                quantite=quantite, prix_unitaire=prix, montant_total=montant_total,
                solde_apres=new_balance,
                agent_id=(agent.id if agent else None),
                agent_uuid=(agent.uuid if agent else ""),
                agent_nom=(agent.nom_complet if agent else r.get("nom_complet") or ""),
                note=note, created_at=_iso_now(), deleted=False,
            )
            # Met à jour le stock et crée le mouvement
            product.quantite_stock = new_stock
            product.updated_at = _iso_now()
            product.save()
            StockMovement.objects.create(
                uuid=str(uuid_mod.uuid4()),
                product_id=product.id, product_uuid=product.uuid, product_nom=product.nom,
                type="sortie", quantite=quantite, stock_apres=new_stock,
                motif="Vente en ligne", sale_id=sale.id,
                agent_id=(agent.id if agent else None),
                agent_uuid=(agent.uuid if agent else ""),
                agent_nom=(agent.nom_complet if agent else r.get("nom_complet") or ""),
                created_at=_iso_now(),
            )
            _log_audit(
                request, "sale_create", target_type="sale", target_id=sale.uuid,
                details=f"{product.nom} x{quantite:g} = {montant_total:.0f} pour {matricule}",
            )
            messages.success(
                request,
                f"Vente enregistrée : {product.nom} x {quantite:g} = {montant_total:,.0f} GNF. "
                f"Stock restant : {new_stock:g}. Nouveau solde du client : {new_balance:,.0f} GNF.",
            )
            request.session["last_sale"] = {
                "id": sale.id, "matricule": matricule, "product_nom": product.nom,
                "quantite": quantite, "prix": prix, "montant_total": montant_total,
                "solde_apres": new_balance, "new_stock": new_stock,
                "created_at": sale.created_at, "agent_nom": sale.agent_nom,
            }
            return redirect("web:sale_new")
        except (ValueError, TypeError) as e:
            error = str(e)

    return render(request, "web/sale_form.html", {
        "error": error,
        "remote": r,
        "products": products,
        "last_receipt": last_receipt,
    })


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
    })


@login_required(login_url="web:login")
@role_required("super_admin", "admin")
def product_new(request):
    error = None
    if request.method == "POST":
        try:
            nom = (request.POST.get("nom") or "").strip()
            if not nom:
                raise ValueError("Le nom est obligatoire.")
            reference = (request.POST.get("reference") or "").strip()
            description = (request.POST.get("description") or "").strip()
            prix = float(request.POST.get("prix_unitaire") or 0)
            if prix < 0:
                raise ValueError("Le prix doit être positif ou nul.")
            seuil = float(request.POST.get("seuil_alerte") or 0)
            qte = float(request.POST.get("quantite_stock") or 0)
            now = _iso_now()
            p = Product.objects.create(
                uuid=str(uuid_mod.uuid4()),
                reference=reference,
                nom=nom,
                description=description,
                prix_unitaire=prix,
                quantite_stock=qte,
                seuil_alerte=seuil,
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
            actif = request.POST.get("actif") == "on"
            product.nom = nom
            product.reference = (request.POST.get("reference") or "").strip()
            product.description = (request.POST.get("description") or "").strip()
            product.prix_unitaire = prix
            product.seuil_alerte = seuil
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
            motif = (request.POST.get("motif") or "").strip()

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
@role_required("super_admin", "admin")
def client_new(request):
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
