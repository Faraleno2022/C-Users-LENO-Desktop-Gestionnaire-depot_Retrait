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
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from sync.models import TABLE_MODELS

# Ordre de réplication : les tables référencées (users, products) d'abord.
TABLE_ORDER = [
    "users", "products", "clients", "stock_movements",
    "transactions", "sales", "audit_logs",
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

    # -- État (filigranes) ----------------------------------------------------

    def _load_state(self) -> Dict[str, str]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        self.state_path.write_text(
            json.dumps(self.state, indent=2), encoding="utf-8"
        )

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
            qs = qs.filter(received_at__gt=since)
        qs = qs.order_by("received_at", "id")

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
            sent += len(rows)
            # Avance le filigrane après chaque lot accepté.
            self.state[f"push_{table}"] = rows[-1].received_at.isoformat()
            self._save_state()
            qs = model.objects.filter(
                received_at__gt=self.state[f"push_{table}"]
            ).order_by("received_at", "id")
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
        inserted = updated = 0
        while True:
            resp = requests.get(
                f"{self.base_url}/api/sync/pull/",
                params={"table": table, "since": since, "limit": BATCH},
                headers=self._headers(), timeout=TIMEOUT,
            )
            if resp.status_code == 401:
                raise ReplicationError("Jeton refusé par le serveur distant (401).")
            if resp.status_code != 200:
                raise ReplicationError(
                    f"Pull {table} rejeté ({resp.status_code}) : {resp.text[:160]}"
                )
            body = resp.json()
            records = body.get("records") or []
            for rec in records:
                uuid = rec.get("uuid")
                if not uuid:
                    continue
                values = {f: rec.get(f) for f in fields if f in rec and rec.get(f) is not None}
                obj = model.objects.filter(uuid=uuid).first()
                if obj is None:
                    model.objects.create(uuid=uuid, **values)
                    inserted += 1
                elif not self._identical(obj, values):
                    # Sauvegarde uniquement si différent : évite de faire
                    # avancer received_at et de créer une boucle d'écho.
                    for k, v in values.items():
                        setattr(obj, k, v)
                    obj.save()
                    updated += 1
            since = body.get("next_since") or since
            if since:
                self.state[f"pull_{table}"] = since
                self._save_state()
            if not body.get("has_more") or not records:
                break
        return inserted, updated

    # -- Cycle complet ----------------------------------------------------------

    def run_once(self) -> dict:
        """Push puis pull sur toutes les tables. Retourne un résumé."""
        summary: Dict[str, dict] = {}
        for table in TABLE_ORDER:
            pushed = self._push_table(table)
            ins, upd = self._pull_table(table)
            if pushed or ins or upd:
                summary[table] = {"pushed": pushed, "inserted": ins, "updated": upd}
        return summary
