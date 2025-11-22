from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional

app = FastAPI()

# CORS : autoriser ton GitHub Pages
origins = [
    "https://fragkilleur159-stack.github.io",          # ton GitHub Pages
    "https://fragkilleur159-stack.github.io/raid-view",
    "http://localhost:5500",                            # pratique pour tests locaux
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== Modèle d'état de raid ==========

class RaidState(BaseModel):
    id: str
    boss_pet_id: str
    hp_max: int
    hp_current: int
    start: float
    end: float
    status: str
    difficulty_stars: int
    # dict: user_id -> { username, pet_name, damage, ... }
    participants: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

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
        # Tu peux soit renvoyer 404, soit un état "vide"
        raise HTTPException(status_code=404, detail="Aucun raid actif")
    return raid_state

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
