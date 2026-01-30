import time
import torch
import os
from sentence_transformers import SentenceTransformer, CrossEncoder

# Пути из твоего конфига
EMBED_MODEL_PATH = os.path.expanduser("~/models/embeddings/bge-m3")
RERANK_MODEL_PATH = os.path.expanduser("~/models/rerankers/bge-reranker-v2-m3")

def benchmark_rag():
    print("🚀 Начинаем профилирование RAG пайплайна...")
    
    test_query = "Какие планы по развитию системы Анимара?"
    # Имитируем 10 кусков текста, найденных в Milvus
    test_chunks = [f"Фрагмент текста {i}: проект Animara развивается в Убуде." for i in range(10)]

    # 1. Загрузка моделей (замеряем, сколько они занимают в памяти)
    print("⏳ Загрузка моделей в память...")
    start_load = time.perf_counter()
    model = SentenceTransformer(EMBED_MODEL_PATH)
    reranker = CrossEncoder(RERANK_MODEL_PATH)
    print(f"✅ Модели загружены за {time.perf_counter() - start_load:.2f} сек")

    # 2. Замер Embedding
    start_emb = time.perf_counter()
    query_vector = model.encode(test_query)
    end_emb = time.perf_counter()
    print(f"🔹 [1/3] Embedding (BGE-M3): {end_emb - start_emb:.4f} сек")

    # 3. Замер Reranking (самое тяжелое место)
    start_rerank = time.perf_counter()
    pairs = [[test_query, chunk] for chunk in test_chunks]
    scores = reranker.predict(pairs)
    end_rerank = time.perf_counter()
    print(f"🔹 [2/3] Reranking (10 кусков): {end_rerank - start_rerank:.4f} сек")

    # 4. Итоговое время поиска (без учета LLM)
    print(f"\n📊 Итого на поиск и ранжирование: {end_rerank - start_emb:.4f} сек")

if __name__ == "__main__":
    benchmark_rag()
