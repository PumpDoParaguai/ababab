"""Cliente da API web do Traderie.

Derivado de traderie-bot (Copyright (C) 2022 Imanol-Mikel Barba Sabariego,
GPL-3.0-or-later). Reescrito como uma classe com sessão HTTP única, timeouts,
tentativas automáticas para leituras e Authorization *opcional*.

Política de autenticação
------------------------
Cada endpoint tem uma chave (ver ``ENDPOINTS``) e uma política:

  * ``public``  - tentado sem token; se o servidor recusar, vira AuthRequired.
  * ``private`` - exige token; sem ele falhamos localmente, sem gastar requisição.

Os padrões abaixo são uma HIPÓTESE (o código original enviava o cabeçalho em
tudo, vazio, e só bloqueava ações localmente). Para tirar a dúvida, use
``TraderieClient.diagnose()`` (botão "Testar endpoints" no painel, ou
``python diagnose.py``): ele chama os endpoints de LEITURA com e sem token e
ajusta a política em memória conforme o que o servidor realmente respondeu.
Endpoints que alteram a conta (PUT/POST) nunca são testados e ficam sempre
privados.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import requests
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)

BASE_URL = "https://traderie.com/api"
DEFAULT_SLUG = "creaturesofsonaria"
MAX_PAGES = 60  # trava de segurança contra paginação infinita
# Não presumimos cooldown fixo: a decisão depende de sinais explícitos da API.
_REFRESH_TRUE = ("can_refresh", "canRefresh", "refreshable", "can_relist", "canRelist", "relistable")
_REFRESH_TIMES = ("next_refresh_at", "nextRefreshAt", "refresh_available_at", "refreshAvailableAt", "relist_available_at", "relistAvailableAt", "next_relist_at", "nextRelistAt")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# chave -> (método, caminho, política padrão)
ENDPOINTS: Dict[str, Tuple[str, str, str]] = {
    # leituras
    "users":                ("GET", "users", "public"),
    "accounts":             ("GET", "accounts", "public"),
    "listings":             ("GET", "listings", "public"),
    "offers":               ("GET", "offers", "private"),
    "notifications":        ("GET", "notifications", "private"),
    "conversations":        ("GET", "conversations", "private"),
    "messages":             ("GET", "messages", "private"),
    # escritas: sempre privadas
    "accounts.update":      ("PUT", "accounts/update", "private"),
    "listings.refresh":     ("PUT", "listings/refresh", "private"),
    "listings.create":      ("POST", "listings/create", "private"),
    "listings.delete":      ("POST", "sell", "private"),
    "notifications.read":   ("PUT", "notifications/read", "private"),
    "offers.deny":          ("PUT", "offers/deny", "private"),
    "offers.accept":        ("PUT", "offers/accept", "private"),
    "conversations.create": ("POST", "conversations", "private"),
    "conversations.update": ("PUT", "conversations", "private"),
    "messages.send":        ("POST", "messages", "private"),
    "reviews.add":          ("POST", "reviews/add", "private"),
    "blocks.add":           ("POST", "blocks", "private"),
}
PROBEABLE = ("accounts", "listings", "offers", "notifications", "conversations")


def default_policy() -> Dict[str, str]:
    return {key: pol for key, (_m, _p, pol) in ENDPOINTS.items()}


# --------------------------------------------------------------------------
# Erros
# --------------------------------------------------------------------------
class TraderieError(Exception):
    """Falha ao falar com a API (rede, HTTP, JSON inesperado ou erro da API)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class AuthRequired(TraderieError):
    """A operação precisa de Authorization (ausente, expirado ou recusado)."""


class Blocked(TraderieError):
    """O site respondeu com uma página anti-bot (ex.: Cloudflare), não com a API."""


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------
@dataclass
class ListingProperty:
    id: Any
    name: str
    value: str
    type: str = "string"
    icon_url: Optional[str] = None


@dataclass
class Listing:
    listingID: int
    updated: str
    properties: Dict[str, ListingProperty] = field(default_factory=dict)
    itemName: Optional[str] = None
    amount: Optional[int] = None
    image_url: Optional[str] = None
    itemID: Optional[int] = None
    can_refresh: Optional[bool] = None  # None = API não informou disponibilidade
    refresh_available_at: Optional[str] = None
    item_category: str = "other"
    availability_source: str = "api"


@dataclass
class Notification:
    notificationID: str
    text: str
    date: str
    fromUserID: Optional[int]
    listingID: Optional[int]


@dataclass
class Message:
    msgID: str
    text: str
    fromID: int
    toID: int


@dataclass
class Conversation:
    conversationID: int
    userID: int


@dataclass
class Offer:
    itemName: str
    offerID: int
    listingID: int
    sellerID: int
    sellerUsername: str
    buyerID: int
    buyerUsername: str
    amount: int
    itemID: int
    item_category: str = "other"
    image_url: Optional[str] = None


@dataclass
class Probe:
    """Resultado de uma chamada de diagnóstico a um endpoint de leitura."""
    endpoint: str
    status: Optional[int]   # código HTTP (None = sem conexão)
    verdict: str            # ok | auth | blocked | notfound | error | network
    count: Optional[int] = None  # nº de itens devolvidos (quando é lista)
    detail: str = ""


# --------------------------------------------------------------------------
# Utilidades puras (fáceis de testar)
# --------------------------------------------------------------------------
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*$")


def clean_slug(slug: str) -> str:
    cleaned = "".join(ch for ch in (slug or "") if ch.isalnum()).lower()
    if not cleaned:
        raise ValueError("O slug do jogo não pode ser vazio.")
    return cleaned


def clean_token(token: Optional[str]) -> str:
    """Aceita o valor puro ou colado com prefixo 'authorization:'."""
    token = (token or "").strip().strip('"').strip("'")
    token = re.sub(r"^authorization\s*:\s*", "", token, flags=re.I)
    return token.strip()


def looks_like_bare_jwt(token: str) -> bool:
    """JWT 'solto' (sem 'Bearer '), como costuma aparecer fora do cabeçalho."""
    return bool(_JWT_RE.match(token or ""))


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_updated(value: str) -> Optional[dt.datetime]:
    try:
        parsed = dateparser.isoparse(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _refresh_fields(raw: Dict[str, Any]) -> Tuple[Optional[bool], Optional[str]]:
    """Lê apenas sinais explícitos; ausência não significa um cooldown de 24h."""
    sources = [raw]
    for key in ("refresh", "relist", "refresh_status", "refreshStatus"):
        part = raw.get(key)
        if isinstance(part, dict):
            sources.append(part)
    allowed, available_at = None, None
    for source in sources:
        for key in _REFRESH_TRUE:
            if allowed is None and type(source.get(key)) is bool:
                allowed = source[key]
        for key in _REFRESH_TIMES:
            value = source.get(key)
            if available_at is None and isinstance(value, str) and parse_updated(value) is not None:
                available_at = value
    return allowed, available_at



# Categorias exibidas no menu oficial do Traderie, separadas do modo Slot/Species.
CATEGORY_ALIASES = {
    "creatures": "species", "creature": "species", "species": "species",
    "sub-species": "species", "subspecies": "species", "sub_species": "species",
    "plushies": "plushies", "plushie": "plushies", "plush": "plushies",
    "palettes": "palettes", "palette": "palettes", "material palettes": "palettes",
    "material-palettes": "palettes", "material_palettes": "palettes",
}


def item_category(raw: Any) -> str:
    """Classifica pelo campo de categoria, não pelo texto livre do nome."""
    if not isinstance(raw, dict):
        return "other"
    possible = [raw.get(k) for k in ("category", "category_slug", "categorySlug", "itemType", "item_type", "type")]
    if isinstance(raw.get('categories'), list):
        possible += raw['categories']
    for value in possible:
        if isinstance(value, dict):
            value = value.get('slug') or value.get('name') or value.get('type')
        if isinstance(value, str):
            found = CATEGORY_ALIASES.get(value.strip().lower())
            if found:
                return found
    return "other"


def listing_category(raw: dict, item: dict, properties: dict) -> str:
    category = item_category(item)
    if category == 'other':
        category = item_category(raw)
    if category not in ('plushies', 'palettes'):
        for prop in properties.values():
            if 'species or slot' in prop.name.lower() or 'species or stored' in prop.name.lower():
                return 'slots' if prop.value.strip().lower() in ('slot', 'stored') else 'species'
    if category == 'other':
        name = str(item.get('name') or '').strip().lower()
        if name.endswith(' plushie'):
            return 'plushies'
        if name.endswith(' palette'):
            return 'palettes'
    return category


def relist_eta(listing: Listing, now: Optional[dt.datetime] = None) -> Optional[dt.timedelta]:
    """Disponibilidade explícita ou momento confirmado; None se desconhecida."""
    if listing.can_refresh is True:
        return dt.timedelta(0)
    ready = parse_updated(listing.refresh_available_at)
    if ready is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return max(dt.timedelta(0), ready - now)


def is_listing_relistable(listing: Listing, now: Optional[dt.datetime] = None) -> bool:
    """Só republica se a API declarar disponibilidade, nunca pela idade do anúncio."""
    if listing.can_refresh is not None:
        return listing.can_refresh
    eta = relist_eta(listing, now)
    return eta is not None and eta <= dt.timedelta(0)


def parse_listing_property(raw: Dict[str, Any]) -> Optional[ListingProperty]:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind not in ("string", "number", "bool") or kind not in raw:
        logger.warning("Tipo de propriedade desconhecido: %r", kind)
        return None
    return ListingProperty(id=raw.get("id"), name=str(raw.get("property") or raw.get("name") or "Propriedade"), value=str(raw.get(kind)), type=kind, icon_url=normalize_image_url(raw.get("icon_url") or raw.get("icon") or raw.get("image_url")))


# Extrai apenas URLs apontadas por campos de arte. Não trata a URL de um
# anúncio, avatar ou link genérico como imagem e nunca envia Authorization.
_IMAGE_FIELDS = ("image_url", "imageUrl", "thumbnail_url", "thumbnailUrl", "icon_url",
                 "image", "icon", "thumbnail", "images", "icons", "art", "artwork",
                 "media", "cover", "picture", "photo", "img", "image_large", "image_small",
                 "full", "original", "large", "small", "url", "src", "cdnUrl", "path")


def normalize_image_url(raw: Any) -> Optional[str]:
    from urllib.parse import urlsplit
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if url.startswith('//'):
        return None  # rejeita URL scheme-relative potencialmente não confiável
    elif url.startswith('/'):
        url = 'https://traderie.com' + url
    elif url.startswith('data:') or url.startswith('blob:'):
        return None
    if not url.startswith('https://') or len(url) > 1800:
        return None
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        return None
    # Não permite URLs locais, IPs privados nem URLs que contêm credenciais.
    import ipaddress
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if parsed.hostname.lower() in ('localhost', 'localhost.localdomain') or '.' not in parsed.hostname:
            return None
    else:
        if not ip.is_global:
            return None
    return url


def find_item_image(raw: Any, *, restricted: bool = False, max_depth: int = 5) -> Optional[str]:
    """Aceita campos de arte aninhados, variantes do CDN e URL relativa."""
    def walk(value: Any, depth: int, in_image: bool) -> Optional[str]:
        if depth > max_depth:
            return None
        if isinstance(value, str):
            return normalize_image_url(value) if in_image else None
        if isinstance(value, list):
            for part in value[:16]:
                found = walk(part, depth+1, in_image)
                if found:
                    return found
        elif isinstance(value, dict):
            keys = ("image_url", "imageUrl", "thumbnail_url", "thumbnailUrl", "icon_url",
                    "image", "icon", "thumbnail", "images", "icons", "art", "artwork", "img",
                    "picture", "photo", "media", "cover", "cdnUrl", "image_large", "image_small")
            for key in keys:
                if key in value and (found := walk(value[key], depth+1, True)):
                    return found
            if in_image:
                for key in ("url", "src", "path", "original", "large", "small", "full", "default"):
                    if key in value and (found := walk(value[key], depth+1, True)):
                        return found
            if not restricted:
                for key in ("item", "data", "attributes", "metadata", "assets", "details"):
                    if key in value and (found := walk(value[key], depth+1, False)):
                        return found
        return None
    return walk(raw, 0, False)


def parse_listing(raw: Dict[str, Any]) -> Optional[Listing]:
    if not isinstance(raw, dict):
        logger.warning("Anúncio com formato inesperado.")
        return None
    try:
        listing_id = int(raw["id"])
        updated = raw["updated_at"]
    except (KeyError, TypeError, ValueError):
        logger.warning("Anúncio sem id/updated_at: %r", raw)
        return None
    item = raw.get("item") or {}
    if not isinstance(item, dict):
        item = {}
    image_url = find_item_image(item) or find_item_image(raw, restricted=True)
    can_refresh, refresh_available_at = _refresh_fields(raw)
    lst = Listing(
        listingID=listing_id,
        updated=updated,
        itemName=item.get("name") or raw.get("item_name"),
        amount=_int(raw.get("amount")),
        image_url=image_url,
        itemID=_int(item.get("id")) or _int(raw.get("item_id")),
        can_refresh=can_refresh,
        refresh_available_at=refresh_available_at,
    )
    props = raw.get("properties") or []
    if isinstance(props, list):
        for prop in props:
            if not isinstance(prop, dict):
                continue
            parsed = parse_listing_property(prop)
            if parsed is not None:
                lst.properties[parsed.name] = parsed
    lst.item_category = listing_category(raw, item, lst.properties)
    return lst


def parse_offer(raw: Dict[str, Any]) -> Optional[Offer]:
    try:
        listing = raw["listing"]
        return Offer(
            itemName=(listing.get("item") or {}).get("name") or "Item",
            offerID=int(raw["id"]),
            listingID=int(listing["id"]),
            sellerID=int(listing["seller"]["id"]),
            sellerUsername=listing["seller"].get("username", ""),
            buyerID=int(raw["buyer"]["id"]),
            buyerUsername=raw["buyer"].get("username", ""),
            amount=int(listing.get("amount") or 1),
            itemID=int(listing["item"]["id"]),
            image_url=find_item_image(listing.get("item") or {}) or find_item_image(listing, restricted=True),
            item_category=listing_category(listing, listing.get("item") or {}, {
                p.name: p for p in (
                    parse_listing_property(p) for p in (listing.get("properties") or [])
                    if isinstance(p, dict)
                ) if p is not None
            }),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        logger.warning("Oferta com formato inesperado: %r", raw)
        return None



# O contrato abaixo foi extraído de requisições de criação/exclusão capturadas
# pelo usuário. O servidor pode rejeitar outros formatos sem aviso.
CREATE_DEFAULTS = {
    "acceptListingPrice": False, "captcha": "", "captchaManaged": False,
    "diy": False, "endTime": "", "free": False, "itemMode": None,
    "itemType": "sub-species", "makeOffer": True,
    "needMaterials": False, "offerBells": False, "offerNmt": False,
    "offerWishlist": False, "offerWishlistId": "", "selling": True,
    "standingListing": False, "stockListing": False,
    "touchTrading": False, "wishlist": "", "properties": [],
}
ALLOWED_CREATE_KEYS = frozenset(CREATE_DEFAULTS) | {"item", "amount", "currencyGroupPrices"}


def validated_creation(raw: Any) -> dict:
    """Normaliza uma configuração de anúncio usando os campos observados.

    Não aceita chaves arbitrárias nem payloads com credenciais; não resolve captcha
    automaticamente. O endpoint somente será invocado por uma ação autenticada.
    """
    if not isinstance(raw, dict):
        raise ValueError("O modelo de anúncio deve ser um objeto JSON.")
    extra = set(raw) - ALLOWED_CREATE_KEYS
    if extra:
        raise ValueError("Campos de anúncio não reconhecidos: " + ", ".join(sorted(extra)))
    out = {**CREATE_DEFAULTS, **raw}
    item = str(out.get("item") or "")
    if not item.isdigit() or int(item) <= 0:
        raise ValueError("Informe o ID numérico do item no Traderie.")
    amount = str(out.get("amount") or "")
    if not amount.isdigit() or not 1 <= int(amount) <= 999:
        raise ValueError("Quantidade precisa ser de 1 a 999.")
    out["item"], out["amount"] = item, amount
    if not isinstance(out["itemType"], str) or not 1 <= len(out["itemType"]) <= 80:
        raise ValueError("Tipo de item inválido.")
    for key, value in out.items():
        if isinstance(CREATE_DEFAULTS.get(key), bool) and not isinstance(value, bool):
            raise ValueError(f"'{key}' deve ser verdadeiro ou falso.")
    # Traderie creation payload supplied by the user, 2026-10-15.
    # CoS Shooms are represented as nmt in the shared currency schema.
    prices = out.get("currencyGroupPrices")
    if out["acceptListingPrice"]:
        if out["makeOffer"] or out["free"]:
            raise ValueError("Preço fixo não pode ser combinado com ofertas ou anúncio gratuito.")
        if not isinstance(prices, list) or len(prices) != 1:
            raise ValueError("Informe um preço fixo em Shooms.")
        price = prices[0]
        if (not isinstance(price, dict) or set(price) != {"group", "nmt", "currency"}
                or type(price["group"]) is not int or price["group"] != 0
                or price["currency"] is not True
                or type(price["nmt"]) is not int or not 1 <= price["nmt"] <= 999999999):
            raise ValueError("Preço em Shooms deve ser inteiro, entre 1 e 999999999.")
        out["currencyGroupPrices"] = [dict(price)]
    elif prices is not None:
        raise ValueError("Remova o preço ao escolher receber ofertas.")
    elif not out["makeOffer"] and not out["free"]:
        raise ValueError("Escolha receber ofertas ou um preço fixo válido.")
    if not out["selling"]:
        raise ValueError("Somente anúncios de venda são aceitos.")
    if out["captcha"] or out["captchaManaged"]:
        raise ValueError("CAPTCHA precisa ser tratado manualmente no site.")
    for key in ("endTime", "offerWishlistId", "wishlist"):
        if not isinstance(out[key], str) or len(out[key]) > 500:
            raise ValueError(f"Campo '{key}' inválido.")
    if out["itemMode"] is not None and not isinstance(out["itemMode"], (str, int)):
        raise ValueError("Campo itemMode inválido.")
    props = out["properties"]
    if not isinstance(props, list) or len(props) > 32:
        raise ValueError("Informe até 32 propriedades em uma lista.")
    validated = []
    for prop in props:
        if not isinstance(prop, dict) or not set(prop) <= {"id", "name", "type", "string", "number", "bool"}:
            raise ValueError("Formato de propriedade inválido.")
        if isinstance(prop.get("id"), bool) or str(prop.get("id") or "").lstrip("-").isdigit() is False:
            raise ValueError("Propriedade sem ID numérico.")
        kind = prop.get("type")
        if kind not in ("string", "number", "bool") or kind not in prop:
            raise ValueError("Propriedade precisa de type e valor correspondente.")
        if not isinstance(prop.get("name"), str) or not prop["name"].strip():
            raise ValueError("Propriedade sem nome.")
        if len(prop["name"]) > 180:
            raise ValueError("Nome de propriedade muito longo.")
        val = prop[kind]
        if kind == "string" and (not isinstance(val, str) or len(val) > 1000):
            raise ValueError("Valor string de propriedade inválido.")
        if kind == "number" and (isinstance(val, bool) or not isinstance(val, (int, float))):
            raise ValueError("Valor numérico de propriedade inválido.")
        if kind == "bool" and not isinstance(val, bool):
            raise ValueError("Valor booleano de propriedade inválido.")
        validated.append({"id": int(prop["id"]), "name": prop["name"], "type": kind, kind: val})
    out["properties"] = validated
    if out["stockListing"] or out["standingListing"]:
        raise ValueError("Anúncios de estoque/permanentes não são suportados pelas rotinas.")
    return out


def created_listing_id(data: dict) -> Optional[int]:
    """Aceita formatos usuais, sem presumir que uma resposta desconhecida foi sucesso."""
    for candidate in (data.get("listing"), data.get("data"), data.get("listing_id"), data.get("listingID")):
        if isinstance(candidate, dict):
            candidate = candidate.get("id") or candidate.get("listingID")
        if candidate is not None and str(candidate).isdigit():
            return int(candidate)
    # O identificador raiz pode ser um anúncio, mas só quando a API confirma sucesso.
    if (data.get("success") is True or data.get("msg") == "success") and str(data.get("id", "")).isdigit():
        return int(data["id"])
    return None

def _is_antibot(resp: requests.Response) -> bool:
    """Detecta a página de desafio do Cloudflare & cia (HTML em vez de JSON)."""
    headers = resp.headers or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True
    ctype = str(headers.get("Content-Type", "")).lower()
    if "html" not in ctype:
        return False
    text = (getattr(resp, "text", "") or "")[:3000].lower()
    return any(m in text for m in ("just a moment", "cf-chl", "attention required", "cloudflare"))


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------
def refresh_cooldown_minutes(profile, slug=DEFAULT_SLUG):
    """Rules observed in the public site bundle index-uqDPzEb-.js.

    Role names and game/site scopes follow the site's permission evaluator.
    This is a readiness schedule, not authorization for the server operation.
    """
    fast = {'admin', 'lead-mod', 'senior-mod', 'mod', 'mod-perks', 'prime', 'epic', 'investor', 'legendary'}
    six_hour = {'patron', 'champion'}
    global_roles = {'admin', 'mod-perks', 'prime', 'epic', 'investor', 'legendary', 'patron', 'champion'}
    minutes = 1080 if (_int(profile.get('reviews')) or 0) >= 1000 else 1200
    roles = profile.get('roles') or []
    for role in roles if isinstance(roles, list) else []:
        title = role.get('title', '') if isinstance(role, dict) else ''
        if not isinstance(title, str):
            continue
        name, sep, scope = title.partition('_')
        if sep and name not in global_roles and scope not in (slug, 'traderie'):
            continue
        if name in fast:
            minutes = min(minutes, 30)
        elif name in six_hour:
            minutes = min(minutes, 360)
    return minutes


def normalize_catalog_item(raw):
    if not isinstance(raw, dict):
        return None
    iid, name = _int(raw.get('id')), raw.get('name')
    if isinstance(raw.get('id'), bool) or not iid or not 0 < iid < 2**53 or not isinstance(name, str) or not name.strip():
        return None
    properties = []
    for prop in (raw.get('properties') or []) if isinstance(raw.get('properties'), list) else []:
        if not isinstance(prop, dict):
            continue
        pid, label = _int(prop.get('id') or prop.get('property_id')), prop.get('name') or prop.get('property')
        kind = prop.get('type') or 'string'
        if not pid or not isinstance(label, str) or kind not in ('string', 'number', 'bool'):
            continue
        options = prop.get('options') or prop.get('values') or []
        if not isinstance(options, list):
            options = []
        options = [x.get('value') if isinstance(x, dict) else x for x in options[:500]]
        options = [str(x).lower() if isinstance(x, bool) else str(x)[:120] for x in options if x is not None]
        fmt = prop.get('format') if isinstance(prop.get('format'), dict) else {}
        group = fmt.get('group') or {}
        group = group.get('name', '') if isinstance(group, dict) else str(group)
        parent = next((p for p in raw.get('properties', []) if isinstance(p, dict) and p.get('name') == group), {})
        parent_fmt = parent.get('format') or {}
        properties.append({'id': pid, 'name': label[:180], 'type': kind, 'options': options,
                           'group': group, 'group_limit': parent_fmt.get('limit') if isinstance(parent_fmt, dict) else None,
                           'required': prop.get('required') is True})
    return {'id': iid, 'name': name.strip()[:160], 'category': item_category(raw),
            'item_type': raw.get('type') or raw.get('itemType'),
            'image_url': find_item_image(raw), 'properties': properties, 'source': 'Catálogo oficial'}


class TraderieClient:
    """Cliente thread-safe. Uma instância por configuração (slug + token)."""

    MIN_INTERVAL = 0.3  # segundos entre requisições (educação com o servidor)
    GET_RETRIES = 2

    def __init__(self, slug: str = DEFAULT_SLUG, auth: Optional[str] = None, timeout: float = 15.0,
                 policy: Optional[Dict[str, str]] = None):
        self.slug = clean_slug(slug)
        self._auth = clean_token(auth)
        self._auth_value = self._auth     # valor realmente enviado (pode ganhar 'Bearer ')
        self.timeout = timeout
        self.policy = default_policy()
        self.apply_policy(policy or {})
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._catalog_unavailable = False
        self._refresh_profile = None

    # ---- token ------------------------------------------------------------
    @property
    def auth(self) -> str:
        return self._auth

    @auth.setter
    def auth(self, value: Optional[str]) -> None:
        self._auth = clean_token(value)
        self._auth_value = self._auth

    @property
    def has_auth(self) -> bool:
        return bool(self._auth)

    # ---- política ---------------------------------------------------------
    def apply_policy(self, overrides: Dict[str, str]) -> None:
        """Só leituras (PROBEABLE) podem mudar de política; escritas ficam privadas."""
        for key, value in (overrides or {}).items():
            if key in PROBEABLE and value in ("public", "private"):
                self.policy[key] = value

    def available(self, key: str) -> bool:
        """A ação pode ser tentada agora? (token presente ou endpoint público)"""
        return self.has_auth or self.policy.get(key) == "public"

    # ---- núcleo -----------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{BASE_URL}/{self.slug}/{path.lstrip('/')}"

    def _throttle(self) -> None:
        with self._lock:
            wait = self.MIN_INTERVAL - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _send(self, key: str, auth_value: str, *, params: Optional[dict], body: Optional[dict]) -> Dict[str, Any]:
        method, path, _ = ENDPOINTS[key]
        headers = {"Authorization": auth_value} if auth_value else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        attempts = 1 + (self.GET_RETRIES if method == "GET" else 0)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            self._throttle()
            try:
                resp = self._session.request(method, self._url(path), params=params, json=body,
                                             headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("%s %s falhou (%s), tentativa %d/%d", method, path, exc, attempt + 1, attempts)
                if attempt + 1 < attempts:
                    time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts and not _is_antibot(resp):
                delay = _int(resp.headers.get("Retry-After")) or 2 * (attempt + 1)
                time.sleep(min(delay, 30))
                continue
            return self._handle(resp, method, path)
        raise TraderieError(f"Sem conexão com o Traderie: {last_exc}")

    def _request(self, key: str, *, params: Optional[dict] = None, body: Optional[dict] = None) -> Dict[str, Any]:
        """Executa a chamada e devolve o JSON (dict). Levanta TraderieError."""
        if self.policy.get(key) == "private" and not self.has_auth:
            raise AuthRequired("Esta ação precisa do token Authorization (cole-o na conexão).")
        try:
            return self._send(key, self._auth_value, params=params, body=body)
        except AuthRequired:
            # Token JWT solto pode precisar do prefixo 'Bearer ' (depende de como foi copiado).
            if self.has_auth and self._auth_value == self._auth and looks_like_bare_jwt(self._auth):
                alt = f"Bearer {self._auth}"
                result = self._send(key, alt, params=params, body=body)  # se falhar, propaga
                self._auth_value = alt
                logger.info("O servidor aceitou o token com o prefixo 'Bearer '.")
                return result
            raise

    @staticmethod
    def _handle(resp: requests.Response, method: str, path: str) -> Dict[str, Any]:
        status = resp.status_code
        if _is_antibot(resp):
            raise Blocked(
                f"O Traderie respondeu com uma página anti-bot ({status}) em {method} {path}. "
                "Abra o site no navegador, resolva a verificação e tente de novo; "
                "se persistir, o acesso por script está sendo bloqueado.", status)
        if status in (401, 403):
            raise AuthRequired(f"O Traderie recusou a requisição ({status}): token ausente, expirado ou sem permissão.", status)
        if status == 404:
            raise TraderieError(f"Endpoint não encontrado (404): {method} {path}. Confira o slug do jogo.", status)
        if status == 429:
            from email.utils import parsedate_to_datetime
            retry = resp.headers.get('Retry-After', '60')
            try:
                seconds = int(retry)
            except (ValueError, TypeError):
                try:
                    seconds = (parsedate_to_datetime(retry) - dt.datetime.now(dt.timezone.utc)).total_seconds()
                except (ValueError, TypeError, OverflowError):
                    seconds = 60
            error = TraderieError("Muitas requisições (429). Aguarde a próxima verificação.", status)
            error.retry_after = max(1, seconds)
            raise error
        if status >= 400:
            raise TraderieError(f"Erro {status} em {method} {path}: {resp.reason}", status)
        try:
            data = resp.json()
        except ValueError:
            raise TraderieError(f"Resposta não é JSON em {method} {path}.", status)
        if not isinstance(data, dict):
            raise TraderieError(f"Formato inesperado em {method} {path}.", status)
        return data

    @staticmethod
    def _require_ok(data: Dict[str, Any], what: str, strict: bool = True) -> None:
        """Valida respostas de escrita: {"msg":"success"} ou {"success":true}."""
        if data.get("error"):
            raise TraderieError(f"{what}: {data['error']}")
        if data.get("msg") == "success" or data.get("success") is True:
            return
        if strict:
            raise TraderieError(f"{what}: resposta inesperada da API ({str(data)[:120]}).")

    @staticmethod
    def _list(data: Dict[str, Any], key: str, what: str) -> list:
        value = data.get(key)
        if not isinstance(value, list):
            raise TraderieError(f"Resposta de {what} inválida.")
        return value

    def search_catalog_items(self, text: str = '', limit: int = 50, *, category=None, page=0) -> list:
        """Official item autocomplete, verified with live public responses."""
        if not isinstance(text, str) or len(text.strip()) > 80:
            raise ValueError("Pesquise usando até 80 caracteres.")
        types = {'species': 'Creatures', 'slots': 'Creatures', 'plushies': 'plushies', 'palettes': 'palettes'}
        params = {'search': text.strip(), 'active': 'true', 'properties': '', 'variants': '', 'page': str(page)}
        if category:
            if category not in types:
                raise ValueError('Categoria inválida.')
            params['type'] = types[category]
        self._throttle()
        try:
            response = self._session.get(self._url('items'), params=params,
                headers={'Accept': 'application/json'}, timeout=min(self.timeout, 12), allow_redirects=False)
        except requests.RequestException:
            raise TraderieError('Não foi possível acessar o catálogo. Verifique a conexão com Traderie.') from None
        data = self._handle(response, 'GET', 'items')
        entries = data.get('items')
        if not isinstance(entries, list):
            raise TraderieError('Formato do catálogo não reconhecido.')
        return [row for raw in entries[:100] if (row := normalize_catalog_item(raw))][:limit]

    # ---- leituras ---------------------------------------------------------
    def search_user(self, username: str) -> Optional[int]:
        data = self._request("users", params={"username": username})
        wanted = username.strip().lower()
        for user in self._list(data, "users", "busca de usuário"):
            if str(user.get("username", "")).lower() == wanted and user.get("id") is not None:
                return int(user["id"])
        return None

    def get_status(self, user_id: int) -> str:
        data = self._request("accounts", params={"user": user_id})
        user = data.get("user") or {}
        status = user.get("status")
        if status is None:
            raise TraderieError("Resposta de status inválida (conta inexistente?).")
        if "reviews" in user and "roles" in user:
            self._refresh_profile = (user_id, time.monotonic(), {"reviews": user["reviews"], "roles": user["roles"]})
        return status

    def get_listings_page(self, seller: int, page: int, include_completed: bool = False) -> Dict[int, Listing]:
        params = {
            "selling": "true", "auction": "false", "page": str(page), "seller": str(seller),
            "completed": "all" if include_completed else "false", "active": "all",
        }
        data = self._request("listings", params=params)
        parsed = (parse_listing(raw) for raw in self._list(data, "listings", "anúncios"))
        return {l.listingID: l for l in parsed if l is not None}

    def get_all_listings(self, seller: int, include_completed: bool = False) -> Dict[int, Listing]:
        """Percorre as páginas até vir uma vazia ou sem nenhum anúncio novo.

        Não assumimos o tamanho da página (o original fixava 50, o que cortaria a
        lista se o jogo usar outro valor); custa uma requisição a mais.
        """
        listings: Dict[int, Listing] = {}
        for page in range(MAX_PAGES):
            chunk = self.get_listings_page(seller, page, include_completed)
            new = set(chunk) - set(listings)
            if not new:  # vazia, ou a API ignorou 'page' e repetiu itens
                break
            listings.update(chunk)
        else:
            logger.warning("Limite de %d páginas atingido; a lista pode estar incompleta.", MAX_PAGES)
        self.apply_refresh_schedule(listings, seller)
        return listings

    def apply_refresh_schedule(self, listings, seller):
        """Fallback matches Traderie's current Relist button (2026-10-15).

        Server flags override this schedule. A successful refresh still needs
        explicit acceptance from the server; timestamps are not fabricated.
        """
        if not any(l.can_refresh is None and not l.refresh_available_at for l in listings.values()):
            return
        cached = self._refresh_profile
        if not cached or cached[0] != seller or time.monotonic()-cached[1] > 300:
            try:
                self.get_status(seller)
            except TraderieError:
                return  # Without a readable profile the schedule is unknown.
        if not self._refresh_profile or self._refresh_profile[0] != seller:
            return
        minutes = refresh_cooldown_minutes(self._refresh_profile[2], self.slug)
        for listing in listings.values():
            updated = parse_updated(listing.updated)
            if listing.can_refresh is None and not listing.refresh_available_at and updated:
                listing.refresh_available_at = (updated + dt.timedelta(minutes=minutes)).isoformat()
                listing.availability_source = 'site_rule'

    def get_listing(self, listing_id: int) -> Optional[Listing]:
        params = {"selling": "true", "completed": "all", "active": "all", "id": listing_id}
        raw = self._list(self._request("listings", params=params), "listings", "anúncio")
        return parse_listing(raw[0]) if raw else None

    def get_catalog_image(self, item_id: int) -> Optional[str]:
        """Leitura opcional: nem todas as versões da API disponibilizam /items.

        Nunca usa o token ou inventa uma URL de arte a partir do ID.
        """
        if self._catalog_unavailable:
            return None
        self._throttle()
        try:
            response = self._session.get(self._url('items'), params={'id': str(item_id)},
                                         headers={'Accept': 'application/json'}, timeout=min(self.timeout, 8))
        except requests.RequestException:
            self._catalog_unavailable = True
            return None
        if response.status_code in (401, 403, 404, 429) or _is_antibot(response):
            # A consulta ao catálogo é opcional. Sem acesso, nunca insistir
            # neste endpoint nesta conexão nem tentar contornar o bloqueio.
            self._catalog_unavailable = True
            return None
        if response.status_code != 200:
            self._catalog_unavailable = True
            return None
        try:
            data = response.json()
        except ValueError:
            self._catalog_unavailable = True
            return None
        if not isinstance(data, dict):
            self._catalog_unavailable = True
            return None
        results = data.get('items') or data.get('item') or data.get('data') or []
        if isinstance(results, dict):
            results = [results]
        if not isinstance(results, list):
            return None
        for item in results[:30]:
            if isinstance(item, dict) and _int(item.get('id')) == item_id:
                return find_item_image(item)
        return None

    def get_offers(self, *, to_seller: Optional[int] = None, from_user: Optional[int] = None) -> Dict[int, Offer]:
        if (to_seller is None) == (from_user is None):
            raise ValueError("Informe exatamente um entre to_seller e from_user.")
        params: Dict[str, Any] = {"accepted": "open"}
        params.update({"seller": to_seller} if to_seller is not None else {"user": from_user})
        data = self._request("offers", params=params)
        parsed = (parse_offer(raw) for raw in self._list(data, "offers", "ofertas"))
        return {o.offerID: o for o in parsed if o is not None}

    def get_notifications(self, new: bool = False, limit: int = 30) -> List[Notification]:
        params: Dict[str, Any] = {"limit": limit}
        if new:
            params["new"] = ""
        data = self._request("notifications", params=params)
        out = []
        for n in self._list(data, "notifications", "notificações"):
            try:
                out.append(Notification(
                    notificationID=n["id"], text=n["message"], date=n["created_at"],
                    fromUserID=_int(n.get("from_user_id")),
                    listingID=_int((n.get("data") or {}).get("listing_id")),
                ))
            except (KeyError, TypeError, AttributeError):
                logger.warning("Notificação com formato inesperado: %r", n)
        return out

    def get_conversations(self, active: bool, own_user_id: int) -> Dict[int, Conversation]:
        data = self._request("conversations", params={"active": "true" if active else "false"})
        out: Dict[int, Conversation] = {}
        for c in self._list(data, "conversations", "conversas"):
            partner = next((_int(u) for u in c.get("users") or [] if _int(u) != own_user_id), None)
            cid = _int(c.get("id"))
            if partner is None or cid is None:
                logger.warning("Conversa com formato inesperado: %r", c)
                continue
            out[partner] = Conversation(conversationID=cid, userID=partner)
        return out

    def get_messages(self, from_user_id: int, conversation_id: int, limit: int = 50) -> List[Message]:
        params = {"user": from_user_id, "limit": limit, "convoId": conversation_id}
        data = self._request("messages", params=params)
        out = []
        for m in self._list(data, "messages", "mensagens"):
            try:
                out.append(Message(msgID=m["id"], text=m["content"], toID=int(m["to"]), fromID=int(m["from"])))
            except (KeyError, TypeError, ValueError):
                logger.warning("Mensagem com formato inesperado: %r", m)
        return out

    # ---- escritas (sempre exigem token) ----------------------------------
    def set_status(self, status: str) -> None:
        data = self._request("accounts.update", body={"status": status})
        self._require_ok(data, f"Alterar status para {status}")

    def relist(self, listing_id: int) -> None:
        data = self._request("listings.refresh", body={"listing": str(listing_id)})
        self._require_ok(data, f"Republicar anúncio {listing_id}")

    def create_listing(self, template: dict) -> Optional[int]:
        """Envia POST /listings/create e devolve ID quando fornecido pelo site."""
        data = self._request("listings.create", body=validated_creation(template))
        # Create pode retornar o novo anúncio sem a chave msg: success.
        lid = created_listing_id(data)
        if lid is None:
            self._require_ok(data, "Criar anúncio")
        elif data.get("error"):
            raise TraderieError(f"Criar anúncio: {data['error']}")
        return lid

    def delete_listing(self, listing_id: int) -> None:
        if isinstance(listing_id, bool) or int(listing_id) <= 0:
            raise ValueError("ID do anúncio inválido.")
        data = self._request("listings.delete", body={
            "listing": str(listing_id), "selling": True, "remove": True, "endTime": None,
        })
        # Confirmação estrita: nunca marque como removido após resposta ambígua.
        self._require_ok(data, f"Excluir anúncio {listing_id}")

    def mark_notifications_read(self, notification_ids: List[str]) -> None:
        data = self._request("notifications.read", body={"newNotifications": list(notification_ids)})
        self._require_ok(data, "Marcar notificações como lidas")

    def decline_offer(self, offer: Offer, reason: str = "the offer was too low") -> None:
        body = {"offer": offer.offerID, "buyer": str(offer.buyerID), "listing": offer.listingID, "reason": reason}
        self._require_ok(self._request("offers.deny", body=body), "Recusar oferta")

    def accept_offer(self, offer: Offer, *, is_auction: bool = False,
                     parent_user: Optional[int] = None, offer_amount: Optional[int] = None) -> None:
        body = {
            "offer": offer.offerID, "parent_user": parent_user, "buyer": offer.buyerID,
            "listing": offer.listingID, "amount": offer.amount, "item": offer.itemID,
            "isAuction": is_auction, "offerAmount": offer_amount,
        }
        self._require_ok(self._request("offers.accept", body=body), "Aceitar oferta")

    def open_conversation(self, user_id: int, username: str, offer_id: int) -> None:
        body = {"to": str(user_id), "toUsername": username, "offer": offer_id}
        self._require_ok(self._request("conversations.create", body=body), "Abrir conversa")

    def send_message(self, user_id: int, text: str) -> None:
        # O site envia o payload dentro de "body"; mantido como no bot original.
        data = self._request("messages.send", body={"body": {"to": str(user_id), "content": text}})
        self._require_ok(data, "Enviar mensagem")

    def set_conversation_active(self, conversation_id: int, active: bool) -> None:
        data = self._request("conversations.update", body={"id": str(conversation_id), "active": active})
        self._require_ok(data, "Atualizar conversa", strict=False)

    def send_review(self, user_id: int, stars: int, description: str) -> None:
        body = {"rating": stars, "description": description, "user": str(user_id)}
        self._require_ok(self._request("reviews.add", body=body), "Enviar avaliação", strict=False)

    def block_user(self, user_id: int) -> None:
        self._require_ok(self._request("blocks.add", body={"user": str(user_id)}), "Bloquear usuário", strict=False)

    # ---- diagnóstico (somente leitura) --------------------------------------
    def _probe_params(self, key: str, uid: int) -> dict:
        return {
            "accounts": {"user": uid},
            "listings": {"selling": "true", "auction": "false", "page": "0", "seller": str(uid),
                         "completed": "false", "active": "all"},
            "offers": {"accepted": "open", "seller": uid},
            "notifications": {"limit": 5},
            "conversations": {"active": "true"},
        }[key]

    def _probe_one(self, key: str, uid: int, with_token: bool) -> Probe:
        """GET cru, sem a checagem local de política: mostra o que o servidor diz."""
        _m, path, _p = ENDPOINTS[key]
        headers = {"Authorization": self._auth_value} if with_token and self.has_auth else {}
        self._throttle()
        try:
            resp = self._session.get(self._url(path), params=self._probe_params(key, uid),
                                     headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            return Probe(key, None, "network", detail=str(exc)[:120])
        status = resp.status_code
        if _is_antibot(resp):
            return Probe(key, status, "blocked", detail="página anti-bot")
        if status in (401, 403):
            return Probe(key, status, "auth")
        if status == 404:
            return Probe(key, status, "notfound")
        if status >= 400:
            return Probe(key, status, "error", detail=str(resp.reason))
        try:
            data = resp.json()
        except ValueError:
            return Probe(key, status, "error", detail="resposta não é JSON")
        count = None
        if isinstance(data, dict):
            lists = [v for v in data.values() if isinstance(v, list)]
            count = len(lists[0]) if lists else None
        return Probe(key, status, "ok", count=count)

    def diagnose(self, user_id: int) -> List[Dict[str, Any]]:
        """Chama as leituras sem token e (se houver) com token; ajusta a política.

        Regras (conservadoras):
          * sem token deu 401/403           -> private
          * sem token e com token OK e iguais -> public
          * sem token OK mas sem token para comparar -> política inalterada
            (um 200 vazio não prova que o endpoint é público)
        """
        rows: List[Dict[str, Any]] = []
        for key in PROBEABLE:
            anon = self._probe_one(key, user_id, with_token=False)
            tok = self._probe_one(key, user_id, with_token=True) if self.has_auth else None
            if anon.verdict == "auth":
                note, new = "exige token", "private"
            elif anon.verdict == "ok" and tok is not None and tok.verdict == "ok":
                if anon.count == tok.count:
                    note, new = "funciona sem token", "public"
                else:
                    note, new = f"sem token vem incompleto ({anon.count} x {tok.count})", "private"
            elif anon.verdict == "ok":
                note, new = "respondeu sem token (informe um token para confirmar)", None
            elif anon.verdict == "blocked":
                note, new = "bloqueado por anti-bot", None
            else:
                note, new = f"{anon.verdict} {anon.detail}".strip(), None
            if new:
                self.policy[key] = new
            rows.append({
                "endpoint": key, "policy": self.policy[key], "note": note,
                "anon": {"status": anon.status, "verdict": anon.verdict, "count": anon.count},
                "token": ({"status": tok.status, "verdict": tok.verdict, "count": tok.count} if tok else None),
            })
        return rows
