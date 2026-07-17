"""Build-Stempel fürs Diagnose-Panel — zeigt, ob eine Frappe-Cloud-Installation
den aktuellen Stand von frappe-app-pcb-board gezogen hat.

Wird bei jeder relevanten Änderung an frappe_app/pcb_board von Hand aktualisiert
(BUILD_COMMIT verweist auf den Commit, der den zuletzt gepushten Funktionsstand
enthält — der Stempel-Commit selbst kommt naturgemäß eine Ebene später).
"""

BUILD_TIME = "2026-07-17T13:29:16+00:00"
BUILD_COMMIT = "9ee03c6689e03d25fea73f206e708a4effdff48b"
