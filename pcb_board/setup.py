"""Einmalige Einrichtung, die beim Migrieren mitläuft (hooks.after_migrate).

Bisher nur das Feld „Wiedervorlage" am Kundenauftrag: Mitarbeitende tragen dort
bei Teillieferung oder Verzögerung einen Termin ein, das Board zeigt ihn in der
Liefertermin-Liste. Bewusst ein Custom Field am Sales Order (nicht im Board):
gepflegt wird im Auftrag selbst, das Board liest nur mit.
"""
from __future__ import annotations

import frappe

CUSTOM_FIELDS = [
    {
        "dt": "Sales Order",
        "fieldname": "custom_wiedervorlage",
        "label": "Wiedervorlage",
        "fieldtype": "Date",
        "insert_after": "delivery_date",
        # Verzögerungen zeigen sich NACH der Freigabe des Auftrags — ohne
        # allow_on_submit käme niemand mehr an das Feld heran.
        "allow_on_submit": 1,
        "no_copy": 1,
        "description": ("Bei Teillieferung oder Verzögerung: Termin, an dem der Auftrag "
                         "wieder vorgelegt werden soll. Erscheint im Team-Board in der "
                         "Liefertermin-Liste."),
    },
]


def ensure_custom_fields() -> None:
    """Legt fehlende Custom Fields an; vorhandene bleiben unangetastet (die
    Einstellungen könnten vor Ort bewusst angepasst worden sein)."""
    for spec in CUSTOM_FIELDS:
        name = f"{spec['dt']}-{spec['fieldname']}"
        if frappe.db.exists("Custom Field", name):
            continue
        doc = frappe.new_doc("Custom Field")
        doc.update(spec)
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
