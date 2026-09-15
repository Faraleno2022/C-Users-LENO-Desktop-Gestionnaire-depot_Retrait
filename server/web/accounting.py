"""Calculs décimaux avant stockage dans les colonnes historiques en flottant.

Ce petit module reste autonome : bureau et console web sont distribués séparément.
"""
from decimal import Decimal
from math import isfinite


def number(value):
    value = float(str(value).replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", "."))
    if not isfinite(value):
        raise ValueError("Le montant ou la quantité doit être un nombre fini.")
    return value


def add(*values):
    return number(sum((Decimal(str(number(v))) for v in values), Decimal(0)))


def subtract(left, right):
    return add(left, -number(right))


def multiply(left, right):
    return number(Decimal(str(number(left))) * Decimal(str(number(right))))
