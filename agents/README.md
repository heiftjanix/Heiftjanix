# Mail-Entwurfsagent PCB-Systems — Quelle der Triage-Regeln

Hier liegt die Original-Definition des Claude-Platform-Agenten, aus der die
Mail-Triage des Boards ihre Regeln bezieht. Die Dateien sind **Referenz, kein
Laufzeit-Artefakt**: das Board ruft diesen Agenten nicht auf.

| Datei | Inhalt |
|---|---|
| `mail-entwurfsagent-pcb-systems.md` | Agent-Definition; der Markdown-Teil ist der Systemprompt |
| `pcb-systems-mail-env.yml` | Umgebung der Agent-Sessions (`ant apply`) |

## Wie es im Board umgesetzt ist

Der Systemprompt ist in `frappe_app/pcb_board/pcb_board/triage.py` als Konstante
`RELEVANCE_GUIDANCE` eingebettet, das Ausgabeschema als `MailTriage`. Das Board
ruft damit die Anthropic-API direkt auf — gebatcht zu 20 Mails pro Call, weil
das Konto ein knappes Requests-pro-Minute-Limit hat. Ein Aufruf des gehosteten
Agenten wäre eine Session je Mail und liefe sofort ins Limit.

**Wer den Prompt ändert, muss beides anfassen**: diese Datei (für den gehosteten
Agenten) und `triage.py` (fürs Board). Sie werden nicht automatisch
synchronisiert; ein Test in `tests/test_triage.py` prüft nur, dass die
wesentlichen Regeln im Board-Prompt überhaupt vorkommen.

## Was bewusst NICHT übernommen ist

Punkt 5 des Agenten — **Stücklisten im Anhang gegen das ERPNext-Einkaufstool
prüfen**. Dafür fehlen im Board zwei Voraussetzungen:

1. `graph.py` holt aus Outlook nur `bodyPreview`, also weder den vollen Mailtext
   noch Anhänge. Es gibt schlicht keine MPNs, die man prüfen könnte.
2. Der Board-Pfad ist ein einzelner `messages.parse`-Call ohne Werkzeuge. Eine
   Stücklistenabfrage bräuchte Tool-Use und damit einen anderen Aufruf.

Das ist ein eigenes Vorhaben (Anhang-Pipeline), kein Nebeneffekt dieser
Integration.
