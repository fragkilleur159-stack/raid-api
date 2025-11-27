# main.py
import time
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 🔗 Pour lire l'inventaire des joueurs (même module que /inv)
try:
    from utils.inventory_store import user_items, item_label
except Exception:
    # Si jamais ce module n'est pas dispo sur l'API, ça évitera un crash
    def user_items(_uid: int) -> Dict[str, int]:
        return {}
    def item_label(item_id: str) -> str:
        return item_id


# ✅ IDs des items autorisés en raid (à adapter à tes IDs réels)
RAID_USABLE_ITEMS: Dict[str, Dict[str, str]] = {
    # exemple, adapte aux vrais ids de ton inventaire
    "potion_pet_petite": {
        "effect_label": "Rend 200 PV à ton familier"
    },
    "potion_pet_grosse": {
        "effect_label": "Rend 600 PV à ton familier"
    },
    "bomb_raid_petite": {
        "effect_label": "Inflige 1 000 dégâts au boss"
    },
    "bomb_raid_grosse": {
        "effect_label": "Inflige 3 000 dégâts au boss"
    },
}

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

class UseItemRequest(BaseModel):
    user_id: str
    item_id: str

class ChatIn(BaseModel):
    user_id: Optional[str] = None
    name: str
    content: str


class ChatMessage(BaseModel):
    user_id: Optional[str] = None
    name: str
    content: str
    is_spectator: bool = True
    ts: float = Field(default_factory=time.time)

class RaidParticipant(BaseModel):
    user_id: str
    name: str
    pet: str
    damage: int = 0
    hp_current: int = 0
    hp_max: int = 0

    # 🔥 pour les objets
    last_item_used: Optional[str] = None
    last_item_value: int = 0



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
    current_turn: Optional[str] = None

    # 🔥 Nouveau : historique du tchat
    chat: List[ChatMessage] = Field(default_factory=list)


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
    current_turn: Optional[str] = None


@app.get("/raid/items")
async def raid_get_items(user_id: str):
    """
    Retourne la liste des objets utilisables en raid que possède le joueur.
    """
    global raid_state
    if raid_state is None or raid_state.status != "running":
        return []

    try:
        uid_int = int(user_id)
    except ValueError:
        return []

    # inventaire complet du joueur
    inv = user_items(uid_int)  # {item_id: quantité}
    if not inv:
        return []

    items = []
    for iid, meta in RAID_USABLE_ITEMS.items():
        qty = int(inv.get(iid, 0))
        if qty <= 0:
            continue
        items.append({
            "id": iid,
            "name": item_label(iid),
            "effect": meta.get("effect_label", ""),
            "qty": qty,
        })

    return items


@app.post("/raid/use_item")
async def raid_use_item(req: UseItemRequest):
    """
    Ajoute une action d'utilisation d'objet dans la file d'actions du raid.
    (Comme les attaques, mais avec item_id.)
    """
    global raid_state
    if raid_state is None or raid_state.status != "running":
        raise HTTPException(status_code=400, detail="Aucun raid actif.")
    
    if req.user_id not in raid_state.participants:
        raise HTTPException(status_code=400, detail="Tu n'es pas dans le raid.")
    
    # empêcher le spam : une seule action par tour
    for h in raid_state.pending_hits:
        if h.get("user_id") == req.user_id:
            raise HTTPException(status_code=429, detail="Une action est déjà en attente.")

    raid_state.pending_hits.append({
        "user_id": req.user_id,
        "item_id": req.item_id,
        "ts": time.time(),
        "type": "item",
    })
    
    return {"ok": True}


@app.get("/raid/chat")
async def raid_chat_get(limit: int = 30):
    """
    Retourne les derniers messages du tchat du raid.
    """
    global raid_state
    if raid_state is None:
        return []

    msgs = raid_state.chat[-limit:]
    # on renvoie les plus récents en bas
    return [
        {
            "user_id": m.user_id,
            "name": m.name,
            "content": m.content,
            "is_spectator": m.is_spectator,
            "ts": m.ts,
        }
        for m in msgs
    ]


@app.post("/raid/update")
async def raid_update(payload: RaidUpdatePayload):
    """
    Appelée depuis le bot Discord (/cogs/raids.py) pour pousser l'état du raid.
    On met à jour l'état global sans toucher au tchat ni à la file d'attaques.
    """
    global raid_state

    # On reconstruit les participants dans le bon modèle
    participants: Dict[str, RaidParticipant] = {}
    for uid, p in payload.participants.items():
        participants[uid] = RaidParticipant(
            user_id=uid,
            name=(
                p.get("username")
                or p.get("name")
                or p.get("display_name")
                or f"User {uid}"
            ),
            pet=(
                p.get("pet_name")
                or p.get("pet_label")
                or p.get("pet")
                or "???"
            ),
            damage=int(p.get("damage", 0)),
            hp_current=int(p.get("hp_current", 0)),
            hp_max=int(p.get("hp_max", 0)),
        )

    # 🔥 On garde l'ancien tchat SI c'est le même raid (même id)
    old_chat: List[ChatMessage] = []
    if raid_state is not None and raid_state.id == payload.id:
        old_chat = list(raid_state.chat)

    # Si pas de raid ou id différent → nouveau RaidState
    if raid_state is None or raid_state.id != payload.id:
        raid_state = RaidState(
            id=payload.id,
            boss_pet_id=payload.boss_pet_id,
            boss=payload.boss_pet_id,
            hp_max=payload.hp_max,
            hp_current=payload.hp_current,
            start=payload.start,
            end=payload.end,
            status=payload.status,
            stars=payload.difficulty_stars,
            participants=participants,
            pending_hits=[],              # la file d'attaques repart propre
            current_turn=payload.current_turn,
            chat=old_chat,                # ✅ on réinjecte le tchat
        )
    else:
        # Même raid → on met juste à jour les champs volatils
        rs = raid_state
        rs.boss_pet_id = payload.boss_pet_id
        rs.boss = payload.boss_pet_id
        rs.hp_max = payload.hp_max
        rs.hp_current = payload.hp_current
        rs.start = payload.start
        rs.end = payload.end
        rs.status = payload.status
        rs.stars = payload.difficulty_stars
        rs.participants = participants
        rs.current_turn = payload.current_turn
        # rs.chat reste inchangé
        raid_state = rs

    return {"ok": True}




@app.post("/raid/chat")
async def raid_chat_post(payload: ChatIn):
    """
    Ajoute un message dans le tchat du raid.
    Si user_id n'est pas dans les participants → Spectateur.
    """
    global raid_state
    if raid_state is None or raid_state.status != "running":
        raise HTTPException(status_code=400, detail="Aucun raid actif.")

    # On nettoie un peu le message
    msg_txt = payload.content.strip()
    if not msg_txt:
        raise HTTPException(status_code=400, detail="Message vide.")

    user_id = str(payload.user_id) if payload.user_id else None

    # Est-ce que le joueur a rejoint le raid ?
    is_participant = False
    if user_id and user_id in raid_state.participants:
        is_participant = True

    chat_msg = ChatMessage(
        user_id=user_id,
        name=payload.name.strip()[:32] or "Inconnu",
        content=msg_txt[:300],
        is_spectator=not is_participant,
    )

    raid_state.chat.append(chat_msg)
    # on limite par exemple à 100 messages max
    if len(raid_state.chat) > 100:
        raid_state.chat = raid_state.chat[-100:]

    return {"ok": True}


@app.get("/raid/resolve_user")
async def resolve_user(name: str):
    """
    Permet de retrouver l'ID Discord d'un joueur à partir de son Pseudo#0000.
    """
    global raid_state
    if raid_state is None or raid_state.status != "running":
        return {"error": "no_raid"}

    name = name.strip().lower()

    # On cherche dans participants
    for uid, p in raid_state.participants.items():
        if p.name.lower() == name:
            return {"user_id": uid}

    return {"error": "not_found"}



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
        "current_turn": raid_state.current_turn,   # ✅
        "participants": [
    {
            "user_id": uid,
            "name": p.name,
            "pet": p.pet,
            "damage": p.damage,
            "hp_current": p.hp_current,
            "hp_max": p.hp_max,
            "items": getattr(p, "items", {})  # ← ajoute ceci
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

    # 🔒 Anti-spam : refuse si une attaque est déjà en attente pour ce joueur
    for h in raid_state.pending_hits:
        if h.get("user_id") == req.user_id:
            raise HTTPException(
                status_code=429,
                detail="Tu as déjà une attaque en attente, attends qu'elle soit résolue."
            )

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













