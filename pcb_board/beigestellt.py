"""Bewertung beigestellter Stücklistenpositionen mit 0 €.

Beigestellt = der Kunde liefert das Teil bei, es taucht also in unserer
Kalkulation nicht als Kosten auf. Markiert wird das am BOM Item über das
Custom Field ``custom_beigestellt`` (Check).

Dieses Modul enthält bewusst **nur reine Rechenlogik ohne frappe/erpnext-
Import** — damit sie ohne Bench testbar bleibt. Die Anbindung an die
BOM-Klasse steckt in ``pcb_board.bom_override``.

Warum überhaupt eigener Code, wo ERPNext doch ``sourced_by_supplier`` und
``Item.is_customer_provided_item`` kennt und beide in ``get_rm_rate`` auf 0
setzt? Weil das die Stücklisten-Explosion nicht abdeckt: hat eine beigestellte
Zeile eine Unterstückliste (``bom_no``), holt ERPNext die Sätze über
``get_child_exploded_items`` bzw. ``get_rm_rate_map`` aus der Explosion der
Unterstückliste — am Satz der Elternzeile vorbei. Genau der Fall (Artikel 9999
mit BOM-9999-001) bleibt dort also bepreist. Deshalb wird hier nachkorrigiert.
"""
from __future__ import annotations

from typing import Any, Iterable

#: Feldname der Markierung am BOM Item.
FLAG = "custom_beigestellt"

#: Felder einer Positionszeile, die auf 0 gehen.
ITEM_ZERO_FIELDS = ("rate", "base_rate", "amount", "base_amount")

#: Felder einer Explosionszeile, die auf 0 gehen.
EXPLODED_ZERO_FIELDS = ("rate", "amount")


def _get(row: Any, field: str, default: Any = None) -> Any:
    """Feld lesen — funktioniert für frappe-Dokumente wie für schlichte Objekte."""
    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            return getter(field, default)
        except TypeError:  # dict.get mit nur einem Argument o. ä.
            pass
    return getattr(row, field, default)


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def is_beigestellt(row: Any) -> bool:
    return bool(_get(row, FLAG))


def beigestellt_item_codes(items: Iterable[Any]) -> set[str]:
    """Artikelnummern aller beigestellten Positionen einer Stückliste."""
    return {code for row in items
            if is_beigestellt(row) and (code := _get(row, "item_code"))}


def zero_item_rows(items: Iterable[Any]) -> list[Any]:
    """Satz und Betrag beigestellter Positionen auf 0 setzen.

    Gibt die Zeilen zurück, die sich dadurch tatsächlich geändert haben — der
    Aufrufer kann daran entscheiden, ob ein ``db_update()`` nötig ist.
    """
    changed = []
    for row in items:
        if not is_beigestellt(row):
            continue
        if not any(_num(_get(row, f)) for f in ITEM_ZERO_FIELDS):
            continue
        for field in ITEM_ZERO_FIELDS:
            setattr(row, field, 0.0)
        changed.append(row)
    return changed


def zero_exploded_rows(exploded: Iterable[Any], codes: set[str]) -> list[Any]:
    """Satz und Betrag der Explosionszeilen zu beigestellten Artikeln auf 0.

    Die Explosion fasst je Artikelnummer zusammen. Wird derselbe Artikel in
    einer Stückliste sowohl beigestellt als auch selbst beschafft verbaut,
    landet er hier trotzdem komplett auf 0 — eine getrennte Zuordnung gibt die
    zusammengefasste Tabelle nicht her, und die vorsichtigere Annahme ist, den
    beigestellten Anteil nicht zu bepreisen.
    """
    if not codes:
        return []
    changed = []
    for row in exploded:
        if _get(row, "item_code") not in codes:
            continue
        if not any(_num(_get(row, f)) for f in EXPLODED_ZERO_FIELDS):
            continue
        for field in EXPLODED_ZERO_FIELDS:
            setattr(row, field, 0.0)
        changed.append(row)
    return changed


def raw_material_totals(items: Iterable[Any]) -> tuple[float, float]:
    """Materialkosten neu aufsummieren (Betrag, Betrag in Firmenwährung)."""
    rows = list(items)
    return (sum(_num(_get(r, "amount")) for r in rows),
            sum(_num(_get(r, "base_amount")) for r in rows))
