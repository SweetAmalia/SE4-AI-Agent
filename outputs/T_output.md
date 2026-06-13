2026-06-11 15:01:15.025 | INFO     | __main__:node_parse_input:275 - Node 1 — intent extractie

📋 Dit heb ik begrepen:
   • 12x Red Bull
   • 13x banaan
   • 5x melk
   • 3x frikandelbroodje

2026-06-11 15:01:27.145 | SUCCESS  | __main__:node_parse_input:314 - Extractie OK: locatie=None, items=['12x Red Bull', '13x banaan', '5x melk', '3x frikandelbroodje']
2026-06-11 15:01:27.147 | INFO     | __main__:node_locatie:342 - Node 2 — automatische locatiebepaling (Geolocation API)
2026-06-11 15:01:28.432 | SUCCESS  | __main__:node_locatie:354 - Locatie (automatisch): Linnaeusstraat 14, 2522 GS Den Haag, Netherlands
2026-06-11 15:01:28.440 | INFO     | __main__:node_winkels:368 - Node 3 — dichtstbijzijnde supermarkten zoeken
2026-06-11 15:01:29.569 | SUCCESS  | __main__:node_winkels:377 - Albert Heijn: AH Lorentzplein op 0.3 km (Lorentzplein 76, Den Haag)
2026-06-11 15:01:29.569 | SUCCESS  | __main__:node_winkels:377 - Jumbo: Jumbo op 1.0 km (Laakweg 126, Den Haag)
2026-06-11 15:01:29.574 | SUCCESS  | __main__:node_winkels:377 - Lidl: Lidl op 2.0 km (Wesselsstraat 500, Den Haag)
2026-06-11 15:01:29.574 | SUCCESS  | __main__:node_winkels:377 - Hoogvliet: Hoogvliet op 1.1 km (Hendrik Ravesteijnplein 40, Rijswijk)
2026-06-11 15:01:29.576 | INFO     | __main__:node_vergelijk_prijzen:389 - Node 4 — prijzen vergelijken (AH + Jumbo)
2026-06-11 15:01:30.692 | DEBUG    | __main__:_safe_jumbo_price:220 - Jumbo match 'Red Bull Energy Drink Suikervrij Voordeelverpakking - 6 x 250ml' → €9.89
2026-06-11 15:01:30.692 | DEBUG    | __main__:node_vergelijk_prijzen:422 - 12x Red Bull: AH €395.28 (✓) | Jumbo €118.68 (✓)
2026-06-11 15:01:30.692 | DEBUG    | __main__:_safe_jumbo_price:220 - Jumbo match 'Jumbo Banaan Schuim Zoet & Zacht 250 g' → €1.79
2026-06-11 15:01:30.692 | DEBUG    | __main__:node_vergelijk_prijzen:422 - 13x banaan: AH €64.87 (✓) | Jumbo €23.27 (✓)
2026-06-11 15:01:30.696 | DEBUG    | __main__:_safe_jumbo_price:220 - Jumbo match 'Campina Verse Halfvolle Melk Voordeelpak 1,5 L' → €1.89
2026-06-11 15:01:30.696 | DEBUG    | __main__:node_vergelijk_prijzen:422 - 5x melk: AH €28.35 (✓) | Jumbo €9.45 (✓)
2026-06-11 15:01:30.696 | DEBUG    | __main__:_safe_jumbo_price:220 - Jumbo match 'Scharreleieren Wit 12 Stuks' → €3.74
2026-06-11 15:01:30.696 | DEBUG    | __main__:node_vergelijk_prijzen:422 - 3x frikandelbroodje: AH €31.56 (✓) | Jumbo €11.22 (✓)

📍 Locatie (automatisch bepaald): Linnaeusstraat 14, 2522 GS Den Haag, Netherlands

💶 Prijsvergelijking (AH vs Jumbo):
  • 12x Red Bull                 AH  €395.28  |  Jumbo  €118.68
  • 13x banaan                   AH   €64.87  |  Jumbo   €23.27
  • 5x melk                      AH   €28.35  |  Jumbo    €9.45
  • 3x frikandelbroodje          AH   €31.56  |  Jumbo   €11.22
  Totaal: AH €520.06  |  Jumbo €162.62

🏪 Dichtstbijzijnde supermarkten:
  • Albert Heijn   0.3 km — Lorentzplein 76, Den Haag — lijst: €520.06
  • Jumbo          1.0 km — Laakweg 126, Den Haag — lijst: €162.62
  • Lidl           2.0 km — Wesselsstraat 500, Den Haag — geen prijsdata beschikbaar
  • Hoogvliet      1.1 km — Hendrik Ravesteijnplein 40, Rijswijk — geen prijsdata beschikbaar

🏆 Goedkoopste: Jumbo (1.0 km) — bespaart €357.44
📏 Dichtstbijzijnde: Albert Heijn op 0.3 km
