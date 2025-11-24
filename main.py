# main.py
import time
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI()

# CORS pour autoriser ton site GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # si tu veux restreindre, mets ton domaine ici
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
#   MODÈLES Pydantic
# =========================

class RaidParticipant(BaseModel):
    user_id: str
    name: str
    pet: str
    damage: int = 0


class RaidState(BaseModel):
    id: Optional[str] = None
    boss_pet_id: Optional[str] = None
    boss: Optional[str] = None  # nom lisible (optionnel)
    hp_max: int = 0
    hp_current: int = 0
    start: Optional[float] = None
    end: Optional[float] = None
    status: str = "idle"  # idle / running / finished
    stars: int = 0
    participants: Dict[str, RaidParticipant] = Field(default_factory=dict)

    # 🔥 Nouveau : file d’attaques
    pending_hits: List[Dict[str, Any]] = Field(default_factory=list)


# État global en mémoire
raid_state: Optional[RaidState] = None


# =========================
#   ROUTES
# =========================

@app.get("/")
async def root():
    return {"ok": True, "message": "Raid API up"}


@app.get("/health")
async def health():
    return {"status": "ok"}


class RaidUpdatePayload(BaseModel):
    id: Optional[str] = None
    boss_pet_id: Optional[str] = None
    hp_max: int
    hp_current: int
    start: Optional[float] = None
    end: Optional[float] = None
    status: str
    difficulty_stars: int = 0
    participants: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


@app.post("/raid/update")
async def raid_update(payload: RaidUpdatePayload):
    """
    Appelée depuis le bot Discord (/cogs/raids.py) pour pousser l'état du raid.
    On met à jour l'état global sans toucher à la file d'attaques.
    """
    global raid_state

    # On reconstruit les participants dans le bon modèle
    participants: Dict[str, RaidParticipant] = {}
    for uid, p in payload.participants.items():
        participants[uid] = RaidParticipant(
            user_id=uid,
            name=p.get("name") or p.get("display_name") or f"User {uid}",
            pet=p.get("pet_label") or p.get("pet") or "???",
            damage=int(p.get("damage", 0)),
        )

    if raid_state is None or raid_state.id != payload.id:
        # Nouveau raid → on écrase tout sauf la file (on la remet vide)
        raid_state = RaidState(
            id=payload.id,
            boss_pet_id=payload.boss_pet_id,
            boss=payload.boss_pet_id,  # tu peux envoyer un nom lisible plus tard
            hp_max=payload.hp_max,
            hp_current=payload.hp_current,
            start=payload.start,
            end=payload.end,
            status=payload.status,
            stars=payload.difficulty_stars,
            participants=participants,
            pending_hits=[],
        )
    else:
        # Même raid → on met à jour les champs, mais on garde la file d'attaques
        rs = raid_state
        rs.boss_pet_id = payload.boss_pet_id
        rs.hp_max = payload.hp_max
        rs.hp_current = payload.hp_current
        rs.start = payload.start
        rs.end = payload.end
        rs.status = payload.status
        rs.stars = payload.difficulty_stars
        rs.participants = participants
        # rs.pending_hits inchangé
        raid_state = rs

    return {"ok": True}


@app.get("/raid/state")
async def raid_state_endpoint():
    """
    Donne l'état du raid pour le site (viewer).
    """
    if raid_state is None:
        return {
            "status": "idle",
            "boss": None,
            "hp_current": 0,
            "hp_max": 0,
            "stars": 0,
            "start": None,
            "end": None,
            "participants": [],
        }

    return {
        "status": raid_state.status,
        "boss": raid_state.boss_pet_id,
        "hp_current": raid_state.hp_current,
        "hp_max": raid_state.hp_max,
        "stars": raid_state.stars,
        "start": raid_state.start,
        "end": raid_state.end,
        "participants": [
            {
                "user_id": uid,
                "name": p.name,
                "pet": p.pet,
                "damage": p.damage,
            }
            for uid, p in raid_state.participants.items()
        ],
    }


# =========================
#   ATTAQUES (depuis le site)
# =========================

class AttackRequest(BaseModel):
    user_id: str


@app.post("/raid/attack")
async def raid_attack(req: AttackRequest):
    """
    Appelée par le bouton "Attaquer" sur le site.
    On NE calcule PAS les dégâts ici, on stocke juste l'intention d'attaque.
    Le bot viendra consommer ces "hits" via /raid/pending_hits.
    """
    global raid_state
    if raid_state is None or raid_state.status != "running":
        raise HTTPException(status_code=400, detail="Aucun raid en cours")

    # Vérifie que le joueur est bien dans le raid (a fait /raid_join)
    if req.user_id not in raid_state.participants:
        raise HTTPException(status_code=400, detail="Tu n'es pas inscrit au raid (/raid_join).")

    hit = {
        "user_id": req.user_id,
        "ts": time.time(),
    }
    raid_state.pending_hits.append(hit)
    return {"ok": True}


@app.get("/raid/pending_hits")
async def raid_pending_hits():
    """
    Appelée par le bot Discord pour récupérer les attaques en attente.
    On renvoie la liste, puis on la vide.
    """
    global raid_state
    if raid_state is None:
        return []

    hits = list(raid_state.pending_hits)
    raid_state.pending_hits = []
    return hits
