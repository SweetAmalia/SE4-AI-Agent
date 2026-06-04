# Sprint 2 – Toolonderzoek – Groep 7

**Project:** DiscountR – AI-agent voor goedkope boodschappen (Albert Heijn vs. Jumbo)
**Teamleden:** Ling-Hi Koc (21021317), Ties van den Berg (24130729), Jonathan Verkaik (24154490)
**Trello:** [Project-bord](https://trello.com/invite/b/6a16e35ce988d4538d79cbec/ATTI4ff8fbcdc209d7e1b6fc275eba21a3d76D3866FA/de-project-ai-agent)
**Datum:** Sprint 2, juni 2026

---

## 1. Onderzoeksvraag

> **Welke tools zijn het meest geschikt om onze DiscountR agent workflow te bouwen?**

Het doel is **niet** om de "beste" tools in het algemeen te vinden, maar om onderbouwd te bepalen welke tools het beste passen bij de DiscountR-workflow: een research-agent die op basis van een boodschappenlijstje en locatie de goedkoopste supermarkt (AH/Jumbo) in de buurt selecteert, inclusief route-advies.

---

## 2. Onderzoeksopzet

Het onderzoek volgt het achtstappenplan uit de opdracht. We combineren **Route A** (twee tools vergelijken via benchmark) met **Route B** (één tool experimenteel uitproberen) zoals het voorbeeld in de lesstof aanbeveelt.

| Stap | Activiteit | Deliverable |
|------|------------|-------------|
| 1 | Onderzoeksvraag vaststellen | ✅ Klaar |
| 2 | Onderzoeksopzet schrijven | ✅ Dit hoofdstuk |
| 3 | Requirements afleiden uit workflow | Requirementslijst (R1–R12) |
| 4 | Voorselectie tools via documentatieonderzoek | Shortlist van 3 frameworks + 3 API-tools |
| 5 | Onderzoeksvormen kiezen per tool | Benchmark (n8n vs LangGraph) + Experiment (PydanticAI) |
| 6 | Meetcriteria vaststellen | Meetbare criteria-tabel per onderzoeksvorm |
| 7 | Dataverzameling en vastlegging | Ingevulde testlogboeken per tool |
| 8 | Onderbouwde conclusie + toolkeuze | Tool(combinatie) met motivatie |

**Werkverdeling (voorlopig):**
- Ling-Hi: benchmark n8n
- Jonathan: benchmark LangGraph
- Ties: experiment PydanticAI + API-tools

**Bijstellen van het plan:** als tijdens stap 7 blijkt dat een criterium niet meetbaar is of dat een tool afvalt, mogen we de opzet bijstellen — dit wordt expliciet vastgelegd in het logboek.

---

## 3. Ontwerponderzoek: Requirements afleiden uit de workflow

### 3.1 Onze workflow (Sprint 1, samengevat)

De DiscountR-workflow bestaat uit **9 stappen**, elk met validatie, LLM-validatie en een herstelactie (loop):

| # | Stap | Input | Output | LLM | Tool/API |
|---|------|-------|--------|-----|----------|
| 1 | Gebruiker Input | Boodschappenlijst, locatie (optioneel) | Ruwe tekst | Ja | Nee |
| 2 | Locatie Bepalen | Locatie-aanwijzing uit stap 1 | Adres/coördinaten | Nee | Ja (Geocoding) |
| 3 | Boodschappen Lijst | Ruwe tekst uit stap 1 | Gestructureerde JSON | Ja | Nee |
| 4 | Winkels Zoeken | Coördinaten + max. straal | Lijst supermarkten op afstand | Nee | Ja (Maps API) |
| 5 | Prijzen Opzoeken | Lijsten uit stap 3+4 | Gevulde prijslijst per supermarkt | Optioneel | Ja (AH/Jumbo) |
| 6 | Vergelijking Supermarkt | Prijslijst uit stap 5 | Totaalsom + absoluut prijsverschil | Ja | Nee |
| 7 | Route Planning | Locatie + winkels + vervoermiddel | Reistijd & afstand per winkel | Nee | Ja (Routing API) |
| 8 | Supermarkt Advies | Prijsverschil + reistijden | Beslissingsmodel (meerkeuze) | Ja | Nee |
| 9 | Gebruiker Updaten | Beslissingsmodel | Knoppen locatie / online | Ja | Nee |

Elke stap kan bij een gefaalde validatie **terugloopen** naar een eerdere stap (loop) — bijvoorbeeld stap 5 die mislukt → terug naar stap 4 om een andere winkel te zoeken.

### 3.2 Afgeleide requirements

Op basis van de bovenstaande workflow leiden we de volgende requirements af voor het AI-framework dat we gaan kiezen:

#### Functionele requirements (must-have)

| ID | Requirement | Reden uit workflow |
|----|-------------|-------------------|
| **R1** | De tool moet **orchestration** van minimaal 9 sequentiële processtappen ondersteunen | Workflow stap 1–9 |
| **R2** | De tool moet **state** kunnen bewaren tussen stappen (boodschappenlijst, locatie, prijzen) | Output stap N is input stap N+1 |
| **R3** | De tool moet **loops/herhaling** ondersteunen bij gefaalde validatie | Herstelacties per stap |
| **R4** | De tool moet **externe HTTP/API-calls** kunnen uitvoeren | Geocoding, Maps, Routing, AH/Jumbo |
| **R5** | De tool moet **LLM-aanroepen** ondersteunen voor validatie van stap-output | LLM-validatie in 6/9 stappen |
| **R6** | De tool moet **conditionele branching** ondersteunen (if validatie faalt → herstel) | Validatie-rij in workflow |
| **R7** | De tool moet **gestructureerde output** (JSON) kunnen genereren en valideren | Stap 3, 5, 8 |

#### Niet-functionele requirements (should-have)

| ID | Requirement | Reden |
|----|-------------|-------|
| **R8** | **Leercurve** acceptabel binnen 1 sprint (≤ 2 weken) voor een 2e-jaars HBO-student | Studententeam, beperkte tijd |
| **R9** | **Kosten** € 0 voor ontwikkeling en demo (gratis tier of self-host) | Studentenbudget |
| **R10** | **Documentatie** in het Engels, met werkende voorbeelden | Standaard voor HBO-projecten |
| **R11** | **Actieve community** (≥ 1.000 GitHub stars OF officiële enterprise-support) | Risico op doodlopende tool minimaliseren |
| **R12** | **Demo-baarheid** — output moet getoond kunnen worden in een eenvoudige UI of API-response | Sprint-demo aan docent |

> **Conclusie ontwerponderzoek:** we zoeken een tool die orchestration + state + loops + API-calls + LLM-integratie in één framework biedt, betaalbaar is, en binnen één sprint te leren valt. Voor de externe data zoeken we daarnaast naar concrete API-tools/libraries voor geocoding, supermarktprijzen en routing.

---

## 4. Voorselectie tools (documentatieonderzoek)

### 4.1 Aanpak voorselectie

Op basis van de requirements hebben we via officiële documentatie, tutorials, GitHub-repo's en het lesvoorbeeld een longlist gemaakt en die teruggebracht tot **3 agent-frameworks** die op papier aan R1–R7 voldoen. Daarnaast selecteren we **3 externe API-tools** voor data die elk framework zal moeten kunnen aanroepen (R4).

### 4.2 Voorgeselecteerde agent-frameworks

#### A. n8n (visueel low-code platform)

| Aspect | Bevinding | Bron |
|--------|-----------|------|
| Type | Low-code, visuele workflow-builder | docs.n8n.io |
| Orchestration (R1) | ✅ Drag-and-drop nodes, native multi-step workflows | Officiële docs |
| State (R2) | ✅ Data flowt automatisch tussen nodes via JSON | Officiële docs |
| Loops (R3) | ✅ Loop-nodes + Wait-nodes + AI Agent met retries | Officiële docs |
| API-calls (R4) | ✅ 500+ integraties + generieke HTTP Request node | docs.n8n.io |
| LLM (R5) | ✅ AI Agent-node + LangChain-integratie | docs.n8n.io |
| Branching (R6) | ✅ IF/Switch-nodes | Officiële docs |
| Kosten (R9) | ✅ Self-host gratis (Fair-code license) | n8n.io/pricing |
| Leercurve (R8) | 🟢 Laag — visueel | Tutorials |

#### B. LangGraph (code-first stateful graphs)

| Aspect | Bevinding | Bron |
|--------|-----------|------|
| Type | Python/JS framework, code-first | langchain-ai.github.io/langgraph |
| Orchestration (R1) | ✅ Graph-based met nodes + edges | Officiële docs |
| State (R2) | ✅ Expliciete `StateGraph` met TypedDict + checkpointing | Officiële docs |
| Loops (R3) | ✅ Conditional edges kunnen terugverwijzen | Officiële docs |
| API-calls (R4) | ✅ Volledig Python — elke library bruikbaar | n.v.t. |
| LLM (R5) | ✅ Native LangChain-integratie (OpenAI, Anthropic, etc.) | Officiële docs |
| Branching (R6) | ✅ `add_conditional_edges()` | Officiële docs |
| Kosten (R9) | ✅ Gratis open source (MIT) | GitHub |
| Leercurve (R8) | 🟡 Middel — vereist Python + concept "graph" | Tutorials |

#### C. PydanticAI (Python type-safe agent framework)

| Aspect | Bevinding | Bron |
|--------|-----------|------|
| Type | Python framework, gebouwd door Pydantic-team | ai.pydantic.dev |
| Orchestration (R1) | ✅ Agents + optioneel `pydantic-graph` voor complexe flows | Officiële docs |
| State (R2) | ✅ Dependency injection + structured deps | Officiële docs |
| Loops (R3) | ✅ Ingebouwde retries op tool- en validatieniveau | Officiële docs |
| API-calls (R4) | ✅ `@agent.tool` decorator voor elke Python-functie | Officiële docs |
| LLM (R5) | ✅ Multi-model (OpenAI, Anthropic, Gemini, lokaal) | Officiële docs |
| Branching (R6) | ✅ Type-safe routing op model output | Officiële docs |
| Kosten (R9) | ✅ Gratis open source (MIT) | GitHub |
| Leercurve (R8) | 🟢 Laag-middel — vergelijkbaar met FastAPI | Tutorials |

#### Afgevallen (kort onderbouwd)

- **AutoGen / CrewAI** — sterk in multi-agent rollen, maar overkill voor onze lineaire pipeline; minder geschikt voor expliciete loop/state-control.
- **Zapier / Make** — minder ontwikkelaarsvriendelijk en betaald voor het volume API-calls dat wij nodig hebben.
- **Bare OpenAI Assistants API** — geen orchestration/state-management out-of-the-box; we zouden alle plumbing zelf moeten schrijven.

### 4.3 Voorgeselecteerde externe API-tools (voor R4)

Deze tools zijn nodig binnen het gekozen framework, ongeacht welk framework wint:

| API/Tool | Doel | Bron | Licentie |
|----------|------|------|----------|
| **OpenStreetMap Nominatim** OF **Google Geocoding API** | Stap 2: locatie → coördinaten | nominatim.org / Google | Gratis / freemium |
| **SupermarktConnector** (Python) | Stap 5: prijzen ophalen AH + Jumbo | [github.com/bartmachielsen/SupermarktConnector](https://github.com/bartmachielsen/SupermarktConnector) | MIT |
| **OpenRouteService** OF **Google Directions API** | Stap 7: route planning + reistijd | openrouteservice.org / Google | Gratis tier / freemium |

**Backup-opties voor stap 5:**
- [python-appie](https://github.com/tijnschouten/appie) — async AH-client met bonus-detectie
- [supermarkt/checkjebon](https://github.com/supermarkt/checkjebon) — multi-supermarkt (uitbreidbaar)

> ⚠️ **Risico:** SupermarktConnector gebruikt unofficial endpoints. Dit accepteren we als bekend risico voor een schoolproject; we leggen vast wanneer/hoe vaak het breekt tijdens testen.

---

## 5. Onderzoeksvormen kiezen per tool

We volgen het lesvoorbeeld en kiezen **twee onderzoeksvormen tegelijk**:

| Tool(s) | Onderzoeksvorm | Waarom deze vorm? |
|---------|----------------|-------------------|
| **n8n vs LangGraph** | **Benchmarkonderzoek** | We willen twee fundamenteel verschillende paradigma's (low-code visueel vs. code-first graphs) op dezelfde criteria scoren om te zien welke beter past bij ons team en de workflow. |
| **PydanticAI** | **Experimentonderzoek** | We zijn vooral nieuwsgierig óf het werkt voor onze specifieke validatie-zware workflow — een werkende mini-workflow geeft hier sneller antwoord dan een papieren vergelijking. |

Het **documentatieonderzoek** uit stap 4 telt als 0-meting; vanaf nu werken we per tool verder.

---

## 6. Meetcriteria vaststellen per onderzoeksvorm

### 6.1 Meetcriteria – Benchmark n8n vs LangGraph

Elke tool wordt op identieke criteria gescoord. Scoreschaal: **0 = werkt niet / 1 = werkt met workaround / 2 = werkt out-of-the-box**. Tijden zijn harde meetwaarden.

| # | Criterium (specifiek, meetbaar, controleerbaar) | Gerelateerd aan |
|---|------------------------------------------------|-----------------|
| **MC-1** | Installatie & "hello world" werkend lokaal binnen **60 minuten** (ja/nee + werkelijke tijd) | R8 |
| **MC-2** | Een workflow met **minimaal 5 sequentiële stappen** is te bouwen (ja/nee) | R1 |
| **MC-3** | State (een variabele) is **aantoonbaar bewaard** tussen stap 1 en stap 5 (ja/nee + screenshot) | R2 |
| **MC-4** | Er is **minimaal 1 loop** in te bouwen die terugkeert bij gefaalde validatie (ja/nee) | R3 |
| **MC-5** | Een **externe HTTP-call naar SupermarktConnector** levert prijsdata op (ja/nee + responsetijd) | R4 |
| **MC-6** | Een **LLM-call** (OpenAI/Claude) is binnen het framework aanroepbaar (ja/nee) | R5 |
| **MC-7** | Een **conditionele branche** (validatie geslaagd → door, gefaald → loop) werkt (ja/nee) | R6 |
| **MC-8** | Output is als **gestructureerde JSON** beschikbaar voor de volgende stap (ja/nee) | R7 |
| **MC-9** | Kosten voor onze gebruikstest **€ 0** (ja/nee) | R9 |
| **MC-10** | Documentatie-kwaliteit op schaal **0–5** (subjectief, met motivatie van minimaal 1 zin) | R10 |
| **MC-11** | Aantal **GitHub-sterren** & datum laatste commit (hard getal) | R11 |
| **MC-12** | Tijd om **complete 9-stappen DiscountR-workflow** als prototype op te zetten (uren-schatting na 1 dag werken) | R12 |

### 6.2 Meetcriteria – Experiment PydanticAI

Voor het experiment bouwen we een **mini-workflow van 3 stappen** die een echt stuk DiscountR-functionaliteit nabouwt:
- **Stap A:** parse boodschappenlijst (ruwe tekst → JSON via LLM)
- **Stap B:** roep SupermarktConnector aan voor 1 product (tool-call)
- **Stap C:** valideer output en retry bij fout

| # | Criterium | Slagingseis |
|---|-----------|-------------|
| **MX-1** | Mini-workflow van **3 stappen** komt succesvol ten einde | Volledige run zonder crash |
| **MX-2** | LLM produceert **gevalideerde Pydantic-output** (geen losse strings) | Type-check slaagt |
| **MX-3** | Externe **tool-call (`@agent.tool`)** naar SupermarktConnector werkt | Prijsdata in response |
| **MX-4** | **Retry/fallback** treedt aantoonbaar in werking bij geforceerde fout | Log toont retry-poging |
| **MX-5** | Totale **looptijd ≤ 30 sec** voor 1 product (acceptabele UX) | Stopwatch-meting |
| **MX-6** | Code is **leesbaar voor teamgenoten** zonder PydanticAI-ervaring (peer-review 1–5) | ≥ 3 / 5 |

---

## 7. Dataverzameling en vastlegging

### 7.1 Bronnen die we raadplegen

- Officiële documentatie: [docs.n8n.io](https://docs.n8n.io), [langchain-ai.github.io/langgraph](https://langchain-ai.github.io/langgraph), [ai.pydantic.dev](https://ai.pydantic.dev)
- GitHub-repo's (sterren, issues, laatste commit)
- Tutorials (YouTube, Medium, dev.to) — voor leercurve-impressie
- Onze eigen test-resultaten (screenshots, code, log-output)

### 7.2 Logboek-template benchmark (per tool in te vullen tijdens stap 8)

#### n8n – ingevuld door: _[naam]_  | datum: _[dd-mm-jjjj]_

| MC | Resultaat | Bewijs (link/screenshot/code) | Opmerking |
|----|-----------|-------------------------------|-----------|
| MC-1 | ⬜ | | |
| MC-2 | ⬜ | | |
| MC-3 | ⬜ | | |
| MC-4 | ⬜ | | |
| MC-5 | ⬜ | | |
| MC-6 | ⬜ | | |
| MC-7 | ⬜ | | |
| MC-8 | ⬜ | | |
| MC-9 | ⬜ | | |
| MC-10 | ⬜ | | |
| MC-11 | ⬜ | | |
| MC-12 | ⬜ | | |

#### LangGraph – ingevuld door: _[naam]_  | datum: _[dd-mm-jjjj]_

| MC | Resultaat | Bewijs (link/screenshot/code) | Opmerking |
|----|-----------|-------------------------------|-----------|
| MC-1 | ⬜ | | |
| MC-2 | ⬜ | | |
| MC-3 | ⬜ | | |
| MC-4 | ⬜ | | |
| MC-5 | ⬜ | | |
| MC-6 | ⬜ | | |
| MC-7 | ⬜ | | |
| MC-8 | ⬜ | | |
| MC-9 | ⬜ | | |
| MC-10 | ⬜ | | |
| MC-11 | ⬜ | | |
| MC-12 | ⬜ | | |

### 7.3 Logboek-template experiment PydanticAI

| MX | Resultaat | Bewijs | Opmerking |
|----|-----------|--------|-----------|
| MX-1 | ⬜ | | |
| MX-2 | ⬜ | | |
| MX-3 | ⬜ | | |
| MX-4 | ⬜ | | |
| MX-5 | ⬜ | | |
| MX-6 | ⬜ | | |

### 7.4 Aanvullende observaties

Tijdens het testen leggen we ook vast:
- **Onverwachte issues** (bv. rate-limits, breaking changes)
- **Tijdsinvestering per teamlid** (in uren)
- **Persoonlijke voorkeur** met motivatie (niet doorslaggevend, wél informatief voor R8/R12)

---

## 8. Conclusie en onderbouwde toolkeuze

> ⚠️ **Dit hoofdstuk wordt definitief ingevuld ná het uitvoeren van stap 7 (benchmark + experiment).**
> Hieronder staat het sjabloon dat we gaan invullen, zodat de structuur conform de opdracht ("Conclusie = keuze + onderbouwing + bewijs") al klaarstaat.

### 8.1 Toolkeuze

**Gekozen agent-framework:** _[in te vullen]_
**Gekozen externe API-tools:** _[in te vullen — verwachting: SupermarktConnector + Nominatim + OpenRouteService]_

### 8.2 Onderbouwing

Waarom past deze tool(combinatie) bij onze DiscountR-workflow?
- _Argument 1 — past bij requirements R1–R7_
- _Argument 2 — leercurve & teamcompetenties_
- _Argument 3 — kosten en duurzaamheid_

### 8.3 Bewijs

| Bron | Wat het aantoont |
|------|------------------|
| Benchmark-logboek (§7.2) | _[verwijzing]_ |
| Experimentlogboek (§7.3) | _[verwijzing]_ |
| Officiële documentatie | _[link]_ |
| Werkende prototype-code | _[GitHub-link of Trello-card]_ |

### 8.4 Score per meetcriterium (samenvatting)

| Criterium | n8n | LangGraph | PydanticAI |
|-----------|-----|-----------|------------|
| MC-1 t/m MC-12 | _[in te vullen]_ | _[in te vullen]_ | n.v.t. (experiment) |
| MX-1 t/m MX-6 | n.v.t. | n.v.t. | _[in te vullen]_ |

### 8.5 Wat betekent dit voor het bouwen van de agent (Sprint 3+)

- Architectuur-impact: _[bv. "We bouwen elke workflow-stap als een LangGraph-node met een centrale `DiscountRState` TypedDict"]_
- Skills die we moeten opbouwen: _[bv. "Python async, LangGraph state, OpenAI function calling"]_
- Risico's: _[bv. "SupermarktConnector kan breken bij API-wijziging AH — fallback inbouwen"]_
- Volgende stap: _[bv. "Sprint 3 = werkend prototype stappen 1–5"]_

---

## Bijlagen

### A. Verwijzing naar workflow-diagram
Zie Sprint 1-document, p.4: "Boodschappenlijst Workflow — Validatie, Herstel & Loops"

### B. Relevante GitHub-repo's voor supermarktprijzen

| Repo | ⭐ | Doel | Status |
|------|----|----|--------|
| [bartmachielsen/SupermarktConnector](https://github.com/bartmachielsen/SupermarktConnector) | 150 | AH + Jumbo, Python | **Eerste keuze** |
| [tijnschouten/appie](https://github.com/tijnschouten/appie) | actief | Async AH-client | Backup AH |
| [supermarkt/checkjebon](https://github.com/supermarkt/checkjebon) | 231 | Multi-supermarkt JS | Uitbreiding later |
| [mrserzhan/ah-mcp](https://github.com/mrserzhan/ah-mcp) | 12 | MCP-server AH | Interessant bij MCP-route |

### C. Definities

- **Orchestration:** het aansturen van de volgorde van workflow-stappen
- **State:** informatie die meegegeven wordt tussen stappen
- **Loop:** terugkeren naar een eerdere stap bij gefaalde validatie
- **Tool/API:** externe functie die de agent kan aanroepen
- **LLM-validatie:** een Large Language Model dat controleert of de output van een stap zinvol is

---

*Document-status: stappen 1–6 voltooid, stappen 7–8 worden ingevuld tijdens deze sprint.*
