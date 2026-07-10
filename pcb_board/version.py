"""Build-Stempel fürs Diagnose-Panel — zeigt, ob eine Frappe-Cloud-Installation
den aktuellen Stand von frappe-app-pcb-board gezogen hat.

Wird bei jeder relevanten Änderung an frappe_app/pcb_board von Hand aktualisiert
(BUILD_COMMIT verweist auf den Commit, der den zuletzt gepushten Funktionsstand
enthält — der Stempel-Commit selbst kommt naturgemäß eine Ebene später).
"""

BUILD_TIME = "2026-07-10T14:13:37+00:00"
BUILD_COMMIT = "a29fee66dbb9e711f95b07e6898b69b0478c69a6"
