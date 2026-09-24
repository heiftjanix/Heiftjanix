"""BOM-Klasse mit 0-€-Bewertung für beigestellte Positionen.

Eingehängt über ``hooks.override_doctype_class``. Die Rechenlogik selbst steht
in :mod:`pcb_board.beigestellt`; hier hängt sie nur an den richtigen Stellen
der ERPNext-BOM-Klasse.

**Wo angesetzt wird und warum ausgerechnet dort.** ERPNext hat die Kalkulation
zwischen Versionen umgebaut: in v15 rechnen ``calculate_rm_cost`` und
``calculate_exploded_cost`` direkt in der BOM-Klasse, in neueren Ständen
delegieren sie an interne Service-Klassen (``BOMCostingService``,
``BOMExplodedItemsService``) und rufen sich untereinander auf, ohne noch einmal
über das Dokument zu gehen. Ein Override der einzelnen Rechenmethoden würde
dort also stillschweigend übersprungen.

Deshalb wird hier an den **äußeren** Einstiegen angesetzt, die es in beiden
Bauarten am Dokument gibt und die jeder Weg durchläuft:

* ``calculate_cost``        — Speichern/Submit (über ``validate``),
                              „Kosten aktualisieren" (``update_cost``) und das
                              Stücklisten-Aktualisierungstool, das seinerseits
                              ``update_cost`` am Dokument aufruft.
* ``update_exploded_items`` — Neuaufbau der Tabelle ``exploded_items``.

Beide rufen zuerst das Original und korrigieren danach. Rechnerisch ist das
identisch damit, die Sätze vor dem Summieren zu nullen: die Summe wird aus den
korrigierten Zeilen neu gebildet, nicht nachträglich geschätzt.

Nicht angefasst werden Lagerbewegungen und die Lagerbewertung — ausschließlich
die Kalkulation in der Stückliste.
"""
from __future__ import annotations

from erpnext.manufacturing.doctype.bom.bom import BOM

from pcb_board import beigestellt


class BeigestelltBOM(BOM):
    """BOM, die beigestellte Positionen durchgängig mit 0 € führt."""

    def calculate_cost(self, *args, **kwargs):
        result = super().calculate_cost(*args, **kwargs)
        # Signatur ist versionsabhängig (save_updates bzw. save als 1. Argument):
        # beide Male entscheidet das erste Positionsargument bzw. das Keyword,
        # ob gebuchte Zeilen mitgeschrieben werden.
        save = bool(args[0]) if args else bool(
            kwargs.get("save_updates", kwargs.get("save", False)))
        self.apply_beigestellt(save=save)
        return result

    def update_exploded_items(self, save=True, *args, **kwargs):
        result = super().update_exploded_items(save=save, *args, **kwargs)
        self.zero_beigestellt_exploded(save=save)
        return result

    # -- Korrekturen ------------------------------------------------------

    def apply_beigestellt(self, save: bool = False) -> None:
        """Positionen und Explosion auf 0 ziehen und die Summen nachführen."""
        items = self.get("items") or []
        if not beigestellt.beigestellt_item_codes(items):
            return

        before_rm = float(self.raw_material_cost or 0)
        before_base_rm = float(self.base_raw_material_cost or 0)

        for row in beigestellt.zero_item_rows(items):
            if save and self.docstatus == 1:
                row.db_update()

        rm_cost, base_rm_cost = beigestellt.raw_material_totals(items)
        self.raw_material_cost = rm_cost
        self.base_raw_material_cost = base_rm_cost

        # total_cost wird je nach Version aus unterschiedlichen Bestandteilen
        # gebildet (Ausschuss bzw. Nebenprodukte). Statt die Formel
        # nachzubauen, wird nur der weggefallene Materialanteil abgezogen — der
        # geht in jeder Version mit Faktor 1 in die Gesamtkosten ein.
        self.total_cost = float(self.total_cost or 0) - (before_rm - rm_cost)
        self.base_total_cost = float(self.base_total_cost or 0) - (
            before_base_rm - base_rm_cost)

        self.zero_beigestellt_exploded(save=save)

    def zero_beigestellt_exploded(self, save: bool = False) -> None:
        """Explosionszeilen beigestellter Artikel auf 0 €.

        Nötig zusätzlich zum Nullen der Positionen: hat eine beigestellte Zeile
        eine Unterstückliste, zieht ERPNext den Satz aus deren Explosion und
        nicht aus der Elternzeile.
        """
        codes = beigestellt.beigestellt_item_codes(self.get("items") or [])
        changed = beigestellt.zero_exploded_rows(self.get("exploded_items") or [], codes)
        if not save:
            return
        for row in changed:
            if row.get("name"):
                row.db_update()
