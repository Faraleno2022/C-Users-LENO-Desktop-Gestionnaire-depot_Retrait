"""Recalcul déterministe, sans accès à la base : le journal fait foi.

Les montants saisis et les quantités vendues ne sont jamais inventés.
Un plan contient les valeurs avant/après et les cas impossibles à déduire.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from itertools import groupby, takewhile
import math
import heapq
import hashlib
import json

REPAIR_VERSION = "stock-ledger-v1"


def decimal(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or not math.isfinite(float(result)):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ValueError("Nombre absent ou non fini.") from None


def stamp(row):
    value = str(row.get("created_at") or "").replace("T", " ")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.isoformat(" ", timespec="microseconds")


def _issue(plan, table, row, reason):
    plan["issues"].append({"table": table, "uuid": row.get("uuid"),
                           "label": row.get("nom") or row.get("product_nom") or row.get("matricule"),
                           "reason": reason})


def _change(plan, table, row, **values):
    changes = {key: value for key, value in values.items() if row.get(key) != value}
    if changes:
        plan["changes"].append({"table": table, "uuid": row["uuid"],
            "before": {key: safe_value(row.get(key)) for key in changes}, "after": changes})


def _delta(row):
    q = decimal(row["quantite"])
    if q < 0 or (q == 0 and row.get("stock_compte") is None):
        raise ValueError("Quantité invalide.")
    if row["type"] not in ("entree", "sortie"):
        raise ValueError("Type de mouvement invalide.")
    return q if row["type"] == "entree" else -q


def _ordered_moves(rows, stamp_key=stamp):
    """Même ordre des soldes, sans reparcourir tout un groupe à chaque retrait."""
    result = []
    dated = sorted(((stamp_key(m), str(m['uuid']), m) for m in rows), key=lambda item: item[:2])
    for _, group in groupby(dated, key=lambda item: item[0]):
        moves = [item[2] for item in group]
        if len(moves) == 1:
            result.extend(moves)
            continue
        after = [decimal(m['stock_apres']) for m in moves]
        before = [value - _delta(m) for value, m in zip(after, moves)]
        counts = Counter(after)
        waiting = defaultdict(list)
        priorities = []
        roots = []
        active = set(range(len(moves)))
        for i, m in enumerate(moves):
            waiting[before[i]].append(i)
            key = (not (m.get('is_initial') or m.get('motif') == 'Stock initial'), str(m['uuid']), i)
            priorities.append(key)
            if before[i] not in counts:
                roots.append(key)
        all_moves = list(priorities)
        heapq.heapify(all_moves)
        heapq.heapify(roots)
        while active:
            while roots and roots[0][2] not in active:
                heapq.heappop(roots)
            while all_moves and all_moves[0][2] not in active:
                heapq.heappop(all_moves)
            _, _, i = heapq.heappop(roots if roots else all_moves)
            active.remove(i)
            result.append(moves[i])
            counts[after[i]] -= 1
            if not counts[after[i]]:
                del counts[after[i]]
                for unlocked in waiting[after[i]]:
                    if unlocked in active:
                        heapq.heappush(roots, priorities[unlocked])
    return result


def build_plan(products, movements, transactions, sales, audit_logs=()):
    dates = {}
    def dated(row):
        key = str(row.get('created_at') or '')
        if key not in dates:
            dates[key] = stamp(row)
        return dates[key]

    plan = {"version": REPAIR_VERSION, "changes": [], "issues": [], "stocks": [], "balances": []}
    products = [p if isinstance(p, dict) else dict(p) for p in products]
    movements = [dict(m) for m in movements]
    sales = [s if isinstance(s, dict) else dict(s) for s in sales]
    transactions = [t if isinstance(t, dict) else dict(t) for t in transactions]
    by_uuid = {p["uuid"]: p for p in products}
    by_id = {p["id"]: p for p in products}
    grouped = defaultdict(list)
    sales_by_product = defaultdict(list)
    for sale in sales:
        product = by_uuid.get(sale.get('product_uuid')) if sale.get('product_uuid') else by_id.get(sale.get('product_id'))
        if product is not None:
            sales_by_product[product['uuid']].append(sale)
    invalid_products = set()
    for m in movements:
        p = by_uuid.get(m.get("product_uuid")) if m.get("product_uuid") else by_id.get(m.get("product_id"))
        if p is None:
            _issue(plan, "stock_movements", m, "Produit absent ; synchronisation complète nécessaire.")
            continue
        try:
            dated(m)
            _delta(m)
            decimal(m["stock_apres"])
        except (ValueError, KeyError):
            invalid_products.add(p["uuid"])
            _issue(plan, "stock_movements", m, "Date, quantité ou stock après invalide.")
        grouped[p["uuid"]].append(m)

    # Les anciens écrans d'inventaire enregistraient le comptage dans
    # stock_apres et le libellé standard "Inventaire physique". Ce comptage
    # reste la référence ; seule la quantité d'ajustement est recalculée.
    # Un libellé personnalisé exige en plus une trace d'audit correspondante.
    for movement in movements:
        if movement.get("stock_compte") is None and movement.get("motif") == "Inventaire physique":
            try:
                counted = decimal(movement["stock_apres"])
                if counted >= 0:
                    movement["_legacy_count"] = float(counted)
            except ValueError:
                pass
    movements_by_time = defaultdict(list)
    for movement in movements:
        if movement.get('stock_compte') is None:
            movements_by_time[movement.get('created_at')].append(movement)
    for log in audit_logs:
        if log.get("action") != "inventory_adjust":
            continue
        details = str(log.get("details") or "")
        for m in movements_by_time.get(log.get("created_at"), ()):
            marker = str(m.get("product_nom")) + ": "
            if marker in details:
                segment = details.split(marker, 1)[1].split(";", 1)[0]
                try:
                    counted = decimal(segment.split("→", 1)[1].split(" ", 1)[0])
                    if counted == decimal(m["stock_apres"]) and counted >= 0:
                        m["_legacy_count"] = float(counted)
                except (IndexError, ValueError):
                    pass

    for p in products:
        if p["uuid"] in invalid_products:
            continue
        if p.get("suivi_stock") is not None and not p["suivi_stock"]:
            # Article vendu sans suivi de stock : il n'a ni stock initial ni
            # mouvement, donc rien à recalculer et aucun écart à signaler.
            continue
        rows = grouped[p["uuid"]]
        try:
            for movement in rows:
                label = str(movement.get("motif") or "").lower()
                if ("inventaire" in label or "comptage" in label) and movement.get("stock_compte") is None and movement.get("_legacy_count") is None:
                    raise ValueError("Inventaire ancien sans comptage identifiable : vérifier le justificatif.")
            rows = _ordered_moves(rows, stamp_key=dated)
            initial_rows = [m for m in rows if m.get("is_initial") or
                            (m.get("motif") == "Stock initial" and m["type"] == "entree" and
                             dated(m) == dated(rows[0]))]
            if len(initial_rows) > 1:
                raise ValueError("Plusieurs stocks initiaux : inventaire nécessaire.")
            source = p.get("stock_initial_source") or ""
            initial = p.get("stock_initial")
            if initial_rows:
                initial = decimal(initial_rows[0]["quantite"])
                source = source if source in ("creation", "mouvement_initial") else "mouvement_initial"
            elif initial is not None and source != "solde_premier_mouvement":
                initial = decimal(initial)
            elif rows:
                first_time = dated(rows[0])
                first = list(takewhile(lambda m: dated(m) == first_time, rows))
                afters = {decimal(m["stock_apres"]) for m in first}
                roots = {decimal(m["stock_apres"]) - _delta(m) for m in first
                         if decimal(m["stock_apres"]) - _delta(m) not in afters}
                if len(roots) != 1:
                    raise ValueError("Stock initial indéterminé ; inventaire nécessaire.")
                initial = roots.pop()
                source = "solde_premier_mouvement"
            elif not sales_by_product[p['uuid']]:
                initial = decimal(p["quantite_stock"])
                source = "stock_sans_mouvement"
            else:
                raise ValueError("Ventes présentes sans mouvements : historique incomplet.")
            if initial < 0:
                raise ValueError("Stock initial négatif : inventaire nécessaire.")
            # Une sortie absente peut signaler une synchronisation partielle.
            product_sales = sales_by_product[p['uuid']]
            sale_quantities = sum((decimal(sale["quantite"]) for sale in product_sales), Decimal(0))
            sale_outputs = sum((decimal(m["quantite"]) for m in rows if m["type"] == "sortie"
                                and (m.get("sale_id") is not None or str(m.get("motif") or "").startswith("Vente"))
                                and not str(m.get("motif") or "").startswith("Rétablissement")), Decimal(0))
            if sale_quantities != sale_outputs:
                raise ValueError("Les ventes et leurs sorties ne concordent pas : historique à compléter.")
            running = initial
            entries = exits = Decimal(0)
            staged = []
            initial_ids = {m["uuid"] for m in initial_rows}
            negative = False
            for m in rows:
                values = {}
                is_initial = m["uuid"] in initial_ids
                if is_initial:
                    values["is_initial"] = True
                else:
                    counted = m.get("stock_compte", None)
                    if counted is None:
                        counted = m.get("_legacy_count")
                    if counted is not None:
                        counted = decimal(counted)
                        if counted < 0:
                            raise ValueError("Comptage physique négatif.")
                        delta = counted - running
                        values.update(stock_compte=float(counted), quantite=float(abs(delta)),
                                      type="entree" if delta >= 0 else "sortie")
                    else:
                        delta = _delta(m)
                    running += delta
                    entries += max(delta, Decimal(0))
                    exits += max(-delta, Decimal(0))
                if not math.isfinite(float(running)):
                    raise ValueError("Stock calculé hors limites.")
                negative = negative or running < 0
                values["stock_apres"] = float(running)
                staged.append((m, values))
            _change(plan, "products", p, stock_initial=float(initial), stock_initial_source=source,
                    quantite_stock=float(running))
            for m, values in staged:
                _change(plan, "stock_movements", m, **values)
            plan["stocks"].append({"uuid": p["uuid"], "nom": p["nom"], "initial": float(initial),
                "entries": float(entries), "exits": float(exits), "closing": float(running),
                "previous": safe_value(p["quantite_stock"]), "source": source, "initial_movements": sorted(initial_ids)})
            if negative:
                _issue(plan, "products", p, "Un ancien solde de stock est négatif ; chronologie à vérifier.")
        except (ValueError, KeyError, OverflowError) as exc:
            _issue(plan, "products", p, str(exc))

    accounts = defaultdict(list)
    bad_accounts = set()
    for table, rows in (("transactions", transactions), ("sales", sales)):
        for row in rows:
            try:
                date = dated(row)
                if table == "sales":
                    quantity, price = decimal(row["quantite"]), decimal(row["prix_unitaire"])
                    if quantity <= 0 or price < 0:
                        raise ValueError("Quantité ou prix invalide.")
                    amount = quantity * price
                    if not math.isfinite(float(amount)):
                        raise ValueError("Montant hors limites.")
                    _change(plan, table, row, montant_total=float(amount))
                    if row.get("mode_paiement") == "caisse":
                        # Vente encaissée : elle appartient à la caisse, pas à
                        # un compte client, et n'entre dans aucun solde.
                        continue
                    delta, rank = -amount, 2
                else:
                    amount = decimal(row["montant"])
                    if amount <= 0 or row["type"] not in ("depot", "retrait"):
                        raise ValueError("Montant ou type invalide.")
                    delta, rank = (amount, 0) if row["type"] == "depot" else (-amount, 1)
                if not row.get("deleted"):
                    accounts[row["matricule"]].append((date, rank, row["uuid"], table, row, delta))
            except (ValueError, KeyError, OverflowError) as exc:
                if not row.get("deleted"):
                    bad_accounts.add(row.get("matricule"))
                _issue(plan, table, row, str(exc))
    for matricule, events in accounts.items():
        if matricule in bad_accounts:
            continue
        balance = Decimal(0)
        for _, _, _, table, row, delta in sorted(events, key=lambda e: e[:3]):
            balance += delta
            _change(plan, table, row, solde_apres=float(balance))
        plan["balances"].append({"matricule": matricule, "balance": float(balance)})
        # Un solde négatif représente désormais une dette issue de ventes à crédit.
    return plan


def safe_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(item) for item in value]
    return value


def plan_token(plan):
    return hashlib.sha256(json.dumps(safe_value(plan), sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
