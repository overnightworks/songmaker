# Design

Hier liegen die vom Operator gesegneten Bilder von Oberflächen — das, wogegen
gebaut wird. Ein Bild ist erst gesegnet, wenn es hier im Repository als
Besitzer eingefroren ist; ein Artefakt-Link allein reicht nicht.

**Warum:** Ein Bild, das nur als Artefakt-Link in einer Milestone-Beschreibung
lebt, verschwindet. Genau das ist am 30.08.2026 passiert: Der Link zeigte ins
Leere, und niemand hat es gemerkt, bis jemand danach gesucht hat.

**Regel:** Eine Änderung an einer Oberfläche (Raum, Seite, Karte, Ablauf)
fängt hier an — Bild lesen, Änderung einzeichnen, Freigabe des Operators
einholen, dann bauen. Wording- und Fehlerkorrekturen brauchen kein Bild.

## Inhalt

- `navigation.html` — die Navigation (#263). Erste Fassung freigegeben am
  30.08.2026, zweite Fassung freigegeben am 31.08.2026 — gegen die inzwischen
  gelandete Adressstruktur (#265) gehalten: jede Zeile der Leiste ist jetzt
  eine echte Adresse, das Aufklappen ist reine Darstellung.
- `admin-models.html` — der Admin-Tab „Models" (#317). Erste Fassung
  freigegeben am 01.09.2026: Provider-Status oben, Co-Writer und Scoring als
  baugleiche Blöcke darunter, totes Chat-Model-Feld entfernt. Backend-
  Voraussetzungen: #316 (echter Provider-Status) und #315 (Judge
  providerneutral).
