"""Notiz zu einem Produktionsauftrag: vom Team gesetzter, korrigierter
Liefertermin plus freie Bemerkung.

Bewusst ein eigenes Dokument statt eines Custom Fields am Work Order: das Board
soll nichts an den ERPNext-Belegen verändern (harte Regel „nur Vorschläge"), und
die Notiz bleibt auch bestehen, wenn der Auftrag abgeschlossen wird.
"""
from __future__ import annotations

from frappe.model.document import Document


class PCBBoardWorkOrderNote(Document):
    pass
