#!/usr/bin/env python3
"""
ANIMARA Identity Service v1.0
- Face Recognition (InsightFace)
"""

import os
import json
import time
import numpy as np
from typing import Optional, Tuple, List
from pymilvus import MilvusClient

CONFIG = {
    "insightface_model": "/media/agx-thor/SSD_AI/models/insightface/models",
    "milvus_uri": "http://localhost:19530",
    "face_threshold": 0.5,
}

class FaceRecognizer:
    def __init__(self):
        print("Loading InsightFace...")
        import insightface
        from insightface.app import FaceAnalysis
        self.app = FaceAnalysis(
            name="buffalo_l",
            root=CONFIG["insightface_model"],
            providers=['CUDAExecutionProvider', 'CPUExecutionProvider']
        )
        self.app.prepare(ctx_id=0, det_size=(640, 640))
        print("InsightFace ready")
    
    def get_embedding(self, image):
        faces = self.app.get(image)
        if not faces:
            return None
        face = max(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]))
        return face.embedding

class IdentityManager:
    def __init__(self):
        print("Initializing Identity Manager...")
        self.milvus = MilvusClient(uri=CONFIG["milvus_uri"])
        self.face_recognizer = FaceRecognizer()
        print("Identity Manager ready")
    
    def identify_face(self, image):
        embedding = self.face_recognizer.get_embedding(image)
        if embedding is None:
            return None, 0.0, {}
        
        results = self.milvus.search(
            "persons",
            [embedding.tolist()],
            anns_field="face_embedding",
            limit=1,
            output_fields=["person_id", "name", "role", "profile_json", "permissions"]
        )
        
        if not results or not results[0]:
            return None, 0.0, {}
        
        hit = results[0][0]
        distance = hit.get("distance", 0)
        
        if distance < CONFIG["face_threshold"]:
            return None, distance, {}
        
        entity = hit.get("entity", {})
        return entity.get("person_id"), distance, {
            "name": entity.get("name"),
            "role": entity.get("role")
        }
    
    def enroll_face(self, person_id, name, image, role="guest"):
        embedding = self.face_recognizer.get_embedding(image)
        if embedding is None:
            print("No face detected")
            return False
        
        fake_voice = np.zeros(192, dtype=np.float32).tolist()
        
        self.milvus.insert("persons", [{
            "person_id": person_id,
            "name": name,
            "role": role,
            "face_embedding": embedding.tolist(),
            "voice_embedding": fake_voice,
            "profile_json": "{}",
            "permissions": '["basic_info"]',
            "created_at": int(time.time()),
            "last_seen": int(time.time())
        }])
        print(f"Enrolled: {name} ({person_id})")
        return True
    
    def list_persons(self):
        return self.milvus.query("persons", filter="", output_fields=["person_id", "name", "role"], limit=100)

if __name__ == "__main__":
    print("=" * 50)
    print("ANIMARA IDENTITY SERVICE TEST")
    print("=" * 50)
    manager = IdentityManager()
    print("\nRegistered persons:")
    for p in manager.list_persons():
        print(f"  {p.get('name')} ({p.get('person_id')}) - {p.get('role')}")
    print("\nReady!")
