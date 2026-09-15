"""Endpoints de synchronisation poste ↔ serveur (push + pull)."""
from __future__ import annotations

from django.http import JsonResponse
from django.db import IntegrityError, models
from django.db.models import Q
from django.core.exceptions import ValidationError
from math import isfinite
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from sync.auth import DeviceTokenAuthentication
from web.operations import operation_transaction
from rest_framework.response import Response

from sync.models import TABLE_MODELS


def root(request):
    return JsonResponse({"service": "gestionnaire-sync", "status": "ok"})


@api_view(["GET"])
@authentication_classes([DeviceTokenAuthentication])
def ping(request):
    """Vérifie l'authentification du poste."""
    device = getattr(request, "auth", None)
    return Response({
        "ok": True,
        "device": getattr(device, "name", None),
        "time": timezone.now().isoformat(),
    })


def _coerce(model, record, allowed):
    """Ne garde que les champs autorisés présents et non nuls.

    Les valeurs None sont ignorées pour laisser jouer les valeurs par défaut des
    champs (les champs texte optionnels ne sont pas nullables côté serveur).
    Les chaînes trop longues sont écrêtées à la taille de la colonne : SQLite
    (postes) ne vérifie pas max_length mais PostgreSQL (serveur) refuse avec
    une erreur 500 — ce qui bloquerait la synchronisation de tout le lot.
    """
    out = {}
    for k in allowed:
        if k not in record:
            continue
        field = model._meta.get_field(k)
        value = record[k]
        if value is None:
            if k in ("stock_initial", "stock_compte"):
                continue
            if field.null:
                out[k] = None
            continue
        if isinstance(value, (dict, list)):
            raise ValueError(f"Valeur invalide pour {k}.")
        if isinstance(field, (models.FloatField, models.IntegerField, models.BooleanField)):
            value = field.to_python(value)
        if isinstance(value, float) and not isfinite(value):
            raise ValueError(f"Nombre non fini pour {k}.")
        if k in ("montant", "quantite") and float(value) <= 0:
            if not ((model.__name__ == "StockEntryRequest" or
                     (model.__name__ == "StockMovement" and record.get("stock_compte") is not None)) and float(value) == 0):
                raise ValueError(f"{k} doit être strictement positif.")
        if k in ("prix_unitaire", "prix_achat", "seuil_alerte", "stock_max", "montant_total", "new_prix_unitaire", "new_seuil_alerte", "stock_initial", "stock_compte") and float(value) < 0:
            raise ValueError(f"{k} ne peut pas être négatif.")
        if field.choices and value not in dict(field.choices):
            raise ValueError(f"Valeur invalide pour {k}.")
        if k == "role" and value not in ("super_admin", "admin", "superviseur", "caissier"):
            raise ValueError("Rôle invalide.")
        if k == "type":
            allowed_types = ("depot", "retrait") if model.__name__ == "Transaction" else ("entree", "sortie")
            if value not in allowed_types:
                raise ValueError("Type d'opération invalide.")
        if isinstance(value, str):
            max_length = getattr(model._meta.get_field(k), "max_length", None)
            if max_length and len(value) > max_length:
                value = value[:max_length]
        out[k] = value
    return out


@api_view(["POST"])
@authentication_classes([DeviceTokenAuthentication])
def push(request):
    """Reçoit un lot d'enregistrements pour une table et les upserte par uuid.

    Corps attendu : {"table": "transactions", "records": [{...}, ...]}.
    """
    device = getattr(request, "auth", None)
    if not isinstance(request.data, dict):
        return Response({"detail": "Le corps doit être un objet JSON."}, status=400)
    table = request.data.get("table")
    records = request.data.get("records")

    if not isinstance(table, str) or table not in TABLE_MODELS:
        return Response(
            {"detail": f"Table inconnue : {table}"}, status=status.HTTP_400_BAD_REQUEST
        )
    if not isinstance(records, list):
        return Response(
            {"detail": "'records' doit être une liste."}, status=status.HTTP_400_BAD_REQUEST
        )

    model, allowed = TABLE_MODELS[table]
    created = 0
    updated = 0
    skipped = 0

    if len(records) > MAX_PULL_LIMIT:
        return Response({"detail": "Lot trop volumineux (maximum 1000 lignes)."}, status=400)
    try:
        with operation_transaction():
            for record in records:
                if not isinstance(record, dict):
                    raise ValueError("Chaque enregistrement doit être un objet.")
                uuid = record.get("uuid")
                if not uuid:
                    skipped += 1
                    continue
                if not isinstance(uuid, str) or len(uuid) > 36:
                    raise ValueError("UUID invalide.")
                defaults = _coerce(model, record, allowed)
                defaults["device"] = device
                _, was_created = model.objects.update_or_create(uuid=uuid, defaults=defaults)
                if was_created:
                    created += 1
                else:
                    updated += 1
    except (ValueError, TypeError, OverflowError, ValidationError, IntegrityError) as exc:
        return Response({"detail": f"Lot rejeté : {exc}"}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {"table": table, "created": created, "updated": updated, "skipped": skipped},
        status=status.HTTP_200_OK,
    )


DEFAULT_PULL_LIMIT = 200
MAX_PULL_LIMIT = 1000


@api_view(["GET"])
@authentication_classes([DeviceTokenAuthentication])
def pull(request):
    """Retourne les enregistrements d'une table modifiés depuis un filigrane.

    Paramètres : `table`, `since` (ISO datetime, optionnel), `limit` (≤ 1000).
    Réponse : `{table, records, next_since, has_more}`.

    Le filigrane utilisé est `received_at` (auto-mis à jour à chaque save côté
    serveur). Les postes le stockent et le rejouent au prochain appel.
    """
    table = request.GET.get("table")
    if not isinstance(table, str) or table not in TABLE_MODELS:
        return Response(
            {"detail": f"Table inconnue : {table}"}, status=status.HTTP_400_BAD_REQUEST
        )
    model, allowed = TABLE_MODELS[table]

    try:
        limit = min(int(request.GET.get("limit") or DEFAULT_PULL_LIMIT), MAX_PULL_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_PULL_LIMIT
    if limit <= 0:
        limit = DEFAULT_PULL_LIMIT

    since_raw = request.GET.get("since") or ""
    try:
        since = parse_datetime(since_raw) if since_raw else None
    except ValueError:
        since = None
    if since_raw and since is None:
        return Response({"detail": "Horodatage de synchronisation invalide."}, status=400)
    after_uuid = request.GET.get("since_uuid") or ""

    qs = model.objects.all()
    if since is not None:
        if after_uuid:
            qs = qs.filter(Q(received_at__gt=since) | Q(received_at=since, uuid__gt=after_uuid))
        else:
            qs = qs.filter(received_at__gt=since)
    qs = qs.order_by("received_at", "uuid")[: limit + 1]
    rows = list(qs)
    has_more = len(rows) > limit
    rows = rows[:limit]

    records = []
    for r in rows:
        rec = {"uuid": r.uuid, "received_at": r.received_at.isoformat()}
        for field in allowed:
            rec[field] = getattr(r, field, None)
        records.append(rec)

    next_since = records[-1]["received_at"] if records else (since.isoformat() if since else "")

    return Response({
        "table": table,
        "records": records,
        "next_since": next_since,
        "next_uuid": records[-1]["uuid"] if records else after_uuid,
        "has_more": has_more,
    })
