"""Build-Stempel fürs Diagnose-Panel — zeigt, ob eine Frappe-Cloud-Installation
den aktuellen Stand von frappe-app-pcb-board gezogen hat.

Wird bei jeder relevanten Änderung an frappe_app/pcb_board von Hand aktualisiert
(BUILD_COMMIT verweist auf den Commit, der den zuletzt gepushten Funktionsstand
enthält — der Stempel-Commit selbst kommt naturgemäß eine Ebene später).
"""

BUILD_TIME = "2026-07-10T17:42:29+00:00"
BUILD_COMMIT = "3f5143859f66f737cc1851809015c20b214ce6e8"
