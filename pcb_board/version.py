"""Build-Stempel fürs Diagnose-Panel — zeigt, ob eine Frappe-Cloud-Installation
den aktuellen Stand von frappe-app-pcb-board gezogen hat.

Wird bei jeder relevanten Änderung an frappe_app/pcb_board von Hand aktualisiert
(BUILD_COMMIT verweist auf den Commit, der den zuletzt gepushten Funktionsstand
enthält — der Stempel-Commit selbst kommt naturgemäß eine Ebene später).
"""

BUILD_TIME = "2026-08-04T07:09:39+00:00"
BUILD_COMMIT = "de370de7f007ecbe8b84b7c92f3d08651ab4f746"
