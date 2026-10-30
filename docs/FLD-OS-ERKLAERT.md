# FLD OS — was es ist, wie es rechnet, wie wir es weiterbauen

Für Betreiber und Partner von FLD Technologies. Stand: 14.10.2026, Zahlen aus dem Tageslauf vom 14.10.
Ziel dieses Dokuments: Wir beide verstehen genau dasselbe unter jedem Baustein und jeder Zahl, und wir haben
eine gemeinsame Grundlage, um das System bewusst und nachvollziehbar weiterzuentwickeln.

---

## 1 · In einem Satz

**FLD OS sagt einem Biomethan-BHKW jeden Tag, wann es aus seiner festen Gasmenge Strom machen soll,
damit derselbe Brennstoff mehr Geld bringt, und weist nach, wie viel mehr.**

Gemessen über 347 echte Tage des letzten Jahres: rund **120.000 € pro Jahr und MW mehr als Dauerbetrieb
(+33 %)**, so gerechnet, wie es im Betrieb möglich gewesen wäre.

---

## 2 · Das Problem, das wir lösen

- Ein Biomethan-BHKW bekommt **jeden Tag ungefähr dieselbe Menge Gas**. Was es verstromt, ist begrenzt
  (Modellanlage: 1 MW elektrisch, Gas für 8 Volllaststunden am Tag, Gasspeicher für 8 Stunden).
- Der **Strompreis schwankt** innerhalb eines Tages stark (oft zwischen nahe 0 und über 200 €/MWh, manchmal negativ).
- Wer **gleichmäßig** fährt („Dauerbetrieb“), verkauft zum Tagesdurchschnitt. Wer dieselbe Gasmenge in die
  **teuren Viertelstunden** legt, verdient mehr, **ohne mehr Gas zu kaufen**.
- Die Schwierigkeit: Gebote für morgen müssen **heute vor 12:00 Uhr** abgegeben werden, also bevor man die Preise kennt.
  Man braucht eine **Prognose** und einen Fahrplan, der die Grenzen der Anlage einhält.

Genau das macht FLD OS jeden Tag automatisch.

---

## 3 · Der Tagesablauf (die „Tageskette“)

Zweimal am Tag (09:30 und 13:30 Uhr) läuft ein einziger Befehl. Er erledigt nacheinander:

```
 1 Daten holen        Strompreise, Wetter, Netzbetreiber-Prognosen, Gas/CO₂, Regelenergiepreise
        ↓
 2 Prognose           Strompreis für jede Viertelstunde von morgen (mit Unsicherheitsband)
        ↓
 3 Nachweis           dasselbe Verfahren für jeden Tag des letzten Jahres nachgerechnet (Backtest)
        ↓
 4 Fahrplan           Optimierung: wann BHKW, wann Elektrolyse — innerhalb aller Anlagengrenzen
        ↓
 5 Entscheidung       nur Spotmarkt oder zusätzlich Regelenergie vorhalten?
        ↓
 6 Bericht + Datenbank  Cockpit, Tagesbericht, CSV-Fahrplan für Leitwarte/Direktvermarkter
```

- **09:30-Lauf:** Plan auf der Prognose, damit das Gebot vor der Auktion (12:00) steht.
- **13:30-Lauf:** Die Auktionspreise sind jetzt bekannt (ab ~12:45). Der Plan bleibt **derselbe** (das Gebot ist
  abgegeben), aber FLD OS zeigt, was genau dieser Plan zu den echten Preisen bringt. Wir zeigen nie einen Plan,
  den man im Nachhinein mit perfekter Voraussicht hätte machen können, als Empfehlung.

---

## 4 · Die Bausteine einzeln

### 4.1 Daten (alles öffentlich, täglich automatisch)

| Was | Woher | Wofür |
|---|---|---|
| Day-Ahead-Strompreise je ¼ h, Last, Wind, Solar | Energy-Charts, Lücken aus SMARD | Lernen und Abrechnen |
| Wettervorhersagen (Wind 100 m in 5 Windregionen, Sonne + Temperatur in 4 Solarregionen) | Open-Meteo | wichtigste Prognose-Eingabe |
| Netzbetreiber-Prognosen (Last, Wind, Solar) | ENTSO-E | nur Vergleich |
| Gaspreis (TTF), CO₂-Preis (EUA) | Yahoo, EEX | Netto-Erlös, Startwerte |
| Regelenergiepreise aFRR+, aFRR−, FCR | regelleistung.net | Entscheidung Regelenergie |

**Wichtig für die Ehrlichkeit:** Für die Vergangenheit nimmt FLD OS beim Wetter die **Vorhersage vom Vortag**
(nicht das tatsächliche Wetter). So weiß das System in der Nachrechnung genau so viel wie im echten Betrieb um 09:30.

### 4.2 Prognose

- Ein **Lernmodell** (Gradient Boosting) lernt aus Kalender (Stunde, Wochentag, Feiertag), aus Preisen der
  Vortage und aus den Wettervorhersagen, wie der Preis morgen aussieht.
- Es nutzt **nur, was vor der Auktion bekannt ist**. Ein automatischer Test prüft, dass es den Zieltag nie „sieht“.
- Es wird **rollierend** gemessen: Für jeden Monat des letzten Jahres wird nur mit Daten davor trainiert und dann
  vorhergesagt, so wie es im Betrieb gewesen wäre.
- **Kalibrierung:** Liegt die Prognose systematisch daneben, wird das nur dann korrigiert, wenn es messbar hilft.
- **Unsicherheitsband (P10–P90):** Für jede Viertelstunde gibt es nicht nur einen Wert, sondern eine Spanne,
  in der der Preis in 8 von 10 Fällen liegen sollte.
- Güte heute: mittlerer Fehler **20,3 €/MWh** über 12 Monate, „Preis wie gestern“ läge bei 30,8 €/MWh.

### 4.3 Fahrplan (Optimierung)

Ein mathematisches Optimierungsmodell (gemischt-ganzzahlige lineare Optimierung, MILP) sucht für alle 96
Viertelstunden des Tages die beste Kombination, und zwar **innerhalb der Anlagengrenzen**:

| Grenze | Modellwert (ändern auf der Seite „Anlagendaten“) |
|---|---|
| Leistung BHKW / Mindestlast | 1 MW / 50 % |
| Gas pro Tag | 8 Volllaststunden, Gasspeicher 8 Stunden |
| Mindestlaufzeit / Mindeststillstand | je 1 Stunde |
| Startkosten | 50 € je Start |
| Wärme-Grundlast | mindestens 4 Stunden Lauf am Tag |
| Elektrolyseur | 0,5 MW, Wirkungsgrad 62 %, H₂-Wert 100 €/MWh |

Ergebnis: **wann das BHKW läuft** (teure Stunden) und **wann der Elektrolyseur Strom bezieht** (billige oder
negative Stunden, Wasserstoff als Produkt).

### 4.4 Entscheidung: nur Spot oder zusätzlich Regelenergie?

- FLD OS rechnet zwei Varianten: **nur Spotmarkt** und **Spotmarkt + Regelenergie** (Leistung freihalten, die der
  Netzbetreiber bei Bedarf abruft, dafür gibt es Kapazitätsgeld).
- Regelenergie wird nur empfohlen, wenn sie **mindestens 20 € am Tag mehr** bringt (Aufwand, Präqualifikation).
- Entschieden wird **vor den Auktionen** auf der Prognose. Wenn „Regelenergie vorhalten“ empfohlen wird, enthält der
  Fahrplan die **freizuhaltenden MW je Viertelstunde** (Spalten „Reserve hoch/runter“ in der CSV).
- Mögliche Empfehlungen: *Flexibel am Spotmarkt fahren*, *Günstigen Strom in Wasserstoff umwandeln*,
  *Regelenergie vorhalten*.

### 4.5 EEG (Förderung)

- **Marktprämie** = anzulegender Wert − Monatsmarktwert, nie negativ. Standardwert: 231,2 €/MWh
  (Durchschnitt der Biomethan-Ausschreibung 01.09.2026).
- **Keine Prämie bei negativen Preisen** (§ 51).
- **§ 39m Biomethan:** Prämie nur für eine Jahresmenge von 10 % der installierten Leistung (≈ 876 Volllaststunden je MW).
  Unsere Lesart: Das begrenzt die **Prämie**, nicht den Betrieb. Die Seite „EEG-Jahresbudget“ zeigt den anderen Fall
  (Anlage fährt nur ~876 h). **Welche Lesart für FLD gilt, entscheidet FLD.**
- **Flexibilitätszuschlag (§ 50a):** steht auf 0, bis FLD bestätigt, dass Anspruch besteht.
- Alle EEG-Werte sind je Anlage einstellbar.

### 4.6 Nachweis (Backtest)

Für **jeden Tag des letzten Jahres** wurde so getan, als liefe FLD OS schon:
Plan am Vortag auf der damaligen Prognose → abgerechnet zu den **tatsächlichen** Preisen → verglichen mit Dauerbetrieb
und mit dem theoretisch Besten (perfekte Voraussicht).

| Kennzahl | Wert | Bedeutung |
|---|---|---|
| Tage | 347 | vollständige Tage (ohne Zeitumstellung/Lücken) |
| Mehrerlös pro Jahr und MW | ≈ 120.000 € | gegenüber Dauerbetrieb, gleiche Gasmenge |
| Mehrerlös in % | +33 % | bezogen auf den Erlös im Dauerbetrieb |
| Treffsicherheit | 88 % | Anteil des theoretisch Möglichen, den der Plan mit Prognose holt |

### 4.7 Schattenbetrieb (der Weg zum echten Beweis)

FLD lädt Messdaten der echten Anlage hoch (CSV `zeit;leistung_kw`). FLD OS vergleicht Tag für Tag:
**Was hätte unsere Empfehlung gebracht, was hat der tatsächliche Betrieb gebracht, bei gleicher Energiemenge?**
Formel: (Ø-Preis der Empfehlung − Ø-Preis des Betriebs) × gefahrene Energie. Das ist der faire Vergleich.

### 4.8 Enno (Assistent)

Enno beantwortet Fragen in normaler Sprache („Was bringt das im Jahr?“, „Warum läuft das BHKW abends?“,
„Rechne mit Gaspreis 100“). Er rechnet mit denselben Funktionen wie die Seiten, die Zahlen sind also identisch.
Standardmäßig läuft er **ohne externes KI-Modell** (regelbasiert, keine Kosten, keine Daten nach außen).

---

## 5 · Die Oberfläche: jede Seite in einem Satz

| Bereich | Seite | Was sie zeigt | Wofür |
|---|---|---|---|
| Betrieb | **Cockpit** | Empfehlung für morgen, Begründung, Jahreswert, Fahrplan-Diagramm | Einstieg, 30-Sekunden-Überblick |
| | **Fahrplan** | Stundentabelle, Begründung, Prüfregeln, CSV-Download | geht an Leitwarte/Vermarkter |
| Planung | **Was-wäre-wenn** | Regler für Gas, H₂, CO₂, Technik, Optimierer; Szenarien merken und vergleichen | Workshop mit FLD |
| | **Sensitivität** | welche Annahme das Netto am stärksten bewegt (±30 %) | Prioritäten klären |
| | **Risiko** | Erlös gegen Absicherung (CVaR), Wert der Prognose | Risikoappetit besprechen |
| | **Erlös ↔ CO₂** | was Umplanen fürs Klima kosten würde | ehrliche Klimafrage |
| Erlöse & Technologie | **Erlös-Stapel** | Spot + Regelenergie + PtX je Tag | Zusatzerlöse sehen |
| | **Plasma vs. Elektrolyse** | welcher Wasserstoffpfad mehr bringt | Technologieentscheidung |
| | **CDR-Preis** | ab welchem Kohlenstoffpreis sich Plasma-Pyrolyse lohnt | Geschäftsmodell CO₂-Entnahme |
| | **EEG-Jahresbudget** | Fall „nur ~876 h/Jahr“: auf welchen Tagen fahren | EEG-Lesart klären |
| Prognose & Markt | **Prognose-Güte** | Fehler, Kalibrierung, Prognose vs. Ist | Vertrauen in die Prognose |
| | **Prognoseband** | Unsicherheit und wie gut sie stimmt | Risiko verstehen |
| | **Markt** | Gas, CO₂, Regelenergiepreise im Verlauf | Marktkontext |
| | **Datenanalyse** | Grafiken der Vorstudie (Juni 2026) | Herleitung des Modells |
| Nachweis | **Backtest** | Mehrerlös über das letzte Jahr, Tag für Tag | der Beweis |
| | **Schattenbetrieb** | Empfehlung gegen echten Betrieb | Pilotphase |
| | **Speicher & MPC** | Planung über mehrere Tage | Ausblick |
| Anlage | **Anlagendaten** | echte Werte der FLD-Anlage eintragen, mit Plausibilitätsprüfung | aus Modell wird FLD-Anlage |

---

## 6 · Begriffe, die überall dasselbe bedeuten

| Begriff | Bedeutung |
|---|---|
| **Dauerbetrieb** | Die Vergleichsbasis: dieselbe Gasmenge gleichmäßig über den Tag verstromt. |
| **Mehrerlös** | Erlös des Fahrplans minus Erlös im Dauerbetrieb, bei gleicher Gasmenge. Hängt **nicht** vom Gaspreis ab. |
| **Netto inkl. EEG** | Erlöse (Strom, Wärme, H₂, CO₂, Marktprämie, Flexzuschlag) minus Gas- und Strombezugskosten. Hängt vom Gaspreis ab. Überall dieselbe Zahl (Was-wäre-wenn, Tabelle, Sensitivität, Enno). |
| **Gebotsplan** | Der Fahrplan, der vor der Auktion auf der Prognose gerechnet wurde, also die eigentliche Empfehlung. |
| **Treffsicherheit** | Wie viel vom theoretisch möglichen Mehrerlös (perfekte Voraussicht) der Gebotsplan wirklich holt. |
| **MAE** | Mittlerer absoluter Prognosefehler in €/MWh. |
| **P10–P90** | Spanne, in der der Preis in 8 von 10 Fällen liegt. |
| **Marktzeit** | Alle Uhrzeiten in deutscher Zeit (Europe/Berlin). Tage mit Zeitumstellung haben 92 bzw. 100 Viertelstunden. |
| **Mandant** | Ein Kunde mit seinen eigenen Daten; strikt getrennt von allen anderen. |

---

## 7 · Ehrliche Grenzen (offen ansprechen)

1. **Modellanlage**, solange FLD keine echten Werte einträgt (1 MW, Standardwerte).
2. **Wärme vereinfacht:** Mindestlaufzeit statt echtem Wärmelastgang.
3. **Regelenergie** mit Durchschnittspreisen der letzten 30 Tage, ohne Gebotsrisiko und ohne Abrufenergie.
4. **Kein Intraday-Handel:** Der Plan steht nach der Day-Ahead-Auktion fest.
5. **Vor 2024** gibt es keine archivierten Vortagsvorhersagen. Diese Monate dienen nur dem Training, nie der Messung.
6. **Kein Live-Nachweis an der echten Anlage** bis zum Schattenbetrieb. Der Backtest ist eine Nachrechnung, kein Betrieb.

---

## 8 · Technik (für alle, die mitbauen)

```
 Datenquellen ──► Tageskette (Python) ──► Postgres (je Mandant) ──► API (FastAPI) ──► Oberfläche (React)
                    fldos/pipeline/          fld_os                    fldos/api.py        web/src/pages/
                    engine/ (Optimierung)                              Enno: fldos/enno.py
```

| Teil | Wo | Kurz |
|---|---|---|
| Tageskette | `fldos/pipeline/` (`fetch`, `model`, `plan`, `report`) | ein Befehl: `python -m fldos.pipeline` |
| Optimierung | `engine/` (`whatif`, `coopt_milp`, `backtest_forecast`, …) | MILP mit PuLP/CBC |
| API | `fldos/api.py`, Vertrag `docs/openapi.json` | jede Abfrage an den Mandanten aus dem Login gebunden |
| Datenbank | Postgres, Migrationen `alembic/versions/` | Betrieb `fld_os`, Prüfungen `fld_os_test` |
| Oberfläche | `web/` (React, Vite, Chart.js) | FLD-Farben nur in `web/src/theme.css` + `brand.ts` |
| Start | `./demo.sh` | holt Daten, rechnet, startet alles |
| Prüfungen | `~/.claude/bin/checks-run` (Definition `.checksrc`) | Backend-Tests, Abnahme, Build, Browser-Tests in Chrome |

**Qualität:** Jede Änderung muss alle Prüfungen bestehen: rund 90 Backend-Tests, 42 Abnahmetests und gut 40
Browser-Tests, die jeden Knopf klicken und prüfen, dass die Oberfläche genau die Zahl der API zeigt.
Die Prüfungen laufen auf einer **eigenen Test-Datenbank**, echte Anlagenwerte werden nie überschrieben.

Betrieb im Detail: `docs/BETRIEB.md`. Vorführung: `docs/DEMO.md`. Pilotvorschlag: `docs/PILOT.md`.

---

## 9 · Wie wir es gemeinsam klar weiterentwickeln

### Fünf Regeln, die sich bewährt haben

1. **Nur Wissen, das man zum Zeitpunkt der Entscheidung hätte.** Jede Kennzahl wird so gerechnet, wie sie im
   Betrieb entstanden wäre. Sonst sieht das System besser aus, als es ist.
2. **Ein Begriff, eine Bedeutung, eine Funktion.** „Netto“ wird an genau einer Stelle gerechnet und überall verwendet.
   Neue Begriffe kommen zuerst in die Tabelle in Abschnitt 6.
3. **Jede Zahl ist nachrechenbar.** Für jede Zahl auf dem Bildschirm gibt es eine API-Antwort und einen Test,
   der prüft, dass beide gleich sind.
4. **Erst der Test, dann die Änderung.** Ein Fehler wird zuerst als Test nachgestellt, dann behoben, mit
   benannter Ursache.
5. **Der Mensch entscheidet.** FLD OS empfiehlt und begründet, gefahren wird erst nach Freigabe.

### Wie eine neue Idee ins System kommt

```
 Frage von FLD  →  Annahme aufschreiben  →  messbares Kriterium festlegen  →  Test  →  bauen  →  Backtest/Schattenbetrieb  →  behalten oder verwerfen
```

Beispiel: „Lohnt sich Intraday?“ → Annahme „ja, bei großer Prognoseabweichung“ → Kriterium „+X €/Jahr im
Backtest ohne Vorwissen“ → erst dann bauen.

### Was FLD als Nächstes entscheiden oder liefern muss

| Thema | Frage an FLD | Wirkung |
|---|---|---|
| Anlagenwerte | Leistung, Wirkungsgrade, Gasspeicher, Wärmebedarf der Pilotanlage | Zahlen werden die eigenen |
| EEG | Welche Lesart von § 39m gilt? Anzulegender Wert? Anspruch auf Flexzuschlag? | Netto und EEG-Seite stimmen genau |
| Betriebsdaten | 12 Monate Viertelstundenwerte einer Anlage | Schattenbetrieb, echter Nachweis |
| Vermarktung | Wer ist der Direktvermarkter, welches Format braucht er? | Fahrplan geht automatisch raus |
| Hosting | Wo soll FLD OS laufen (EU-Cloud, eigene Server)? | Dauerbetrieb, Login, Überwachung |

### Fahrplan der nächsten Schritte

1. **Demo (17.10.):** Mehrwert zeigen, gemeinsam an den Reglern rechnen, Fragen sammeln.
2. **Schattenbetrieb (4–8 Wochen):** echte Anlage, echte Messdaten, täglicher Vergleich, kein Eingriff in den Betrieb.
3. **Live mit Freigabe:** Fahrplan geht an Vermarkter/Leitwarte, ein Mensch gibt täglich frei.
4. **Weitere Anlagen und Kunden:** je Kunde ein Mandant, gleiche Plattform.
5. **Modell vertiefen**, jeweils mit Messung: Wärmelastgang, Intraday, Regelenergie mit Gebotsrisiko.
