"""Valeur exacte pour Excel, libellé lisible pour les écrans/PDF."""
from decimal import Decimal


class ReportValue(str):
    def __new__(cls, value, money=False):
        number = Decimal(str(value if value is not None else 0))
        if not number.is_finite():
            raise ValueError('Valeur de rapport non finie.')
        text = format(number, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        if money:
            whole, dot, fraction = text.partition('.')
            text = ('-' if whole.startswith('-') else '') + format(abs(int(whole)), ',').replace(',', ' ') + (dot + fraction if dot else '') + ' GNF'
        obj = super().__new__(cls, text)
        obj.numeric_value = int(number) if number == number.to_integral_value() else float(number)
        obj.number_format = '#,##0.##########' + (' "GNF"' if money else '')
        return obj


def report_number(value):
    return ReportValue(value)


def report_money(value):
    return ReportValue(value, money=True)
