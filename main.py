from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

app = FastAPI()

# CORS : autoriser ton GitHub Pages / tests locaux
origins = [
    "https://fragkilleur159-stack.github.io",          # ton GitHub Pages
    "https://fragkilleur159-stack.github.io/raid-view",
    "http://localhost:5500",                           # pratique pour tests locaux
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
    # dict: user_id -> { pet_id, damage, last_attack, ... }
    participants: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


# ========== Stockage en mémoire ==========

raid_state: Optional[RaidState] = None


# ========== Routes ==========

@app.get("/")
def root():
    return {"status": "ok", "message": "Raid API en ligne"}


@app.get("/raid/state")
def get_raid_state():
    """
    Utilisé par le site HTML pour afficher le raid.

    On transforme ici le RaidState "brut" envoyé par le bot
    en un format EXACTEMENT comme attendu par index.html :

    {
      "status": "...",
      "boss": "...",
      "hp_current": ...,
      "hp_max": ...,
      "stars": ...,
      "start": ...,
      "end": ...,
      "participants": [
        {"user_id": "...", "name": "...", "pet": "...", "damage": ...},
        ...
      ]
    }
    """
    if raid_state is None:
        raise HTTPException(status_code=404, detail="Aucun raid actif")

    rs = raid_state

    # Transforme le dict participants -> liste triée par dégâts
    participants_list: List[Dict[str, Any]] = []
    for uid, rec in rs.participants.items():
        participants_list.append({
            "user_id": uid,
            # Si un jour tu ajoutes "username" ou "pet_name" dans ton dict, ce sera pris automatiquement
            "name": rec.get("username") or f"Joueur {uid}",
            "pet": rec.get("pet_name") or rec.get("pet_id", ""),
            "damage": rec.get("damage", 0),
        })

    participants_list.sort(key=lambda p: p["damage"], reverse=True)

    # On renvoie exactement la forme utilisée par ton JS
    return {
        "status": rs.status,
        "boss": rs.boss_pet_id,
        "hp_current": rs.hp_current,
        "hp_max": rs.hp_max,
        "stars": rs.difficulty_stars,
        "start": rs.start,
        "end": rs.end,
        "participants": participants_list,
    }


@app.post("/raid/update")
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
