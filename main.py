# main.py
import time
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# 🔗 Pour lire l'inventaire des joueurs (même module que /inv)
try:
    from utils.inventory_store import user_items, item_label,
except Exception:
    # Si jamais ce module n'est pas dispo sur l'API, ça évitera un crash
    def user_items(_uid: int) -> Dict[str, int]:
        return {}
    def item_label(item_id: str) -> str:
        return item_id

# 🔮 Artefacts : on importe le store XP (même JSON que le bot)
try:
    from utils.artifacts_store import (
        has_artifacts_unlocked,
        get_artifacts,
        set_artifact_slot,
    )
except Exception:
    # fallback au cas où ça n'existe pas sur l'API
    def has_artifacts_unlocked(_uid: int) -> bool:
        return False

    def get_artifacts(_uid: int) -> Dict[str, Optional[str]]:
        return {"slot1": None, "slot2": None, "slot3": None}

    def set_artifact_slot(_uid: int, _slot: str, _artifact_id: Optional[str]) -> None:
        pass


# Liste des IDs d'artefacts possibles (à adapter si tu en ajoutes)
ARTIFACT_ITEM_IDS = ["art_feu", "art_glace", "art_ombre"]


# ✅ IDs des items autorisés en raid (à adapter à tes IDs réels)
RAID_USABLE_ITEMS: Dict[str, Dict[str, str]] = {
    # exemple, adapte aux vrais ids de ton inventaire
    "potion_pet_petite": {
        "effect_label": "Rend 400 PV à ton familier"
    },
    "potion_pet_grosse": {
        "effect_label": "Rend 1200 PV à ton familier"
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
    raid_id: str
    item_id: str

class AttackRequest(BaseModel):
    user_id: str
    raid_id: str

class ChatIn(BaseModel):
    user_id: Optional[str] = None
    raid_id: str
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
    # 🔥 inventaire raid (envoyé par le bot)
    items: Dict[str, int] = Field(default_factory=dict)
    artifacts_unlocked: bool = False

class UserArtifactsEquipRequest(BaseModel):
    user_id: str
    slot: str
    artifact_id: Optional[str] = None  # None = retirer


class RaidState(BaseModel):
    id: str
    boss_pet_id: Optional[str] = None
    boss: Optional[str] = None  # nom lisible (optionnel)
    hp_max: int = 0
    hp_current: int = 0
    start: Optional[float] = None
    end: Optional[float] = None
    status: str = "idle"
    stars: int = 0
    participants: Dict[str, RaidParticipant] = Field(default_factory=dict)

    # 🔥 file d’actions
    pending_hits: List[Dict[str, Any]] = Field(default_factory=list)
    current_turn: Optional[str] = None

    # 🔥 tchat par raid
    chat: List[ChatMessage] = Field(default_factory=list)

    # 🔥 Upside Down
    upside_down_active: bool = False
    upside_down_turns_left: int = 0


# ✅ Multi-raid : TOUS les raids en mémoire
raid_states: Dict[str, RaidState] = {}


def get_raid_or_none(raid_id: str) -> Optional[RaidState]:
    return raid_states.get(str(raid_id))


def get_raid_or_404(raid_id: str) -> RaidState:
    raid = get_raid_or_none(raid_id)
    if raid is None:
        raise HTTPException(status_code=404, detail="Raid inconnu.")
    return raid


# =========================
#   ROUTES
# =========================

@app.get("/")
async def root():
    return {"ok": True, "message": "Raid API up"}


# ---------- LISTE DES RAIDS ----------
@app.get("/raid/list")
async def raid_list():
    """
    Retourne la liste des raids connus (en cours ou terminés).
    """
    res = []
    for r in raid_states.values():
        res.append({
            "id": r.id,
            "boss_pet_id": r.boss_pet_id,
            "boss": r.boss,
            "hp_max": r.hp_max,
            "hp_current": r.hp_current,
            "status": r.status,
            "stars": r.stars,
            "start": r.start,
            "end": r.end,
            "label": r.boss or f"Raid {r.id}",
        })
    # on trie du plus récent au plus ancien
    res.sort(key=lambda x: (x.get("start") or 0), reverse=True)
    return res


# ---------- ÉTAT D'UN RAID ----------
@app.get("/raid/state")
async def raid_state_endpoint(raid_id: str = Query(...)):
    """
    État complet d'un raid donné (pour le viewer).
    """
    raid = get_raid_or_none(raid_id)
    if raid is None:
        return {
            "status": "idle",
            "boss": None,
            "boss_pet_id": None,
            "hp_max": 0,
            "hp_current": 0,
            "participants": [],
            "stars": 0,
            "start": None,
            "end": None,
            "current_turn": None,
            "upside_down_active": False,
            "upside_down_turns_left": 0,
        }

    return {
        "id": raid.id,
        "status": raid.status,
        "boss": raid.boss,
        "boss_pet_id": raid.boss_pet_id,
        "hp_max": raid.hp_max,
        "hp_current": raid.hp_current,
        "participants": list(raid.participants.values()),
        "stars": raid.stars,
        "start": raid.start,
        "end": raid.end,
        "current_turn": raid.current_turn,
        "upside_down_active": raid.upside_down_active,
        "upside_down_turns_left": raid.upside_down_turns_left,
    }


# ---------- ITEMS D'UN JOUEUR DANS UN RAID ----------
@app.get("/raid/items")
async def raid_get_items(raid_id: str, user_id: str):
    """
    Items de raid pour UN raid précis.
    """
    raid = get_raid_or_none(raid_id)
    if raid is None or raid.status != "running":
        return []

    try:
        uid_int = int(user_id)
    except ValueError:
        return []

    participant = raid.participants.get(str(user_id))
    inv: Dict[str, int] = {}

    if participant and participant.items:
        inv = dict(participant.items or {})
    else:
        inv_raw = user_items(uid_int)

        if isinstance(inv_raw, list):
            inv = {iid: int(qty) for (iid, qty) in inv_raw}
        else:
            inv = dict(inv_raw or {})

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


# ---------- UTILISATION D'OBJET ----------
@app.post("/raid/use_item")
async def raid_use_item(req: UseItemRequest):
    raid = get_raid_or_404(req.raid_id)

    if raid.status != "running":
        raise HTTPException(status_code=400, detail="Raid non actif.")

    if req.user_id not in raid.participants:
        raise HTTPException(status_code=400, detail="Tu n'es pas dans ce raid.")

    # empêcher le spam : une seule action par tour
    for h in raid.pending_hits:
        if h.get("user_id") == req.user_id:
            raise HTTPException(status_code=429, detail="Une action est déjà en attente.")

    raid.pending_hits.append({
        "user_id": req.user_id,
        "item_id": req.item_id,
        "ts": time.time(),
        "type": "item",
    })

    return {"ok": True}


# ---------- ATTAQUE ----------
@app.post("/raid/attack")
async def raid_attack(req: AttackRequest):
    raid = get_raid_or_404(req.raid_id)

    if raid.status != "running":
        raise HTTPException(status_code=400, detail="Raid non actif.")

    if req.user_id not in raid.participants:
        raise HTTPException(status_code=400, detail="Tu n'es pas dans ce raid.")

    # une seule action par tour
    for h in raid.pending_hits:
        if h.get("user_id") == req.user_id:
            raise HTTPException(status_code=429, detail="Tu as déjà une action en attente.")

    raid.pending_hits.append({
        "user_id": req.user_id,
        "ts": time.time(),
        "type": "attack",
    })

    return {"ok": True}


# ---------- PENDING HITS (appelé par le bot) ----------
@app.get("/raid/pending_hits")
async def raid_pending_hits(raid_id: str):
    raid = get_raid_or_404(raid_id)

    hits = list(raid.pending_hits)
    raid.pending_hits.clear()
    return hits


# ---------- TCHAT ----------
@app.get("/raid/chat")
async def raid_chat_get(raid_id: str, limit: int = 30):
    raid = get_raid_or_none(raid_id)
    if raid is None:
        return []

    msgs = raid.chat[-limit:]
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


@app.post("/raid/chat")
async def raid_chat_post(payload: ChatIn):
    raid = get_raid_or_404(payload.raid_id)

    is_spectator = True
    if payload.user_id is not None:
        if str(payload.user_id) in raid.participants:
            is_spectator = False

    msg = ChatMessage(
        user_id=payload.user_id,
        name=payload.name,
        content=payload.content[:300],
        is_spectator=is_spectator,
    )
    raid.chat.append(msg)
    raid.chat = raid.chat[-200:]

    return {"ok": True}


# ---------- RESOLVE USER (pour trouver l’ID depuis le pseudo) ----------
@app.get("/raid/resolve_user")
async def raid_resolve_user(raid_id: str, name: str):
    raid = get_raid_or_none(raid_id)
    if raid is None:
        return {"user_id": None}

    name = (name or "").strip().lower()
    if not name:
        return {"user_id": None}

    for p in raid.participants.values():
        if name in (p.name or "").lower():
            return {"user_id": p.user_id}

    return {"user_id": None}


# ---------- UPDATE DEPUIS LE BOT ----------
class RaidUpdateParticipant(BaseModel):
    username: Optional[str] = None
    pet_id: Optional[str] = None
    damage: int = 0
    hp_current: int = 0
    hp_max: int = 0
    last_item_used: Optional[str] = None
    last_item_value: int = 0
    items: Dict[str, int] = Field(default_factory=dict)
    artifacts_unlocked: bool = False


class RaidUpdatePayload(BaseModel):
    id: str
    boss_pet_id: Optional[str] = None
    boss_name: Optional[str] = None
    hp_max: int = 0
    hp_current: int = 0
    start: Optional[float] = None
    end: Optional[float] = None
    status: str = "idle"
    stars: int = 0
    current_turn: Optional[str] = None
    upside_down_active: bool = False
    upside_down_turns_left: int = 0
    participants: Dict[str, RaidUpdateParticipant] = Field(default_factory=dict)


@app.post("/raid/update")
async def raid_update(payload: RaidUpdatePayload):
    raid_id = str(payload.id)

    # --- reconstruire participants ---
    participants: Dict[str, RaidParticipant] = {}
    for uid, pdata in payload.participants.items():
        uid_str = str(uid)
        p = RaidParticipant(
            user_id=uid_str,
            name=pdata.username or f"Joueur {uid_str}",
            pet=pdata.pet_id or "???",
            damage=pdata.damage or 0,
            hp_current=pdata.hp_current or 0,
            hp_max=pdata.hp_max or 0,
            last_item_used=pdata.last_item_used,
            last_item_value=pdata.last_item_value or 0,
            items=pdata.items or {},
            artifacts_unlocked=bool(pdata.artifacts_unlocked),
        )
        participants[uid_str] = p

    existing = raid_states.get(raid_id)

    # on garde le chat et les pending_hits si le raid existe déjà
    if existing:
        chat = existing.chat
        pending_hits = existing.pending_hits
    else:
        chat = []
        pending_hits = []

    raid = RaidState(
        id=raid_id,
        boss_pet_id=payload.boss_pet_id,
        boss=payload.boss_name,
        hp_max=payload.hp_max,
        hp_current=payload.hp_current,
        start=payload.start,
        end=payload.end,
        status=payload.status,
        stars=payload.stars,
        participants=participants,
        current_turn=payload.current_turn,
        upside_down_active=payload.upside_down_active,
        upside_down_turns_left=payload.upside_down_turns_left,
        chat=chat,
        pending_hits=pending_hits,
    )

    raid_states[raid_id] = raid
    return {"ok": True}











































