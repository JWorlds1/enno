# FLD OS — Pilotvorschlag „Schattenbetrieb“

**Ziel:** In 6–8 Wochen schwarz auf weiß zeigen, was FLD OS an **Ihrer** Anlage bringt — ohne Eingriff in den Betrieb.
FLD OS rechnet jeden Tag einen Fahrplan, die Anlage fährt wie bisher; danach vergleichen wir Euro für Euro.

## Ablauf

| Woche | Schritt | FLD | FLD OS |
|---|---|---|---|
| 1 | Daten übergeben, Anlage einrichten | Anlagendaten + 12 Monate Betriebsdaten (Liste unten) | Import, Plausibilitätsprüfung, Modell kalibrieren |
| 2 | Rückrechnung | — | Backtest mit Ihrer Anlage: was hätte FLD OS im letzten Jahr gebracht? |
| 3–7 | Schattenbetrieb | Fahrweise wie bisher; wöchentlich Messdaten (CSV) | täglicher Fahrplan + Tagesbericht; Vergleich empfohlen ↔ gefahren |
| 8 | Ergebnis | Auswertungstermin | Bericht: Mehrerlös, Treffsicherheit, Grenzen, Empfehlung zum Livebetrieb |

**Ergebnis:** gemessener Mehrerlös je Woche und hochgerechnet aufs Jahr, Prognosegüte, Liste der Betriebsgrenzen,
die den Plan beschränkt haben — und eine Entscheidungsgrundlage für den Livebetrieb.

## Datenanforderung

**Anlagendaten** (einmalig; Import als CSV `parameter;wert` oder direkt in FLD OS → Anlagendaten)

| Parameter | Einheit | Wofür |
|---|---|---|
| Elektrische Leistung BHKW | MW | Fahrplan, Erlös |
| Elektrischer Wirkungsgrad | 0–1 | Gas → Strom |
| Mindestlast | Anteil der Leistung | kleinster Betriebspunkt |
| Startkosten | € je Start | Verschleiß, Start-Stopp-Abwägung |
| Mindestlauf- / Mindeststillstandszeit | Viertelstunden | Technik |
| Gasmenge pro Tag | Volllaststunden/Tag | Gasbudget |
| Gasspeicher | Volllaststunden | wie weit Verstromung verschoben werden kann |
| Wärme: Mindestlaufzeit pro Tag, Wärmeerlös | h/Tag, €/MWh | Wärmeversorgung, Wärmegutschrift |
| Elektrolyseur (falls vorhanden): Leistung, Wirkungsgrad, H₂-Wert, Betriebskosten | MW, 0–1, €/MWh | PtX |
| EEG: anzulegender Wert, Regelung (§ 39m / § 39i / Altanlage), Flexibilitätszuschlag ja/nein | €/MWh | Netto inkl. Marktprämie |
| Gaspreis / Biomethan-Bezugskonditionen | €/MWh | Netto-Erlös |

**Betriebsdaten** (12 Monate rückwirkend, danach wöchentlich): Viertelstundenwerte der **eingespeisten Leistung**
(Zähler oder Leitwarte), wenn möglich **Wärmeabgabe** und **Gasspeicherstand**. Format: CSV mit Zeitstempel + kW.

**Organisatorisch:** Wer vermarktet den Strom (Direktvermarkter)? Wie werden Fahrpläne heute übermittelt
(Format, Uhrzeit)? Ansprechpartner Technik + Vermarktung.

## Was FLD OS bereitstellt

Täglicher Fahrplan (CSV, Viertelstunden, Marktzeit), Tagesbericht, Zugang zur Oberfläche mit eigenem Mandanten,
Szenario-Workshops (Was-wäre-wenn), Abschlussbericht. Daten bleiben getrennt von anderen Kunden; keine
personenbezogenen Daten nötig.

## Was im Pilot bewusst nicht passiert

Kein Eingriff in die Anlagensteuerung, kein Gebot im Markt durch FLD OS — der Mensch entscheidet. Intraday-Handel
ist nicht Teil des Pilots.
