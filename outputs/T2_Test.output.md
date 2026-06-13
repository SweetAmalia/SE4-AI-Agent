Jij: Ik woon op de promotor 4 nootdorp. Dit wil ik hebben:  1 zak appels, 1 tros bananen, 500g broccoli, 1 bakje cherrytomaatjes, 3 paprika's, 300g verse spinazie, 1 netje uien, 10 eieren, 1 liter halfvolle melk, 1 bakje hummus, 500g kwark, 200g kaas, 1 heel brood, 1 pak koffie, 1 doos thee, 500g pasta, 1 pot pastasaus, 500g rijst, 1 pak rijstwafels, 300g kipfilet, 2 stuks vis, 1 fles afwasmiddel, 1 pak toiletpapier
2026-06-11 16:09:38.578 | INFO     | __main__:node_parse_input:336 - Node 1 — intent extractie

📋 Dit heb ik begrepen:
   • 1x appel
   • 1x banaan
   • 500 gram broccoli
   • 1x cherrytomaatjes
   • 3x paprika
   • 300 gram spinazie
   • 1x ui
   • 10x ei
   • 1 liter halfvolle melk
   • 1x hummus
   • 500 gram kwark
   • 200 gram kaas
   • 1x brood
   • 1x koffie
   • 1x thee
   • 500 gram pasta
   • 1x pastasaus
   • 500 gram rijst
   • 1x rijstwafels
   • 300 gram kipfilet
   • 2x vis
   • 1x afwasmiddel
   • 1x toiletpapier

2026-06-11 16:10:43.917 | SUCCESS  | __main__:node_parse_input:380 - Extractie OK: locatie=None, items=['1x appel', '1x banaan', '500 gram broccoli', '1x cherrytomaatjes', '3x paprika', '300 gram spinazie', '1x ui', '10x ei', '1 liter halfvolle melk', '1x hummus', '500 gram kwark', '200 gram kaas', '1x brood', '1x koffie', '1x thee', '500 gram pasta', '1x pastasaus', '500 gram rijst', '1x rijstwafels', '300 gram kipfilet', '2x vis', '1x afwasmiddel', '1x toiletpapier']
2026-06-11 16:10:43.918 | INFO     | __main__:node_locatie:408 - Node 2 — automatische locatiebepaling (Geolocation API)
2026-06-11 16:10:44.020 | SUCCESS  | __main__:node_locatie:420 - Locatie (automatisch): Linnaeusstraat 14, 2522 GS Den Haag, Netherlands
2026-06-11 16:10:44.021 | INFO     | __main__:node_winkels:434 - Node 3 — dichtstbijzijnde supermarkten zoeken
2026-06-11 16:10:44.494 | SUCCESS  | __main__:node_winkels:443 - Albert Heijn: AH Lorentzplein op 0.3 km (Lorentzplein 76, Den Haag)
2026-06-11 16:10:44.494 | SUCCESS  | __main__:node_winkels:443 - Jumbo: Jumbo op 1.0 km (Laakweg 126, Den Haag)
2026-06-11 16:10:44.494 | SUCCESS  | __main__:node_winkels:443 - Lidl: Lidl op 2.0 km (Wesselsstraat 500, Den Haag)
2026-06-11 16:10:44.494 | SUCCESS  | __main__:node_winkels:443 - Hoogvliet: Hoogvliet op 1.1 km (Hendrik Ravesteijnplein 40, Rijswijk)
2026-06-11 16:10:44.494 | INFO     | __main__:node_vergelijk_prijzen:455 - Node 4 — prijzen vergelijken (AH + Jumbo)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Kanzi Appel 1 kg' → €3.59
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x appel: AH €3.49 (✓) | Jumbo €3.59 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Banaan Schuim Zoet & Zacht 250 g' → €1.79
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x banaan: AH €4.99 (✓) | Jumbo €1.79 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Broccoli 500 g' → €1.29
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 500 gram broccoli: AH €2.79 (✓) | Jumbo €1.29 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Cherry Tomaten 400 g' → €3.99
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x cherrytomaatjes: AH €1.09 (✓) | Jumbo €3.99 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Paprika Mix 3 Stuks' → €1.95
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 3x paprika: AH €2.97 (✓) | Jumbo €5.85 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Gewassen Spinazie 600 g' → €2.99
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 300 gram spinazie: AH €1.69 (✓) | Jumbo €2.99 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Uien 1 kg' → €0.92
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x ui: AH €0.89 (✓) | Jumbo €0.92 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Powerful Eggs Nederlandse Witte Scharreleieren 30 Stuks' → €9.25
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 10x ei: AH €19.90 (✓) | Jumbo €92.50 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Halfvolle Melk 2 L' → €1.69
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1 liter halfvolle melk: AH €5.39 (✓) | Jumbo €1.69 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Hummus Naturel 200 g' → €2.59
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x hummus: AH €1.29 (✓) | Jumbo €2.59 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Optimel Magere Kwark met Magere Yoghurt Stracciatella Smaak 0% Vet 500g' → €2.39
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 500 gram kwark: AH €2.39 (✓) | Jumbo €2.39 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Boursin Roomkaas Knoflook & Fijne Kruiden 125 g' → €3.79
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 200 gram kaas: AH €3.09 (✓) | Jumbo €3.79 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Waldkorn - Volkoren Meergranenbrood' → €2.49
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x brood: AH €3.29 (✓) | Jumbo €2.49 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Melitta CaféBar Selection Espresso Classic Filterkoffie 250g' → €4.99
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x koffie: AH €37.96 (✓) | Jumbo €4.99 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Vruchtenthee Variatie Mix 20 Stuks' → €1.59
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x thee: AH €2.39 (✓) | Jumbo €1.59 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'HAK Easy Eats! Pasta Pomodoro 400g' → €3.49
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 500 gram pasta: AH €6.59 (✓) | Jumbo €3.49 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo's Tradizionale Pastasaus 500 g' → €2.99
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x pastasaus: AH €1.55 (✓) | Jumbo €2.99 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Lassie Toverrijst Voordeelpak 750 g' → €2.12
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 500 gram rijst: AH €2.39 (✓) | Jumbo €2.12 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Snack A Jacks Smooth Caramel Rijstwafels 140 gr' → €2.69
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x rijstwafels: AH €1.19 (✓) | Jumbo €2.69 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Jumbo Kipfilet ca. 600g' → €8.28
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 300 gram kipfilet: AH €12.80 (✓) | Jumbo €8.28 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Iglo Vissticks 15 stuks 15 x 28 g' → €4.69
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 2x vis: AH €9.98 (✓) | Jumbo €9.38 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Dreft Platinum Quickwash Original Vloeibaar Afwasmiddel 520ml' → €4.39
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x afwasmiddel: AH €2.99 (✓) | Jumbo €4.39 (✓)
2026-06-11 16:10:45.511 | DEBUG    | __main__:_safe_jumbo_price:281 - Jumbo match 'Edet Toiletpapier Simply Soft 24 Stuks' → €16.99
2026-06-11 16:10:45.511 | DEBUG    | __main__:node_vergelijk_prijzen:488 - 1x toiletpapier: AH €5.89 (✓) | Jumbo €16.99 (✓)

📍 Locatie (automatisch bepaald): Linnaeusstraat 14, 2522 GS Den Haag, Netherlands

💶 Prijsvergelijking (AH vs Jumbo):
  • 1x appel                     AH    €3.49  |  Jumbo    €3.59
  • 1x banaan                    AH    €4.99  |  Jumbo    €1.79
  • 500 gram broccoli            AH    €2.79  |  Jumbo    €1.29  (prijs per verpakking)
  • 1x cherrytomaatjes           AH    €1.09  |  Jumbo    €3.99
  • 3x paprika                   AH    €2.97  |  Jumbo    €5.85
  • 300 gram spinazie            AH    €1.69  |  Jumbo    €2.99  (prijs per verpakking)
  • 1x ui                        AH    €0.89  |  Jumbo    €0.92
  • 10x ei                       AH   €19.90  |  Jumbo   €92.50
  • 1 liter halfvolle melk       AH    €5.39  |  Jumbo    €1.69  (prijs per verpakking)
  • 1x hummus                    AH    €1.29  |  Jumbo    €2.59
  • 500 gram kwark               AH    €2.39  |  Jumbo    €2.39  (prijs per verpakking)
  • 200 gram kaas                AH    €3.09  |  Jumbo    €3.79  (prijs per verpakking)
  • 1x brood                     AH    €3.29  |  Jumbo    €2.49
  • 1x koffie                    AH   €37.96  |  Jumbo    €4.99
  • 1x thee                      AH    €2.39  |  Jumbo    €1.59
  • 500 gram pasta               AH    €6.59  |  Jumbo    €3.49  (prijs per verpakking)
  • 1x pastasaus                 AH    €1.55  |  Jumbo    €2.99
  • 500 gram rijst               AH    €2.39  |  Jumbo    €2.12  (prijs per verpakking)
  • 1x rijstwafels               AH    €1.19  |  Jumbo    €2.69
  • 300 gram kipfilet            AH   €12.80  |  Jumbo    €8.28  (prijs per verpakking)
  • 2x vis                       AH    €9.98  |  Jumbo    €9.38
  • 1x afwasmiddel               AH    €2.99  |  Jumbo    €4.39
  • 1x toiletpapier              AH    €5.89  |  Jumbo   €16.99
  Totaal: AH €136.99  |  Jumbo €182.78

🏪 Dichtstbijzijnde supermarkten:
  • Albert Heijn   0.3 km — Lorentzplein 76, Den Haag — lijst: €136.99
  • Jumbo          1.0 km — Laakweg 126, Den Haag — lijst: €182.78
  • Lidl           2.0 km — Wesselsstraat 500, Den Haag — geen prijsdata beschikbaar
  • Hoogvliet      1.1 km — Hendrik Ravesteijnplein 40, Rijswijk — geen prijsdata beschikbaar

🏆 Goedkoopste: Albert Heijn (0.3 km) — bespaart €45.79
📏 Dichtstbijzijnde: Albert Heijn op 0.3 km