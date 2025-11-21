from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import time

app = FastAPI()

# --- JSON RAID ---
FILE = "raids.json"

def load_data():
    if not os.path.exists(FILE):
        return {"active": None}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"active": None}

def save_data(data):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- CORS (pour autoriser GitHub Pages à lire l’API) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------- API -----------------------

@app.get("/raid")
def get_raid():
    """Retourne le raid actif (depuis Discord)."""
    return load_data().get("active")


@app.post("/raid/update")
def update_raid(payload: dict):
    """Mise à jour complète du raid (appelé par ton bot discord)."""
    data = load_data()
    data["active"] = payload
    save_data(data)
    return {"status": "ok"}


@app.post("/raid/attack")
def apply_attack(info: dict):
    """
    Appelé par ton bot quand un joueur attaque.
    info = {
        "user_id": 123,
        "damage": 500,
        "pet_id": "dragon",
        "username": "John"
    }
    """
    data = load_data()
    raid = data.get("active")

    if not raid:
        return {"error": "no_raid"}

    # Baisser les PV
    raid["hp_current"] = max(0, raid["hp_current"] - info["damage"])

    # Enregistrer le joueur
    uid = str(info["user_id"])
    rec = raid["participants"].setdefault(uid, {
        "username": info["username"],
        "pet_id": info["pet_id"],
        "damage": 0
    })

    rec["damage"] += info["damage"]

    save_data(data)
    return {"status": "ok", "hp_current": raid["hp_current"]}


@app.post("/raid/join")
def join_raid(info: dict):
    """
    Appelé par ton bot quand un joueur rejoint.
    info = {
        "user_id": 123,
        "pet_id": "dragon",
        "username": "John"
    }
    """
    data = load_data()
    raid = data.get("active")

    if not raid:
        return {"error": "no_raid"}

    uid = str(info["user_id"])
    raid["participants"][uid] = {
        "username": info["username"],
        "pet_id": info["pet_id"],
        "damage": 0
    }

    save_data(data)
    return {"status": "ok"}
