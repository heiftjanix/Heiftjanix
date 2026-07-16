"""Täglicher KPI-Schnappschuss (ein Datensatz pro Tag, beim Refresh fortgeschrieben).

Grundlage für Trend-Anzeigen im Board (z. B. „überfällige Auftragssumme ggü.
Vorwoche") — das Board selbst kennt sonst nur den Live-Zustand.
"""
import frappe
from frappe.model.document import Document


class PCBBoardKPISnapshot(Document):
    pass
