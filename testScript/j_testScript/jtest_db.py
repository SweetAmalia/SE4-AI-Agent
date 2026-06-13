import chromadb
from testScript.j_testScript.jbuild_index import MijnLMStudioEmbedding, EIGEN_CHROMA_PAD, COLLECTIE_NAAM

def test_uitlezen():
    # Verbind met exact dezelfde map op schijf
    client = chromadb.PersistentClient(path=EIGEN_CHROMA_PAD)
    
    collectie = client.get_collection(
        name=COLLECTIE_NAAM,
        embedding_function=MijnLMStudioEmbedding()
    )
    
    print("\n--- STATUS CHECK ---")
    print(f"Aantal producten in jouw database: {collectie.count()}")
    
    # Doe een snelle query om te zien of het zoeken werkt
    res = collectie.query(
        query_texts=["Sensodyne whitening"],
        n_results=2,
        where={"winkel": "Albert Heijn"}
    )
    
    print("\n--- ZOEKRESULTAAT TEST ---")
    for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
        print(f"Gevonden: {doc} -> Prijs: €{meta['prijs']}")

if __name__ == "__main__":
    test_uitlezen()