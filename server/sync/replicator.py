"""Réplication console locale ↔ serveur distant (Render).

La console web locale agit comme un client du serveur en ligne, avec le même
protocole que les postes (push/pull par uuid + jeton Device) :

  - PUSH : tout enregistrement local dont `received_at` a avancé depuis le
    dernier envoi est poussé vers le serveur distant (upsert idempotent).
  - PULL : les enregistrements modifiés côté distant sont fusionnés en local ;
    si la ligne locale est strictement identique, on ne sauvegarde pas
    (sinon `received_at` avancerait et l'enregistrement repartirait en push :
    boucle d'écho).

Politique de conflit : dernière écriture gagnante (les deux côtés sont des
miroirs ; les postes restent la source des opérations financières).

L'état (filigranes par table) est conservé dans un fichier JSON du dossier
de données pour survivre aux redémarrages.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Tuple

import requests

from django.db.models import Q
from django.utils.dateparse import parse_datetime
from web.operations import operation_transaction
from sync.models import TABLE_MODELS

# Ordre de réplication : les tables référencées (users, products) d'abord.
TABLE_ORDER = [
    "users", "products", "clients", "stock_movements",
    "transactions", "sales", "audit_logs", "stock_entry_requests",
]

BATCH = 200
TIMEOUT = 30


class ReplicationError(Exception):
    pass


class Replicator:
    def __init__(self, base_url: str, token: str, state_path: Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.state_path = Path(state_path)
        self.state: Dict[str, str] = self._load_state()
        if self.state.get("server_url", self.base_url) != self.base_url:
            self.state = {}
        self.state["server_url"] = self.base_url

    # -- État (filigranes) ----------------------------------------------------

    def _load_state(self) -> Dict[str, str]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            ) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                    dir=self.state_path.parent, prefix=self.state_path.name, delete=False) as out:
                temporary = Path(out.name)
                json.dump(self.state, out, indent=2)
                out.flush()
                os.fsync(out.fileno())
            temporary.replace(self.state_path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    @staticmethod
    def _after(since: str, after_uuid: str):
        return Q(received_at__gt=since) | Q(received_at=since, uuid__gt=after_uuid)

    # -- HTTP -----------------------------------------------------------------

    def _headers(self) -> dict:
        return {"Authorization": f"Device {self.token}"}

    def ping(self) -> bool:
        r = requests.get(
            f"{self.base_url}/api/sync/ping/", headers=self._headers(), timeout=TIMEOUT
        )
        if r.status_code == 401:
            raise ReplicationError("Jeton refusé par le serveur distant (401).")
        return r.status_code == 200

    # -- PUSH local -> distant ------------------------------------------------

    def _push_table(self, table: str) -> int:
        model, fields = TABLE_MODELS[table]
        since = self.state.get(f"push_{table}") or ""
        qs = model.objects.all()
        if since:
            qs = qs.filter(self._after(since, self.state.get(f"push_{table}_uuid", "")))
        qs = qs.order_by("received_at", "uuid")

        sent = 0
        while True:
            rows = list(qs[:BATCH])
            if not rows:
                break
            records = []
            for r in rows:
                rec = {"uuid": r.uuid}
                for f in fields:
                    rec[f] = getattr(r, f, None)
                records.append(rec)
            resp = requests.post(
                f"{self.base_url}/api/sync/push/",
                json={"table": table, "records": records},
                headers=self._headers(), timeout=TIMEOUT,
            )
            if resp.status_code == 401:
                raise ReplicationError("Jeton refusé par le serveur distant (401).")
            if resp.status_code not in (200, 201):
                raise ReplicationError(
                    f"Push {table} rejeté ({resp.status_code}) : {resp.text[:160]}"
                )
            body = resp.json()
            if not isinstance(body, dict) or body.get("skipped", 0):
                raise ReplicationError(f"Push {table} incomplet : lot non acquitté.")
            sent += len(rows)
            # Avance le filigrane après chaque lot accepté.
            self.state[f"push_{table}"] = rows[-1].received_at.isoformat()
            self.state[f"push_{table}_uuid"] = rows[-1].uuid
            self._save_state()
            qs = model.objects.filter(
                self._after(self.state[f"push_{table}"], self.state[f"push_{table}_uuid"])
            ).order_by("received_at", "uuid")
        return sent

    # -- PULL distant -> local ------------------------------------------------

    @staticmethod
    def _identical(obj, values: dict) -> bool:
        for k, v in values.items():
            local = getattr(obj, k, None)
            if isinstance(local, float) or isinstance(v, float):
                try:
                    if float(local or 0) != float(v or 0):
                        return False
                    continue
                except (TypeError, ValueError):
                    return False
            if local != v:
                return False
        return True

    def _pull_table(self, table: str) -> Tuple[int, int]:
        model, fields = TABLE_MODELS[table]
        since = self.state.get(f"pull_{table}") or ""
        after_uuid = self.state.get(f"pull_{table}_uuid", "")
        inserted = updated = 0
        while True:
            resp = requests.get(
                f"{self.base_url}/api/sync/pull/",
                params={"table": table, "since": since, "since_uuid": after_uuid, "limit": BATCH},
                headers=self._headers(), timeout=TIMEOUT,
            )
            if resp.status_code == 401:
                raise ReplicationError("Jeton refusé par le serveur distant (401).")
            if resp.status_code != 200:
                raise ReplicationError(
                    f"Pull {table} rejeté ({resp.status_code}) : {resp.text[:160]}"
                )
            body = resp.json()
            if not isinstance(body, dict) or not isinstance(body.get("records"), list):
                raise ReplicationError(f"Pull {table} : réponse invalide.")
            records = body["records"]
            from sync.views import _coerce
            blocked = False
            with operation_transaction():
                for rec in records:
                    if not isinstance(rec, dict) or not isinstance(rec.get("uuid"), str) or not rec["uuid"]:
                        raise ReplicationError(f"Pull {table} : enregistrement invalide.")
                    uuid = rec["uuid"]
                    values = _coerce(model, rec, fields)
                    obj = model.objects.filter(uuid=uuid).first()
                    if obj is None:
                        model.objects.create(uuid=uuid, **values)
                        inserted += 1
                    elif not self._identical(obj, values):
                        # Une saisie faite pendant l'appel réseau doit d'abord être poussée.
                        pushed = parse_datetime(self.state.get(f"push_{table}", ""))
                        pushed_uuid = self.state.get(f"push_{table}_uuid", "")
                        if pushed is None or (obj.received_at, obj.uuid) > (pushed, pushed_uuid):
                            blocked = True
                            continue
                        for k, v in values.items():
                            setattr(obj, k, v)
                        obj.save()
                        updated += 1
            if blocked:
                break  # Rejouer la page après le prochain push.
            next_since = body.get("next_since") or since
            next_uuid = body.get("next_uuid") or ""
            if body.get("has_more") and (next_since, next_uuid) == (since, after_uuid):
                raise ReplicationError(f"Pull {table} : pagination bloquée.")
            since, after_uuid = next_since, next_uuid
            if since:
                self.state[f"pull_{table}"] = since
                self.state[f"pull_{table}_uuid"] = after_uuid
                self._save_state()
            if not body.get("has_more") or not records:
                break
        return inserted, updated

    # -- Cycle complet ----------------------------------------------------------

    def run_once(self) -> dict:
        """Push puis pull sur toutes les tables. Retourne un résumé."""
        summary: Dict[str, dict] = {}
        # Envoyer tous les mouvements avant de recevoir les stocks calculés.
        for table in TABLE_ORDER:
            pushed = self._push_table(table)
            summary[table] = {"pushed": pushed, "inserted": 0, "updated": 0}
        for table in TABLE_ORDER:
            ins, upd = self._pull_table(table)
            summary[table].update(inserted=ins, updated=upd)
        return {table: counts for table, counts in summary.items() if any(counts.values())}
