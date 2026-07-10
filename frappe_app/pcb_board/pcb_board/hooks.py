app_name = "pcb_board"
app_title = "PCB Board"
app_publisher = "Musterfirma GmbH"
app_description = "Posteingang, Umsatz-Prognose und Abrechnung als native ERPNext-Seite."
app_email = "m.mustermann@example.com"
app_license = "proprietary"

# Alle 30 Min werktags, ca. 06:00-18:30 Uhr (Server-/DB-Zeitzone des Bench massgebend):
# voller Refresh (ERPNext + Mail + UPS). Dazwischen alle 5 Min ein stiller Mail-only-
# Sync (kein Running-Status, kein Ladehinweis, ERPNext/UPS bleiben unangetastet) —
# damit neue/beantwortete Mails zeitnah auftauchen, ohne bei allen einen Refresh-
# Hinweis auszulösen.
scheduler_events = {
    "cron": {
        "*/30 6-18 * * 1-5": ["pcb_board.refresh.scheduled_refresh"],
        "*/5 6-18 * * 1-5": ["pcb_board.refresh.scheduled_mail_sync"],
    }
}
