"""Endpoints de synchronisation poste ↔ serveur (push + pull)."""
from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from sync.models import TABLE_MODELS


def root(request):
    return JsonResponse({"service": "gestionnaire-sync", "status": "ok"})


@api_view(["GET"])
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
    """
    return {k: record[k] for k in allowed if k in record and record[k] is not None}


@api_view(["POST"])
def push(request):
    """Reçoit un lot d'enregistrements pour une table et les upserte par uuid.

    Corps attendu : {"table": "transactions", "records": [{...}, ...]}.
    """
    device = getattr(request, "auth", None)
    table = request.data.get("table")
    records = request.data.get("records")

    if table not in TABLE_MODELS:
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

    for record in records:
        uuid = record.get("uuid")
        if not uuid:
            skipped += 1
            continue
        defaults = _coerce(model, record, allowed)
        defaults["device"] = device
        # received_at est auto_now=True : pas besoin de le fixer ici.
        _, was_created = model.objects.update_or_create(uuid=uuid, defaults=defaults)
        if was_created:
            created += 1
        else:
            updated += 1

    return Response(
        {"table": table, "created": created, "updated": updated, "skipped": skipped},
        status=status.HTTP_200_OK,
    )


DEFAULT_PULL_LIMIT = 200
MAX_PULL_LIMIT = 1000


@api_view(["GET"])
def pull(request):
    """Retourne les enregistrements d'une table modifiés depuis un filigrane.

    Paramètres : `table`, `since` (ISO datetime, optionnel), `limit` (≤ 1000).
    Réponse : `{table, records, next_since, has_more}`.

    Le filigrane utilisé est `received_at` (auto-mis à jour à chaque save côté
    serveur). Les postes le stockent et le rejouent au prochain appel.
    """
    table = request.GET.get("table")
    if table not in TABLE_MODELS:
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
    since = parse_datetime(since_raw) if since_raw else None

    qs = model.objects.all()
    if since is not None:
        qs = qs.filter(received_at__gt=since)
    qs = qs.order_by("received_at", "id")[: limit + 1]
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
        "has_more": has_more,
    })
