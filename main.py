from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional
import time

app = FastAPI()

# CORS : autoriser ton GitHub Pages
origins = [
    "https://fragkilleur159-stack.github.io",  # ton GitHub Pages
    "https://fragkilleur159-stack.github.io/raid-view",
    "http://localhost:5500",  # pratique pour tests locaux
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== Modèles ==========

class RaidState(BaseModel):
    id: str
    boss_pet_id: str
    hp_max: int
    hp_current: int
    start: float
    end: float
    status: str
    difficulty_stars: int
    participants: Dict[str, Dict[str, Any]] = {}


class AttackPayload(BaseModel):
    user_id: str      # on garde ça en str (Discord ID ou pseudo)
    username: str     # nom à afficher
    pet_name: str     # juste pour affichage
    base_damage: int  # dégâts envoyés par le client (on pourra raffiner plus tard)

# ========== Stockage en mémoire ==========

raid_state: Optional[RaidState] = None

# ========== Endpoints ==========

@app.get("/")
def root():
    return {"status": "ok", "msg": "Raid API en ligne"}

@app.get("/raid/state")
def get_raid_state():
    """Utilisé par le site HTML pour afficher le raid."""
    if raid_state is None:
        raise HTTPException(status_code=404, detail="Aucun raid actif")
    return raid_state

@app.post("/raid/state")
def set_raid_state(data: Dict[str, Any]):
    """
    Utilisé par TON BOT Discord pour pousser l'état du raid.
    Il envoie tout le dict (id, boss_pet_id, hp_max, hp_current, etc.).
    """
    global raid_state
    try:
        raid_state = RaidState(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Format invalide: {e}")
    return {"ok": True}

@app.post("/raid/attack")
def raid_attack(payload: AttackPayload):
    """
    Utilisé par le SITE HTML quand un joueur clique sur "Attaquer".
    C'est ici qu'on applique les dégâts.
    """
    global raid_state
    if raid_state is None:
        raise HTTPException(status_code=404, detail="Aucun raid actif")

    now = time.time()
    if now >= raid_state.end:
        raid_state.status = "finished"
        raise HTTPException(status_code=400, detail="Le raid est terminé")

    if raid_state.hp_current <= 0:
        raid_state.status = "finished"
        raise HTTPException(status_code=400, detail="Le boss est déjà vaincu")

    dmg = max(1, int(payload.base_damage))

    # Appliquer dégâts sur le boss
    new_hp = max(0, raid_state.hp_current - dmg)
    raid_state.hp_current = new_hp
    if new_hp <= 0:
        raid_state.status = "finished"

    # Mettre à jour le participant
    participants = raid_state.participants or {}
    rec = participants.get(payload.user_id) or {
        "username": payload.username,
        "pet_name": payload.pet_name,
        "damage": 0,
    }
    rec["username"] = payload.username
    rec["pet_name"] = payload.pet_name
    rec["damage"] = int(rec.get("damage", 0)) + dmg
    participants[payload.user_id] = rec
    raid_state.participants = participants

    return {
        "ok": True,
        "raid": raid_state,
        "applied_damage": dmg,
    }
