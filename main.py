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
    # 🔥 inventaire raid (envoyé par le bot)
    items: Dict[str, int] = Field(default_factory=dict)
    artifacts_unlocked: bool = False
    

class UserArtifactsEquipRequest(BaseModel):
    user_id: str
    slot: str
    artifact_id: Optional[str] = None  # None = retirer


class RaidState(BaseModel):
    id: Optional[str] = None
    boss_pet_id: Optional[str] = None
    boss: Optional[str] = None  # nom lisible (optionnel)
    hp_max: int = 0
    hp_current: int = 0
    start: Optional[float] = None
    end: Optional[float] = None
    status: str = "idle"
    stars: int = 0
    participants: Dict[str, RaidParticipant] = Field(default_factory=dict)

    # 🔥 Nouveau : file d’attaques
    pending_hits: List[Dict[str, Any]] = Field(default_factory=list)
    current_turn: Optional[str] = None

    # 🔥 Nouveau : historique du tchat
    chat: List[ChatMessage] = Field(default_factory=list)

    # 🔥 Upside Down
    upside_down_active: bool = False
    upside_down_turns_left: int = 0


raid_states: Dict[str, RaidState] = {}  # nouveau : tous les raids en mémoire



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
    # 🔥 Upside Down, envoyé par le bot
    upside_down_active: bool = False
    upside_down_turns_left: int = 0

@app.get("/user/artifacts")
async def user_get_artifacts(uid: str):
    """
    Retourne:
      - unlocked: bool (système artefacts débloqué ?)
      - slots: slots équipés (slot1/2/3)
      - available: artefacts possédés dans l'inventaire (filtré sur ARTIFACT_ITEM_IDS)
    """
    try:
        uid_i = int(uid)
    except ValueError:
        return {"unlocked": False, "slots": {}, "available": {}}

    # ✅ on prend la vérité depuis le store d'artefacts
    unlocked = has_artifacts_unlocked(uid_i)

    if unlocked:
        slots = get_artifacts(uid_i)
    else:
        slots = {
            "slot1": None,
            "slot2": None,
            "slot3": None,
        }

    inv = user_items(uid_i) or {}
    available: Dict[str, Dict[str, Any]] = {}
    for art_id in ARTIFACT_ITEM_IDS:
        qty = int(inv.get(art_id, 0) or 0)
        if qty > 0:
            available[art_id] = {
                "label": item_label(art_id),
                "qty": qty,
            }

    return {"unlocked": unlocked, "slots": slots, "available": available}


@app.post("/user/artifacts/equip")
async def user_equip_artifact(req: UserArtifactsEquipRequest):
    """
    Change l'artefact d'un slot pour un joueur.
    """
    try:
        uid_i = int(req.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="user_id invalide")

    if req.slot not in ("slot1", "slot2", "slot3"):
        raise HTTPException(status_code=400, detail="Slot invalide")

    # Vérifier que le système est débloqué
    if not has_artifacts_unlocked(uid_i):
        raise HTTPException(
            status_code=403,
            detail="Tu n'as pas encore débloqué les artefacts."
        )

    art_id = req.artifact_id

    if art_id is not None:
        if art_id not in ARTIFACT_ITEM_IDS:
            raise HTTPException(status_code=400, detail="Artefact inconnu.")
        inv = user_items(uid_i) or {}
        if int(inv.get(art_id, 0) or 0) <= 0:
            raise HTTPException(
                status_code=400,
                detail="Tu ne possèdes pas cet artefact."
            )

    # Sauvegarde dans le JSON XP
    set_artifact_slot(uid_i, req.slot, art_id)

    slots = get_artifacts(uid_i)
    return {"ok": True, "slots": slots}

@app.get("/raid/items")
async def raid_get_items(user_id: str):
    """
    Retourne la liste des objets utilisables en raid que possède le joueur.
    On privilégie les items envoyés par le bot dans raid_state.participants[uid].items.
    """
    global raid_state
    if raid_state is None or raid_state.status != "running":
        return []

    try:
        uid_int = int(user_id)
    except ValueError:
        return []

    # 1️⃣ On tente d'utiliser les items stockés dans l'état du raid
    participant = raid_state.participants.get(user_id)
    inv: Dict[str, int] = {}

    if participant and participant.items:
        inv = dict(participant.items or {})
    else:
        # 2️⃣ Fallback : lecture directe via user_items (utile en local)
        inv_raw = user_items(uid_int)  # chez toi: [(item_id, qty), ...] OU un dict

        # 🔁 Normalisation en dict {item_id: qty}
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
    global raid_state, raid_states

    raid_id = str(payload.id)

    # --- reconstruction des participants comme avant ---
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

    # --- on regarde si on avait déjà ce raid ---
    existing: Optional[RaidState] = raid_states.get(raid_id)

    if existing is None or existing.id != raid_id:
        # Nouveau raid : on part d'une base propre,
        # mais on garde le tchat si jamais on veut le réutiliser
        old_chat = existing.chat if existing else []

        rs = RaidState(
            id=raid_id,
            boss_pet_id=payload.boss_pet_id,
            boss=payload.boss_pet_id,
            hp_max=payload.hp_max,
            hp_current=payload.hp_current,
            start=payload.start,
            end=payload.end,
            status=payload.status,
            stars=payload.difficulty_stars,
            participants=participants,
            pending_hits=[],              # la file d'attaques repart propre pour ce raid
            current_turn=payload.current_turn,
            chat=old_chat,
            upside_down_active=payload.upside_down_active,
            upside_down_turns_left=payload.upside_down_turns_left,
        )
    else:
        # Même raid → on met juste à jour les champs volatils
        rs = existing
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
        rs.upside_down_active = payload.upside_down_active
        rs.upside_down_turns_left = payload.upside_down_turns_left
        # rs.chat reste inchangé
        # rs.pending_hits reste inchangé aussi

    # ✅ on sauvegarde dans le dict multi-raid
    raid_states[raid_id] = rs
    # ✅ on garde aussi la compatibilité avec l’ancien code
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
    global raid_state
    if raid_state is None or raid_state.status != "running":
        return {"error": "no_raid"}

    name = name.strip().lower()

    for uid, p in raid_state.participants.items():
        p_name = p.name.lower()
        if name in p_name:  # 🔥 match partiel au lieu de strict
            return {"user_id": uid}

    return {"error": "not_found"}


@app.get("/raid/list")
async def raid_list():
    """
    Retourne la liste des raids 'running' connus par l'API.
    Utilisé par ta page de sélection des raids.
    """
    out = []
    for rs in raid_states.values():
        if rs.status != "running":
            continue

        out.append({
            "id": rs.id,
            "boss_pet_id": rs.boss_pet_id,
            "hp_current": rs.hp_current,
            "hp_max": rs.hp_max,
            "stars": rs.stars,
            "start": rs.start,
            "end": rs.end,
        })

    # tri optionnel par date de début (du plus récent au plus ancien)
    out.sort(key=lambda r: r["start"], reverse=True)
    return out





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
        "upside_down_active": raid_state.upside_down_active,
        "upside_down_turns_left": raid_state.upside_down_turns_left,
        "participants": [
    {
            "user_id": uid,
            "name": p.name,
            "pet": p.pet,
            "damage": p.damage,
            "hp_current": p.hp_current,
            "hp_max": p.hp_max,
            "items": getattr(p, "items", {}), # ← ajoute ceci
            # 🔥 dernier objet utilisé par ce joueur
            "last_item_used": p.last_item_used,
            "last_item_value": p.last_item_value,
            "artifacts_unlocked": has_artifacts_unlocked(int(uid)),
        }
        for uid, p in raid_state.participants.items()
    ]
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
        "type": "attack",
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


@app.post("/raid/consume_hits")
async def raid_consume_hits():
    """
    Compatibilité / debug. Normalement, on n'en a plus besoin,
    car /raid/pending_hits vide déjà la file.
    """
    global raid_state
    if raid_state is None:
        return {"ok": False}

    raid_state.pending_hits = []
    return {"ok": True}






































