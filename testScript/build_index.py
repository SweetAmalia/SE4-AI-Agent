"""
Bouwt de vector-index: scrapt AH + Jumbo op ~120 veelvoorkomende zoektermen,
embedt de producttitels via LM Studio en slaat alles op in ChromaDB.

Gebruik:
    py testScript/build_index.py            # volledige (her)indexering
    py testScript/build_index.py melk kaas  # alleen specifieke termen toevoegen

Vereisten:
    - LM Studio draait met een embedding-model geladen (zie vector_store.py)
    - Duurt enkele minuten: ~120 termen x 2 winkels, met throttling
"""

from __future__ import annotations

import hashlib
import sys
import time
from datetime import date

from loguru import logger

from winkel_clients import AHClient, jumbo_search_products, ah_prijs, jumbo_prijs
from vector_store import get_collectie

# Veelvoorkomende boodschappen — dekt het grootste deel van een normale lijst.
SEED_TERMEN = [
    # zuivel
    "melk", "halfvolle melk", "volle melk", "karnemelk", "yoghurt", "kwark",
    "vla", "slagroom", "creme fraiche", "boter", "margarine", "kaas",
    "geraspte kaas", "smeerkaas", "eieren", "sojamelk", "havermelk",
    # brood & beleg
    "brood", "volkorenbrood", "wit brood", "croissant", "beschuit", "crackers",
    "rijstwafels", "pindakaas", "hagelslag", "jam", "honing", "chocoladepasta",
    "vleeswaren", "ham", "salami", "kipfilet beleg",
    # vlees, vis & vega
    "gehakt", "kipfilet", "kippendij", "speklapjes", "hamburger", "braadworst",
    "rookworst", "spekblokjes", "zalm", "kabeljauw", "vissticks", "tonijn",
    "garnalen", "vegetarische balletjes", "vegaburger", "tofu", "falafel",
    # groente & fruit
    "banaan", "appel", "peer", "sinaasappel", "mandarijn", "druiven",
    "aardbeien", "blauwe bessen", "watermeloen", "tomaat", "komkommer",
    "paprika", "courgette", "aubergine", "broccoli", "bloemkool", "spinazie",
    "sla", "ui", "knoflook", "wortel", "champignons", "avocado", "citroen",
    "aardappelen", "zoete aardappel",
    # pasta, rijst & wereldkeuken
    "pasta", "spaghetti", "penne", "macaroni", "lasagnebladen", "rijst",
    "zilvervliesrijst", "couscous", "quinoa", "noedels", "wraps",
    "tortilla", "pastasaus", "tomatenblokjes", "tomatenpuree", "kokosmelk",
    "currypasta", "sojasaus", "sambal",
    # soepen, conserven & voorraad
    "soep", "tomatensoep", "kippensoep", "bouillonblokjes", "mais",
    "kidneybonen", "kikkererwten", "linzen", "appelmoes", "olijven",
    # ontbijt & tussendoor
    "muesli", "cornflakes", "havermout", "ontbijtkoek", "mueslireep",
    "chips", "nootjes", "pinda", "studentenhaver", "chocolade", "koekjes",
    "stroopwafels", "snoep", "drop", "ijs",
    # dranken
    "koffie", "filterkoffie", "koffiebonen", "thee", "groene thee",
    "frisdrank", "cola", "sinas", "spa", "bruiswater", "appelsap",
    "sinaasappelsap", "energy drink", "red bull", "bier", "wijn",
    # bakken & kruiden
    "bloem", "suiker", "vanillesuiker", "bakpoeder", "olijfolie",
    "zonnebloemolie", "azijn", "mayonaise", "ketchup", "mosterd", "curry",
    "paprikapoeder", "peper", "zout",
    # huishouden & verzorging
    "wasmiddel", "wasverzachter", "afwasmiddel", "vaatwastabletten",
    "allesreiniger", "wc papier", "keukenpapier", "tandpasta", "shampoo",
    "douchegel", "deodorant", "luiers",
]

PAUZE_TUSSEN_TERMEN = 0.3  # seconden; niet de APIs hameren


def _product_id(winkel: str, titel: str) -> str:
    return f"{winkel}:{hashlib.sha1(titel.lower().encode()).hexdigest()[:16]}"


def indexeer(termen: list[str]) -> None:
    ah = AHClient()
    collectie = get_collectie()
    vandaag = date.today().isoformat()

    # Verzamel uniek per (winkel, titel); laatste prijs wint
    producten: dict[str, dict] = {}

    for i, term in enumerate(termen, 1):
        logger.info(f"[{i}/{len(termen)}] '{term}'")

        try:
            for p in ah.search_products(term, size=30):
                titel = p.get("title")
                prijs = ah_prijs(p)
                if titel and prijs:
                    producten[_product_id("Albert Heijn", titel)] = {
                        "titel": titel, "winkel": "Albert Heijn", "prijs": prijs,
                    }
        except Exception as e:
            logger.warning(f"AH faalde voor '{term}': {e}")

        try:
            for p in jumbo_search_products(term):
                titel = p.get("title")
                prijs = jumbo_prijs(p)
                if titel and prijs:
                    producten[_product_id("Jumbo", titel)] = {
                        "titel": titel, "winkel": "Jumbo", "prijs": prijs,
                    }
        except Exception as e:
            logger.warning(f"Jumbo faalde voor '{term}': {e}")

        time.sleep(PAUZE_TUSSEN_TERMEN)

    logger.info(f"{len(producten)} unieke producten verzameld; embedden en opslaan...")

    ids = list(producten.keys())
    # In batches upserten: elke batch wordt door LM Studio geëmbed
    BATCH = 200
    for start in range(0, len(ids), BATCH):
        batch_ids = ids[start:start + BATCH]
        collectie.upsert(
            ids=batch_ids,
            documents=[producten[i]["titel"] for i in batch_ids],
            metadatas=[{
                "winkel": producten[i]["winkel"],
                "prijs": producten[i]["prijs"],
                "opgehaald_op": vandaag,
            } for i in batch_ids],
        )
        logger.info(f"  {min(start + BATCH, len(ids))}/{len(ids)} opgeslagen")

    per_winkel = {}
    for p in producten.values():
        per_winkel[p["winkel"]] = per_winkel.get(p["winkel"], 0) + 1
    logger.success(
        f"Klaar. Index bevat nu {collectie.count()} producten "
        f"(deze run: {per_winkel})"
    )


if __name__ == "__main__":
    eigen_termen = sys.argv[1:]
    indexeer(eigen_termen if eigen_termen else SEED_TERMEN)
