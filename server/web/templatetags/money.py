"""Filtres template : formatage monétaire et nombre."""
from django import template

register = template.Library()


@register.filter(name="money")
def money(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.0f}".replace(",", " ")
    return f"{s} GNF"


@register.filter(name="num")
def num(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return value
    return f"{v:,.0f}".replace(",", " ")
