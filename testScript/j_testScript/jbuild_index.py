import os
import re
from datetime import datetime
import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from openai import OpenAI
from loguru import logger
from dotenv import load_dotenv
import time
import uuid
from winkel_clients import AHClient, jumbo_search_products, ah_prijs, jumbo_prijs, lidl_search_products, normaliseer_api_resultaat

# Pas het pad naar je eigen .env aan indien nodig
load_dotenv(".env.local")

ah_client = AHClient()

# 1. CONFIGURATIE VIA ENV
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_EMBED_MODEL = os.getenv("LM_STUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")

# We kiezen een eigen, gloednieuwe mapnaam om conflicten te vermijden!
EIGEN_CHROMA_PAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jchroma_db")
COLLECTIE_NAAM = "producten"

# 2. STANDALONE EMBEDDING KLASSE
class MijnLMStudioEmbedding(EmbeddingFunction):
    """Zelfstandige embedding-functie gekoppeld aan LM Studio."""
    def __init__(self, base_url: str = LM_STUDIO_BASE_URL, model: str = LM_STUDIO_EMBED_MODEL):
        self._client = OpenAI(base_url=base_url, api_key="lm-studio")
        self._model = model
        logger.info(f"Embedding-model geïnitialiseerd: {self._model} via {base_url}")

    def __call__(self, input: Documents) -> Embeddings:
        embeddings: Embeddings = []
        for i in range(0, len(input), 256):
            batch = list(input[i:i + 256])
            res = self._client.embeddings.create(model=self._model, input=batch)
            embeddings.extend([d.embedding for d in res.data])
        return embeddings

# 3. RAUWE DATA UIT JOUW LOGS
# def haal_producten_lijst() -> list[dict]:
#     return [
#         {"id": "ah:274b7010fd4dcea8", "winkel": "Albert Heijn", "naam": "Sensodyne Repair & protect tandpasta", "prijs": 7.99},
#         {"id": "ah:60ca93bd1b9b9162", "winkel": "Albert Heijn", "naam": "Sensodyne MultiCare tandpasta", "prijs": 5.89},
#         {"id": "ah:c309ec02bbc62d3b", "winkel": "Albert Heijn", "naam": "Aquafresh Tandsteen controle tandpasta", "prijs": 2.59},
#         {"id": "ah:1411e11b9570a1f2", "winkel": "Albert Heijn", "naam": "Prodent Menthol power tandpasta", "prijs": 2.75},
#         {"id": "ah:3a2fda55b48d9d52", "winkel": "Albert Heijn", "naam": "Sensodyne Repair & protect whitening tandpasta", "prijs": 7.99},
#         {"id": "ah:767c16b861aeb659", "winkel": "Albert Heijn", "naam": "Oral-B Pro-expert bescherming tandpasta", "prijs": 4.89},
#         {"id": "ah:5f344477aa94ae84", "winkel": "Albert Heijn", "naam": "Parodontax Whitening tandpasta", "prijs": 5.99},
#         {"id": "ah:d0c59ace0051365e", "winkel": "Albert Heijn", "naam": "Oral-B 3D white artic fresh tandpasta", "prijs": 4.69},
#         {"id": "ah:e27ec540c6f74566", "winkel": "Albert Heijn", "naam": "Sensodyne Proglasur daily protection tandpasta", "prijs": 6.29},
#         {"id": "ah:c7848e144ad25f7b", "winkel": "Albert Heijn", "naam": "Sensodyne Extra fresh gel tandpasta", "prijs": 5.79},
#         {"id": "ah:30671bd3dd889b11", "winkel": "Albert Heijn", "naam": "Sensodyne Repair & protect whitening tandpasta 6pk", "prijs": 38.35},
#         {"id": "jumbo:e12ff98d81869184", "winkel": "Jumbo", "naam": "Aquafresh White & Shine Tandpasta 5 Stuks", "prijs": 9.99},
#         {"id": "jumbo:7d6cc887404cc725", "winkel": "Jumbo", "naam": "Prodent Tandpasta Cool Mint 75 ml", "prijs": 1.85},
#         {"id": "jumbo:af32c9a0ad493804", "winkel": "Jumbo", "naam": "Sensodyne Deep Clean Gel 75 ml Tube", "prijs": 5.79},
#         {"id": "jumbo:f64831b76bdb07a5", "winkel": "Jumbo", "naam": "Sensodyne Multicare tandpasta voor gevoelige tanden 2x75ML", "prijs": 11.65},
#         {"id": "jumbo:7eba2aee5e10d451", "winkel": "Jumbo", "naam": "Colgate Blue Fresh Gel Tandpasta Voordeelverpakking 4 x 75 ml", "prijs": 7.69},
#         {"id": "jumbo:6a5138a4b9e61199", "winkel": "Jumbo", "naam": "Parodontax Fluoride Tandpasta 75 ML", "prijs": 5.79},
#         {"id": "jumbo:eb2ae1db1acdd0de", "winkel": "Jumbo", "naam": "Aquafresh Fresh & Mint / Aquafresh Fresh & Minty Tandpasta 125ML", "prijs": 2.99},
#         {"id": "jumbo:985c583762913f1e", "winkel": "Jumbo", "naam": "Prodent Tandpasta Wit + Fris 75 ml", "prijs": 3.59},
#         {"id": "jumbo:ad4ab94ff842cae6", "winkel": "Jumbo", "naam": "Aquafresh Fresh & Minty 3-In-1 Tandpasta 75 ML", "prijs": 2.39},
#         {"id": "jumbo:9f958c44b9b8e4f7", "winkel": "Jumbo", "naam": "Zendium Tandpasta Classic 75 ml", "prijs": 4.99},
#         {"id": "jumbo:dea25c8f404e3699", "winkel": "Jumbo", "naam": "Aquafresh White & Shine Tandpasta 75 ML", "prijs": 3.99},
#         {"id": "jumbo:bc46c4536d6935bc", "winkel": "Jumbo", "naam": "Oral-B Arctic Fresh Tandpasta 75 ml", "prijs": 4.69},
#         {"id": "jumbo:df4d0f07cea069c2", "winkel": "Jumbo", "naam": "Zendium Tandpasta Fresh+White 75 ml", "prijs": 4.99},
#         {"id": "jumbo:7c9d9577a52d38d9", "winkel": "Jumbo", "naam": "Prodent Tandpasta Frisse Adem 75 ml", "prijs": 3.59},
#         {"id": "jumbo:ff9eb59350eadc33", "winkel": "Jumbo", "naam": "Prodent Tandpasta Complete Bescherming 75 ml", "prijs": 3.59}
#     ]

# def haal_bulk_producten_lijst() -> list[dict]:
#     """
#     Scrapt live honderden producten op basis van veelvoorkomende zoektermen
#     om de vector database structureel te vullen.
#     """
#     # Breid deze lijst uit met alles wat je erin wilt hebben!
#     zoektermen = [
#         "tandpasta", "citroen", "limoen", "appel", "biefstuk", "jalapeno", "boter",
#         "red bull", "energy", "melk", "kaas", "brood", "kipfilet", "gehakt", 
#         "bananen", "eieren", "yoghurt", "cola", "chips", "rijst", "pasta"
#     ]
    
#     gecollecteerde_producten = []
#     logger.info(f"Start bulk-scoping voor {len(zoektermen)} categorieën...")

#     for term in zoektermen:
#         logger.debug(f"Live data ophalen voor zoekterm: '{term}'")
        
#         # --- 1. ALBERT HEIJN LIVE BINNENHALEN ---
#         try:
#             ah_ruw = ah_client.search_products(term, size=25) # 25 producten per term
#             for p in ah_ruw:
#                 if p.get("title") and ah_prijs(p):
#                     gecollecteerde_producten.append({
#                         "id": f"ah:{p.get('webshopId', uuid.uuid4().hex)}",
#                         "winkel": "Albert Heijn",
#                         "naam": p["title"],
#                         "prijs": float(ah_prijs(p))
#                     })
#         except Exception as e:
#             logger.warning(f"AH bulk voor '{term}' mislukt: {e}")

#         # --- 2. JUMBO LIVE BINNENHALEN ---
#         try:
#             jumbo_ruw = jumbo_search_products(term)[:25]
#             for p in jumbo_ruw:
#                 if p.get("title") and jumbo_prijs(p):
#                     gecollecteerde_producten.append({
#                         "id": f"jumbo:{p.get('id', uuid.uuid4().hex)}",
#                         "winkel": "Jumbo",
#                         "naam": p["title"],
#                         "prijs": float(jumbo_prijs(p))
#                     })
#         except Exception as e:
#             logger.warning(f"Jumbo bulk voor '{term}' mislukt: {e}")
            
#         time.sleep(0.5) # Netjes blijven tegenover de API's

#     return gecollecteerde_producten

def haal_bulk_producten_lijst() -> list[dict]:
    zoektermen = ["tandpasta", "citroen", "limoen", "appel", "biefstuk", "red bull"]
    gecollecteerde_producten = []

    for term in zoektermen:
        # --- 1. ALBERT HEIJN ---
        for p in ah_client.search_products(term, size=25):
            norm = normaliseer_api_resultaat(p, "Albert Heijn")
            if norm: gecollecteerde_producten.append(norm)

        # --- 2. JUMBO ---
        for p in jumbo_search_products(term)[:25]:
            norm = normaliseer_api_resultaat(p, "Jumbo")
            if norm: gecollecteerde_producten.append(norm)

        for p in lidl_search_products(term, size=25):
            norm = normaliseer_api_resultaat(p, "Lidl")
            if norm: gecollecteerde_producten.append(norm)
            
    return gecollecteerde_producten

def parse_aantal_stuks(naam: str) -> int:
    naam_lower = naam.lower()
    match_pk = re.search(r'(\d+)\s*pk', naam_lower)
    match_stuks = re.search(r'(\d+)\s*stuks', naam_lower)
    match_x = re.search(r'(\d+)\s*x\s*\d+', naam_lower)
    
    if match_pk: return int(match_pk.group(1))
    if match_stuks: return int(match_stuks.group(1))
    if match_x: return int(match_x.group(1))
    return 1

# 4. HOOFDFUNCTIE VOOR HET VULLEN
def bouw_mijn_database():
    logger.info(f"Initialiseren van eigen harde schijf database in: {EIGEN_CHROMA_PAD}")
    
    # PersistentClient dwingt Chroma om naar de schijf te schrijven
    chroma_client = chromadb.PersistentClient(path=EIGEN_CHROMA_PAD)
    embedding_functie = MijnLMStudioEmbedding()
    
    collectie = chroma_client.get_or_create_collection(
        name=COLLECTIE_NAAM,
        embedding_function=embedding_functie,
        metadata={"hnsw:space": "cosine"}
    )
    
    # Opschonen indien er al oude data in de eigen DB stond
    if collectie.count() > 0:
        logger.info(f"Eigen DB bevat al {collectie.count()} producten. Leegmaken voor schone lei...")
        oude_data = collectie.get()
        collectie.delete(ids=oude_data["ids"])
    
    rauwe_producten = haal_bulk_producten_lijst()
    
    # OVERLAPPING ERUIT FILTEREN: We gebruiken een dict met ID als key om duplicaten te tackelen
    unieke_producten_dict = {}
    for prod in rauwe_producten:
        unieke_producten_dict[prod["id"]] = prod
        
    producten = list(unieke_producten_dict.values())
    logger.info(f"Na ontdubbeling zijn er {len(producten)} unieke producten overgebleven van de {len(rauwe_producten)}.")
    
    documents: list[str] = []
    metadatas: list[dict] = []
    ids: list[str] = []
    vandaag_str = datetime.now().strftime("%Y-%m-%d")
    
    for prod in producten:
        aantal = parse_aantal_stuks(prod["naam"])
        
        doc_text = f"Winkel: {prod['winkel']} | Product: {prod['naam']} | Categorie: Supermarkt Artikelen"
        metadata = {
            "winkel": prod["winkel"],
            "prijs": float(prod["prijs"]),
            "opgehaald_op": vandaag_str,
            "aantal_in_verpakking": aantal,
            "is_multipack": "ja" if aantal > 1 else "nee"
        }
        
        documents.append(doc_text)
        metadatas.append(metadata)
        ids.append(prod["id"])
        
    logger.info(f"Pushen van {len(documents)} unieke producten naar eigen ChromaDB...")
    
    # VEILIGE BATCH LOOP MET UPSERT
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_docs = documents[i : i + batch_size]
        batch_metas = metadatas[i : i + batch_size]
        
        # .upsert() in plaats van .add() vangt eventuele overgebleven gekke ID-mismatches op
        collectie.upsert(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas
        )
        logger.debug(f"Batch verwerkt: items {i} tot {i + len(batch_docs)}")

    logger.success(f"✅ Gelukt! Database succesvol gevuld en gesyncbed met {collectie.count()} unieke producten.")

if __name__ == "__main__":
    bouw_mijn_database()