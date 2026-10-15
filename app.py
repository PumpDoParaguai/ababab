"""Painel local do Traderie (Creatures of Sonaria). GPL-3.0-or-later.

Roda só em 127.0.0.1. O token Authorization é OPCIONAL e fica apenas na memória
(ou na variável de ambiente TRADERIE_AUTH, se você preferir). Sem ele o painel
funciona nos endpoints que o servidor aceita sem login; o botão "Testar
endpoints" descobre quais são.
"""
from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
import logging
import os
import tempfile
import threading
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, request, send_from_directory

import traderie
from traderie import AuthRequired, TraderieClient, TraderieError

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"           # slug, usuário, intervalo (SEM token)
POLICY_FILE = BASE_DIR / "endpoint_auth.json"    # resultado do diagnóstico (SEM token)
ROTATIONS_FILE = BASE_DIR / "rotation_routines.json"
IMAGES_FILE = BASE_DIR / "item_images.json"  # URLs públicas associadas aos itens, nunca tokens

HOST, PORT = "127.0.0.1", 8765
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}

app = Flask(__name__, static_folder=str(BASE_DIR / "static"), static_url_path="/static")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


# --------------------------------------------------------------------------
# Arquivos de configuração (nunca contêm o token)
# --------------------------------------------------------------------------
def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    """Escrita atômica; falhar ao salvar nunca derruba o painel."""
    try:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("Não foi possível gravar %s: %s", path.name, exc)


def load_policy(slug: str) -> Dict[str, str]:
    return _read_json(POLICY_FILE).get(slug, {})


def save_policy(client: TraderieClient) -> None:
    data = _read_json(POLICY_FILE)
    data[client.slug] = {k: client.policy[k] for k in traderie.PROBEABLE}
    _write_json(POLICY_FILE, data)


# --------------------------------------------------------------------------
# Estado (protegido por lock). O token nunca sai daqui.
# --------------------------------------------------------------------------
class State:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.client: Optional[TraderieClient] = None
        self.user_id: Optional[int] = None
        self.username: str = ""
        self.auto_relist = False
        self.check_minutes = 30
        self.next_auto_run: Optional[dt.datetime] = None
        self.listings_snapshot = None
        self.listings_checked_at = None
        self.last_auto_run: Optional[dt.datetime] = None
        self.last_auto_result: Optional[str] = None
        self.relist_attempts: dict = {}
        self.relist_success: dict = {}  # timestamp da última publicação aceita (por anúncio)
        self.rotations: list[dict] = []
        self.rotation_owner: str = ""
        self.rotation_not_before = None
        self.catalog_cache: dict = {}
        self.inbox = {}
        self.offer_actions = {}
        self.chat_partners = {}


    def public(self) -> dict:
        with self.lock:
            c = self.client
            return {
                "configured": c is not None and self.user_id is not None,
                "slug": c.slug if c else traderie.DEFAULT_SLUG,
                "user_id": self.user_id,
                "username": self.username,
                "auth_set": bool(c and c.has_auth),
                "policy": dict(c.policy) if c else traderie.default_policy(),
                "auto_relist": self.auto_relist,
                "availability_poll_seconds": 10,
                "next_auto_run": self.next_auto_run.isoformat() if self.next_auto_run else None,
                "check_minutes": self.check_minutes,
                "last_auto_run": self.last_auto_run.isoformat() if self.last_auto_run else None,
                "last_auto_result": self.last_auto_result,
                "saved": None if c else _read_json(CONFIG_FILE) or None,
                "rotation_count": len(self.rotations),
                "rotation_active": sum(bool(x.get("enabled")) for x in self.rotations),
            }


S = State()
RELIST_LOCK = threading.Lock()  # evita duas republicações simultâneas (manual x automática)
WRITE_LOCK = threading.Lock()  # serializa criações, exclusões e rotinas
STOP = threading.Event()
AUTO_WAKE = threading.Event()
CATALOG_CLIENT = TraderieClient()
INBOX_LOCK = threading.Lock()
OFFER_ACTION_LOCK = threading.Lock()


def offer_revision(offer):
    return hashlib.sha256(json.dumps(asdict(offer), sort_keys=True, default=str).encode()).hexdigest()


def to_json(obj: Any) -> Any:
    if isinstance(obj, traderie.Conversation):
        return {"conversationID": obj.conversationID, "userID": obj.userID}
    if isinstance(obj, traderie.Offer):
        return {**to_json(asdict(obj)), "revision": offer_revision(obj)}
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, dict):
        return {str(k): to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json(v) for v in obj]
    return obj


def fail(message: str, code: int = 400, **extra):
    return jsonify({"ok": False, "error": message, **extra}), code


# --------------------------------------------------------------------------
# Segurança: o servidor é local, mas qualquer site aberto no navegador poderia
# tentar chamá-lo (CSRF / DNS rebinding). Bloqueamos Host e Origin estranhos.
# --------------------------------------------------------------------------
@app.before_request
def guard():
    if request.host not in ALLOWED_HOSTS:
        return fail("Host não permitido.", 403)
    if request.method != "GET":
        origin = request.headers.get("Origin")
        if origin and origin not in {f"http://{host}" for host in ALLOWED_HOSTS}:
            return fail("Origem não permitida.", 403)
        if not request.is_json:
            return fail("Envie JSON (Content-Type: application/json).", 415)
        if not isinstance(request.get_json(silent=True), dict):
            return fail("Envie um objeto JSON válido.", 400)


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


def api(fn: Callable) -> Callable:
    """Decorator: exige configuração e converte erros da API em JSON legível."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with S.lock:
            client, uid = S.client, S.user_id
        if client is None or uid is None:
            return fail("Configure primeiro o slug e sua conta (usuário ou ID).")
        try:
            return fn(client, uid, *args, **kwargs)
        except AuthRequired as exc:
            return fail(str(exc), 401, auth_required=True)
        except traderie.Blocked as exc:
            return fail(str(exc), 503, blocked=True)
        except TraderieError as exc:
            return fail(str(exc), 502, retry_after=getattr(exc, "retry_after", None))
        except ValueError as exc:
            return fail(str(exc), 400)
    return wrapper


def body() -> dict:
    result = request.get_json(silent=True)
    if not isinstance(result, dict):
        raise ValueError("O corpo JSON deve ser um objeto.")
    return result


def int_field(data: dict, key: str, label: str) -> int:
    try:
        if isinstance(data.get(key), bool):
            raise ValueError()
        value = int(data[key])
        if value <= 0:
            raise ValueError()
        return value
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{label} inválido.")


def clamp_minutes(value: Any, default: int = 30) -> int:
    try:
        return max(5, min(1440, int(value)))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Conexão
# --------------------------------------------------------------------------
def connect(slug: str, username: str, raw_id: str, auth: Optional[str], minutes: int, want_auto: bool) -> dict:
    """Valida a conta, grava o estado e devolve a resposta da rota (levanta ValueError/TraderieError)."""
    clean = traderie.clean_slug(slug or traderie.DEFAULT_SLUG)
    client = TraderieClient(clean, auth, policy=load_policy(clean))
    username = (username or "").strip()
    raw_id = (raw_id or "").strip()
    if raw_id.isdigit():
        user_id = int(raw_id)
    elif username:
        user_id = client.search_user(username)
        if user_id is None:
            raise LookupError(f"Usuário '{username}' não encontrado no jogo '{client.slug}'.")
    else:
        raise ValueError("Informe seu nome de usuário ou ID numérico do Traderie.")

    status, notes = None, []
    try:
        status = client.get_status(user_id)  # teste somente leitura
    except AuthRequired:
        notes.append("O status da conta exigiu token; o resto pode funcionar sem ele.")

    auto = want_auto and client.has_auth  # automação exige token
    owner = f"{client.slug}:{user_id}"
    with WRITE_LOCK, OFFER_ACTION_LOCK, S.lock:
        # Não reutiliza rotinas de outra conta. Nunca reativa após reconectar.
        if S.rotation_owner != owner:
            stored = _read_json(ROTATIONS_FILE)
            candidates = stored.get("routines", []) if stored.get("owner") == owner else []
            S.rotations = [dict(x, enabled=False, running=False) for x in candidates if isinstance(x, dict)]
            S.rotation_not_before = traderie.parse_updated(stored.get("not_before")) if stored.get("owner") == owner else None
            S.rotation_owner = owner
        else:
            for r in S.rotations:
                r["enabled"] = False
                r["running"] = False
        S.client, S.user_id, S.username = client, user_id, username
        S.auto_relist, S.check_minutes = auto, minutes
        S.relist_attempts.clear()
        S.relist_success.clear()
        S.last_auto_run = S.last_auto_result = S.next_auto_run = None
        S.listings_snapshot = S.listings_checked_at = None
        S.inbox = {}
        S.offer_actions = {}
        S.chat_partners = {}
    AUTO_WAKE.set()
    _write_json(CONFIG_FILE, {"slug": client.slug, "username": username, "user_id": user_id, "check_minutes": minutes})

    message = "Conexão testada com sucesso." if status is not None else "Conectado."
    if not client.has_auth:
        message += " Sem token: ações que alteram a conta ficam desativadas. Use 'Testar endpoints' para ver o que funciona."
    elif want_auto and not auto:
        message += " Republicação automática desativada."
    return {"ok": True, "message": " ".join([message, *notes]), "status": status, "state": S.public()}


def autoconnect() -> None:
    """Reconecta ao iniciar usando config.json (+ token de TRADERIE_AUTH, se existir)."""
    saved = _read_json(CONFIG_FILE)
    if not saved.get("user_id"):
        return
    try:
        connect(saved.get("slug") or traderie.DEFAULT_SLUG, saved.get("username", ""), str(saved["user_id"]),
                os.environ.get("TRADERIE_AUTH"), clamp_minutes(saved.get("check_minutes")), False)
        log.info("Reconectado automaticamente como usuário %s.", saved["user_id"])
    except (TraderieError, ValueError, LookupError) as exc:
        log.warning("Reconexão automática falhou: %s", exc)


# --------------------------------------------------------------------------
# Republicação
# --------------------------------------------------------------------------
def remember_listings(client, user_id, listings):
    with S.lock:
        if S.client is client and S.user_id == user_id:
            S.listings_snapshot = listings
            S.listings_checked_at = dt.datetime.now(dt.timezone.utc)


def next_availability_check(listings, now):
    """Poll every 10s; a nearer server deadline wakes the worker earlier."""
    deadline = now + dt.timedelta(seconds=10)
    for listing in listings.values():
        available = traderie.parse_updated(listing.refresh_available_at)
        if available and now < available < deadline:
            deadline = available
    return deadline


def run_relist(client: TraderieClient, user_id: int, *, automatic=False) -> dict:
    """Refresh only on a server signal; never assume an age-based cooldown."""
    if not RELIST_LOCK.acquire(blocking=False):
        raise TraderieError("Já existe uma republicação em andamento.")
    try:
        listings = client.get_all_listings(user_id)
        remember_listings(client, user_id, listings)
        now = dt.datetime.now(dt.timezone.utc)
        results, unknown = [], 0
        next_check = next_availability_check(listings, now)
        for lid, listing in listings.items():
            key = (client.slug, user_id, lid)
            with S.lock:
                if automatic and (not S.auto_relist or S.client is not client or S.user_id != user_id):
                    break
                if listing.can_refresh is False:
                    S.relist_success.pop(key, None)  # a new availability cycle
            with S.lock:
                managed = {n for r in S.rotations if r.get("enabled") for n in r.get("owned_ids", [])}
            if lid in managed:
                continue
            if not traderie.is_listing_relistable(listing, now):
                if listing.can_refresh is None and listing.refresh_available_at is None:
                    unknown += 1
                continue
            with S.lock:
                if key in S.relist_success and S.relist_success[key] == listing.updated:
                    continue
                S.relist_attempts[key] = now
            try:
                client.relist(lid)
                with S.lock:
                    S.relist_success[key] = listing.updated
                results.append({"id": lid, "ok": True, "error": None, "item": listing.itemName})
            except (AuthRequired, traderie.Blocked):
                raise
            except TraderieError as exc:
                results.append({"id": lid, "ok": False, "error": str(exc), "item": listing.itemName})
                if exc.status == 429:
                    next_check = now + dt.timedelta(seconds=max(60, getattr(exc, 'retry_after', 60)))
                    break  # do not continue sending writes after a rate limit
        if any(row['ok'] for row in results):
            # Refresh timestamps only from server evidence, never fabricate them.
            try:
                remember_listings(client, user_id, client.get_all_listings(user_id))
            except TraderieError:
                pass
        with S.lock:
            active_keys = {(client.slug, user_id, lid) for lid in listings}
            S.relist_success = {k: v for k, v in S.relist_success.items() if k in active_keys}
            S.relist_attempts = {k: v for k, v in S.relist_attempts.items() if now-v < dt.timedelta(days=2)}
        return {"ok": True, "checked": len(listings), "unknown": unknown,
                "relisted": sum(r['ok'] for r in results), "results": results,
                "next_check": next_check.isoformat()}
    finally:
        RELIST_LOCK.release()


def auto_loop() -> None:
    while not STOP.is_set():
        now = dt.datetime.now(dt.timezone.utc)
        with S.lock:
            client, uid = S.client, S.user_id
            enabled = S.auto_relist and client is not None and client.has_auth and uid is not None
            deadline = S.next_auto_run or now
        if not enabled or deadline > now:
            AUTO_WAKE.wait(min(30, max(.1, (deadline-now).total_seconds())) if enabled else 30)
            AUTO_WAKE.clear()
            continue
        next_check = now + dt.timedelta(seconds=10)
        try:
            result = run_relist(client, uid, automatic=True)
            next_check = traderie.parse_updated(result['next_check'])
            message = f"{result['relisted']} republicado(s) de {result['checked']} verificado(s)."
            if result['unknown']:
                message += f" {result['unknown']} aguardando informação de disponibilidade do Traderie."
            failed = [r for r in result['results'] if not r['ok']]
            if failed:
                message += f" {len(failed)} falha(s): {failed[0]['error']}"
        except (AuthRequired, traderie.Blocked) as exc:
            message = f"Automação pausada: {exc}"
            with S.lock:
                if S.client is client:
                    S.auto_relist = False
        except TraderieError as exc:
            message = f"Nova tentativa após falha de conexão: {exc}"
            next_check = now + dt.timedelta(seconds=max(60, getattr(exc, 'retry_after', 60)))
        except Exception:
            log.exception("Falha inesperada na republicação automática")
            message = "Erro inesperado (veja o terminal)."
            next_check = now + dt.timedelta(seconds=60)
        with S.lock:
            if S.client is client and S.user_id == uid:
                S.last_auto_run = dt.datetime.now(dt.timezone.utc)
                S.last_auto_result = message
                S.next_auto_run = next_check if S.auto_relist else None
        log.info("Auto-republicação: %s", message)


# --------------------------------------------------------------------------
# Criação/exclusão: as URLs e os campos foram observados no DevTools pelo usuário.
# Ainda requerem validação ao vivo; o código jamais testa essas escritas sozinho.
# --------------------------------------------------------------------------
MAX_BULK_DELETE = 100
MIN_ROTATION_MINUTES = 15


def save_rotations() -> None:
    with S.lock:
        _write_json(ROTATIONS_FILE, {"owner": S.rotation_owner, "routines": S.rotations,
                                    "not_before": S.rotation_not_before.isoformat() if S.rotation_not_before else None})


def rotation_public(r: dict) -> dict:
    """Modelo não contém autenticação; útil para edição/revisão do usuário."""
    return {k: to_json(v) for k, v in r.items()}


def require_auth(client: TraderieClient) -> None:
    if not client.has_auth:
        raise AuthRequired("Esta ação exige Authorization válido.")


def positive_id(value: Any, label: str) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise ValueError(f"{label} inválido.")
    return int(value)


def existing_owned(client: TraderieClient, uid: int) -> dict:
    """Consulta a conta conectada antes de qualquer exclusão."""
    return client.get_all_listings(uid)


def delete_owned(client: TraderieClient, uid: int, lid: int) -> None:
    if lid not in existing_owned(client, uid):
        raise ValueError(f"Anúncio #{lid} não encontrado entre os anúncios desta conta.")
    client.delete_listing(lid)


def create_and_identify(client: TraderieClient, uid: int, template: dict, before_create=None) -> int:
    """Identifica anúncio novo sem repetir o POST quando a resposta for ambígua."""
    current = existing_owned(client, uid)
    if before_create:
        before_create()
    new_id = client.create_listing(template)
    if new_id is not None:
        return new_id
    # Se a API respondeu sucesso sem ID, tenta reconciliar por diferença.
    try:
        new = existing_owned(client, uid)
    except TraderieError as exc:
        raise TraderieError("O anúncio pode ter sido criado, mas o ID não veio na resposta. "
                            "Confira no site antes de tentar novamente.") from exc
    diff = [lid for lid, x in new.items() if lid not in current and x.itemID == int(template["item"])]
    if len(diff) == 1:
        return diff[0]
    raise TraderieError("Criação possivelmente concluída, mas não foi possível identificar "
                        "um único anúncio novo. Confira sua conta antes de repetir.")


def rotation_next(minutes: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()


def rotation_is_current(client, uid, routine):
    return (S.client is client and S.user_id == uid and routine in S.rotations
            and routine.get("enabled") and not STOP.is_set())


def execute_rotation(client: TraderieClient, uid: int, rotation_id: str) -> dict:
    """Delete only this routine's previous listing, then create its exact template.

    All queued publications share a 60-second gate. Never retry an ambiguous write.
    Check pause/account changes before each irreversible step.
    """
    if not WRITE_LOCK.acquire(blocking=False):
        return {"ok": True, "deferred": True}
    try:
        require_auth(client)
        with S.lock:
            routine = next((r for r in S.rotations if r["id"] == rotation_id), None)
            if routine is None:
                raise ValueError("Agendamento não encontrado.")
            if not rotation_is_current(client, uid, routine):
                return {"ok": True, "paused": True}
            now = dt.datetime.now(dt.timezone.utc)
            due = traderie.parse_updated(routine.get("next_run")) or now
            gate = S.rotation_not_before or now
            if max(due, gate) > now:
                return {"ok": True, "deferred": True}
            routine["running"] = True
            previous = list(routine.get("owned_ids", []))
            routine["last_result"] = "Excluindo anterior e publicando…" if previous else "Publicando…"
            save_rotations()
        try:
            template = traderie.validated_creation(routine["template"])
            if len(previous) > 1:
                raise TraderieError("Mais de um anúncio rastreado; revise antes de continuar.")
            removed = 0
            if previous:
                own = existing_owned(client, uid)
                for lid in previous:
                    with S.lock:
                        if not rotation_is_current(client, uid, routine):
                            return {"ok": True, "paused": True}
                    if lid in own:
                        client.delete_listing(lid)
                        removed += 1
                    with S.lock:
                        routine["owned_ids"] = []
                        save_rotations()
            with S.lock:
                if not rotation_is_current(client, uid, routine):
                    return {"ok": True, "paused": True}
                # Reserve the slot before sending; a failed/ambiguous POST also consumes it.
                S.rotation_not_before = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)
                save_rotations()
            def still_active():
                with S.lock:
                    if not rotation_is_current(client, uid, routine):
                        raise ValueError("Agendamento interrompido antes da publicação")
            created = create_and_identify(client, uid, template, before_create=still_active)
            with S.lock:
                finished = dt.datetime.now(dt.timezone.utc)
                S.rotation_not_before = finished + dt.timedelta(seconds=60)
                routine["owned_ids"] = [created]
                routine["last_run"] = finished.isoformat()
                routine["next_run"] = (finished + dt.timedelta(minutes=routine["interval_minutes"])).isoformat()
                routine["cycles"] = routine.get("cycles", 0) + 1
                routine["last_result"] = "Publicado; aguardando próximo ciclo." if routine["enabled"] else "Publicado; agendamento interrompido."
                S.listings_snapshot = None
                save_rotations()
            return {"ok": True, "created_id": created, "removed": removed, "message": routine["last_result"]}
        except Exception as exc:
            with S.lock:
                routine["enabled"] = False
                routine["last_result"] = f"Pausado: {str(exc)[:350]}. Confira os anúncios antes de retomar."
                if isinstance(exc, (AuthRequired, traderie.Blocked)):
                    for row in S.rotations:
                        row["enabled"] = False
                if isinstance(exc, TraderieError) and exc.status == 429:
                    S.rotation_not_before = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(60, getattr(exc, 'retry_after', 60)))
                save_rotations()
            raise
        finally:
            with S.lock:
                routine["running"] = False
                save_rotations()
    finally:
        WRITE_LOCK.release()


def run_rotation_tick():
    """One due item per tick; overdue items retain chronological order."""
    with S.lock:
        c, uid = S.client, S.user_id
        now = dt.datetime.now(dt.timezone.utc)
        due = sorted((r for r in S.rotations if r.get("enabled")),
                     key=lambda r: traderie.parse_updated(r.get("next_run")) or now)
        if c is None or uid is None or not due:
            return
        rid = due[0]["id"]
    return execute_rotation(c, uid, rid)


def rotation_loop() -> None:
    while not STOP.wait(0.5):
        try:
            run_rotation_tick()
        except (TraderieError, ValueError) as exc:
            log.warning("Agendamento pausado: %s", exc)
        except Exception:
            log.exception("Falha no agendamento")


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/state")
def api_state():
    return jsonify({"ok": True, "state": S.public()})


@app.post("/api/config")
def api_config():
    data = body()
    try:
        result = connect(str(data.get("slug") or ""), str(data.get("username") or ""), str(data.get("user_id") or ""),
                         data.get("auth"), clamp_minutes(data.get("check_minutes")), bool(data.get("auto_relist")))
    except LookupError as exc:
        return fail(str(exc), 404)
    except ValueError as exc:
        return fail(str(exc))
    except TraderieError as exc:
        return fail(f"Teste de conexão falhou: {exc}", 502)
    return jsonify(result)


@app.post("/api/clear-auth")
def api_clear_auth():
    with S.lock:
        if S.client:
            S.client.auth = ""
        S.auto_relist = False
        S.inbox = {}
        S.offer_actions = {}
        S.chat_partners = {}
        for rotation in S.rotations:
            rotation["enabled"] = False
        save_rotations()
    return jsonify({"ok": True, "message": "Token removido da memória. Rotinas pausadas.", "state": S.public()})


@app.post("/api/diagnose")
@api
def api_diagnose(client, uid):
    """Somente leitura: chama os GETs com e sem token e ajusta a política."""
    rows = client.diagnose(uid)
    save_policy(client)
    return jsonify({"ok": True, "rows": rows, "has_token": client.has_auth, "state": S.public()})


@app.post("/api/auto-relist")
@api
def api_auto_relist(client, uid):
    enabled = bool(body().get("enabled"))
    if enabled and not client.has_auth:
        raise AuthRequired("A republicação automática precisa do token Authorization.")
    data = body()
    raw_minutes = data.get("check_minutes", S.check_minutes)
    try:
        minutes = int(raw_minutes)
    except (ValueError, TypeError):
        raise ValueError("Informe um intervalo numérico de 5 a 1440 minutos.")
    if not 5 <= minutes <= 1440:
        raise ValueError("O intervalo deve estar entre 5 e 1440 minutos.")
    with S.lock:
        S.auto_relist = enabled
        S.check_minutes = minutes
        S.last_auto_run = None
        S.next_auto_run = None
        saved = {"slug": client.slug, "username": S.username, "user_id": uid, "check_minutes": minutes}
    _write_json(CONFIG_FILE, saved)
    AUTO_WAKE.set()
    return jsonify({"ok": True, "state": S.public()})


@app.get("/api/status")
@api
def api_status(client, uid):
    return jsonify({"ok": True, "status": client.get_status(uid)})


@app.post("/api/online")
@api
def api_online(client, uid):
    data = body()
    new = data.get("status")
    if new is None and isinstance(data.get("online"), bool):
        new = "online" if data["online"] else "offline"  # retrocompatibilidade
    if new not in ("online", "offline", "busy"):
        raise ValueError("Selecione online, ocupado ou offline.")
    client.set_status(new)
    return jsonify({"ok": True, "status": new})


def refresh_inbox(client, uid):
    """Refresh independent sources; stale data remains visible with its error."""
    if not client.has_auth or not INBOX_LOCK.acquire(blocking=False):
        return
    try:
        for source in ("notifications", "offers"):
            with S.lock:
                if S.client is not client or S.user_id != uid or not client.has_auth:
                    return
                previous = S.inbox.get(source, {})
                now = dt.datetime.now(dt.timezone.utc)
                if previous.get("paused") or (previous.get("next_check") and previous["next_check"] > now):
                    continue
            try:
                items = client.get_notifications(limit=50) if source == "notifications" else list(client.get_offers(to_seller=uid).values())
                if source == "offers":
                    items = [o for o in items if o.sellerID == uid]
                result = {"items": to_json(items), "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "error": None, "paused": False, "rate_limited": False,
                          "next_check": dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=15)}
            except TraderieError as exc:
                result = {**previous, "error": str(exc), "paused": isinstance(exc, (AuthRequired, traderie.Blocked)),
                          "rate_limited": exc.status == 429,
                          "next_check": dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=max(30, getattr(exc, 'retry_after', 30)))}
            with S.lock:
                if S.client is not client or S.user_id != uid or not client.has_auth:
                    return
                S.inbox[source] = result
                # A service-wide rejection must also back off the other source.
                if result.get("paused") or result.get("rate_limited"):
                    other = "offers" if source == "notifications" else "notifications"
                    S.inbox[other] = {**S.inbox.get(other, {}), "error": result["error"],
                                     "paused": result["paused"], "rate_limited": result["rate_limited"],
                                     "next_check": result["next_check"]}
                    break
    finally:
        INBOX_LOCK.release()


def inbox_loop():
    while not STOP.wait(1):
        with S.lock:
            client, uid = S.client, S.user_id
        if client is None or uid is None:
            continue
        try:
            refresh_inbox(client, uid)
        except Exception:
            log.exception("Falha inesperada na sincronização da central")
            STOP.wait(15)


def inbox_public():
    with S.lock:
        sources = {name:{k: v.isoformat() if isinstance(v, dt.datetime) else v
                         for k,v in row.items() if k != 'items'} for name,row in S.inbox.items()}
        notifications = S.inbox.get("notifications", {}).get("items", [])
        offers = [o for o in S.inbox.get("offers", {}).get("items", []) if str(o["offerID"]) not in S.offer_actions]
        return {"ok": True, "notifications": notifications, "offers": offers, "sources": sources,
                "unread_count": sum(n.get("read") is False for n in notifications), "poll_seconds":15,
                "counter_supported": True}


@app.get("/api/inbox")
@api
def api_inbox(client, uid):
    require_auth(client)
    refresh_inbox(client, uid)
    return jsonify(inbox_public())


@app.post("/api/inbox/retry")
@api
def api_inbox_retry(client, uid):
    require_auth(client)
    with S.lock:
        for row in S.inbox.values():
            row["paused"] = False
            if not row.get("rate_limited"):
                row["next_check"] = None
    return jsonify({"ok":True})


@app.get("/api/notifications")
@api
def api_notifications(client, uid):
    limit = max(1, min(100, request.args.get("limit", default=30, type=int)))
    return jsonify({"ok": True, "notifications": to_json(client.get_notifications(limit=limit))})


@app.post("/api/notifications/read")
@api
def api_notifications_read(client, uid):
    require_auth(client)
    ids = body().get("ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(x, str) or not x or len(x)>200 for x in ids):
        raise ValueError("Selecione de 1 a 100 notificações válidas.")
    known = {str(n.notificationID) for n in client.get_notifications(limit=100)}
    if not set(ids) <= known:
        raise ValueError("Notificação não encontrada nesta conta. Atualize a central.")
    client.mark_notifications_read(ids)
    with S.lock:
        if S.client is client:
            for row in S.inbox.get("notifications", {}).get("items", []):
                if str(row["notificationID"]) in ids:
                    row["read"] = True
    return jsonify({"ok": True})


def public_image_overrides(slug: str) -> dict:
    stored = _read_json(IMAGES_FILE).get(slug, {})
    return stored if isinstance(stored, dict) else {}


@app.get('/api/item-images')
@api
def api_item_images(client, uid):
    """Resolve poucas imagens por ID em catálogo público; resultado em cache."""
    raw = request.args.get('ids', '')
    parts = [x for x in raw.split(',') if x]
    if len(parts) > 12 or any(not x.isdigit() or len(x) > 20 or int(x) <= 0 for x in parts):
        raise ValueError('Informe até 12 IDs válidos.')
    ids = list(dict.fromkeys(int(x) for x in parts))
    current = dt.datetime.now(dt.timezone.utc)
    overrides = public_image_overrides(client.slug)
    found = {}
    source = {}
    for iid in ids:
        saved = traderie.normalize_image_url(overrides.get(str(iid)))
        if saved:
            found[str(iid)] = saved
            source[str(iid)] = 'manual'
            continue
        key = (client.slug, iid)
        with S.lock:
            cached = S.catalog_cache.get(key)
        if cached and (current - cached[0]).total_seconds() < (21600 if cached[1] else 1800):
            image = cached[1]
        else:
            image = client.get_catalog_image(iid)
            with S.lock:
                S.catalog_cache[key] = (current, image)
        if image:
            found[str(iid)] = image
            source[str(iid)] = 'catalogo'
    return jsonify({'ok': True, 'images': found, 'sources': source,
                    'note': 'Consulta experimental ao catálogo público: imagens podem não estar disponíveis.'})


@app.post('/api/item-images')
@api
def api_set_item_image(client, uid):
    """Associa manualmente uma URL pública à arte do item (opcional)."""
    data = body()
    iid = positive_id(data.get('item_id'), 'ID do item')
    raw_url = str(data.get('image_url') or '').strip()
    url = traderie.normalize_image_url(raw_url) if raw_url else None
    if raw_url and not url:
        raise ValueError('Utilize URL de imagem HTTPS pública válida, sem credenciais.')
    if url:
        from urllib.parse import urlsplit, parse_qs
        fields = parse_qs(urlsplit(url).query, keep_blank_values=True)
        if any(name.lower() in {'token','authorization','jwt','auth','apikey','api_key','secret','password','access_token'}
               for name in fields):
            raise ValueError('A URL parece conter credenciais. Use uma URL pública sem tokens.')
    with S.lock:
        images = _read_json(IMAGES_FILE)
        by_slug = images.get(client.slug, {})
        if not isinstance(by_slug, dict):
            by_slug = {}
        if url:
            if len(by_slug) >= 500 and str(iid) not in by_slug:
                raise ValueError('Limite de 500 imagens por jogo.')
            by_slug[str(iid)] = url
        else:
            by_slug.pop(str(iid), None)
        images[client.slug] = by_slug
        _write_json(IMAGES_FILE, images)
        S.catalog_cache.pop((client.slug, iid), None)
    return jsonify({'ok': True, 'item_id': iid, 'image_url': url})


@app.get("/api/listings")
@api
def api_listings(client, uid):
    out = []
    overrides = public_image_overrides(client.slug)
    with S.lock:
        cached = S.listings_snapshot
        checked = S.listings_checked_at
    if request.args.get('cached') == '1' and cached is not None and checked and (dt.datetime.now(dt.timezone.utc)-checked).total_seconds() < 30:
        listings = cached
    else:
        listings = client.get_all_listings(uid)
        remember_listings(client, uid, listings)
    for lid, l in listings.items():
        eta = traderie.relist_eta(l)
        out.append({
            "id": lid, "updated": l.updated, "item": l.itemName, "amount": l.amount,
            "properties": to_json(l.properties), "image_url": traderie.normalize_image_url(overrides.get(str(l.itemID))) or l.image_url, "item_id": l.itemID, "eligible": traderie.is_listing_relistable(l),
            "eligible_in_hours": None if eta is None else round(eta.total_seconds() / 3600, 1),
            "availability_known": l.can_refresh is not None or l.refresh_available_at is not None,
            "category": l.item_category,
            "refresh_available_at": l.refresh_available_at, "can_refresh": l.can_refresh,
            "availability_source": l.availability_source,
            "url": f"https://traderie.com/{client.slug}/listing/{lid}",
        })
    out.sort(key=lambda x: x["updated"] or "")  # mais antigos primeiro (os próximos a republicar)
    return jsonify({"ok": True, "listings": out, "checked_at": S.listings_checked_at.isoformat() if S.listings_checked_at else None})


@app.post("/api/relist")
@api
def api_relist(client, uid):
    require_auth(client)
    lid = int_field(body(), "listing_id", "ID de anúncio")
    if not RELIST_LOCK.acquire(blocking=False):
        raise TraderieError("Já existe uma republicação em andamento.")
    try:
        listing = existing_owned(client, uid).get(lid)
        if not listing:
            raise ValueError("Anúncio não encontrado nesta conta.")
        key = (client.slug, uid, lid)
        with S.lock:
            if key in S.relist_success and S.relist_success[key] == listing.updated:
                raise ValueError("Republicação já aceita. Aguarde a atualização do Traderie.")
        client.relist(lid)
        with S.lock:
            S.relist_success[key] = listing.updated
            S.listings_snapshot = None
    finally:
        RELIST_LOCK.release()
    return jsonify({"ok": True, "listing_id": lid})


@app.post("/api/relist-all")
@api
def api_relist_all(client, uid):
    if not client.has_auth:
        raise AuthRequired("Esta ação precisa do token Authorization.")
    return jsonify(run_relist(client, uid))


@app.post("/api/listings/create")
@api
def api_create_listing(client, uid):
    require_auth(client)
    data = body()
    if data.get("confirm") is not True:
        raise ValueError("Confirme a publicação no painel.")
    template = traderie.validated_creation(data.get("template"))
    if not WRITE_LOCK.acquire(blocking=False):
        raise TraderieError("Outra operação de criação/exclusão está em andamento.")
    try:
        lid = create_and_identify(client, uid, template)
        return jsonify({"ok": True, "listing_id": lid})
    finally:
        WRITE_LOCK.release()


@app.post("/api/listings/delete")
@api
def api_delete_listing(client, uid):
    require_auth(client)
    data = body()
    if data.get("confirm") is not True:
        raise ValueError("Confirme a exclusão no painel.")
    lid = positive_id(data.get("listing_id"), "ID do anúncio")
    if not WRITE_LOCK.acquire(blocking=False):
        raise TraderieError("Outra operação de criação/exclusão está em andamento.")
    try:
        delete_owned(client, uid, lid)
        with S.lock:
            for routine in S.rotations:
                routine["owned_ids"] = [x for x in routine.get("owned_ids", []) if x != lid]
            save_rotations()
        return jsonify({"ok": True, "deleted": lid})
    finally:
        WRITE_LOCK.release()


@app.post("/api/listings/bulk-delete")
@api
def api_bulk_delete(client, uid):
    require_auth(client)
    data = body()
    exact_name = str(data.get("item_name") or "").strip()
    if not exact_name or data.get("confirm_name") != exact_name:
        raise ValueError("Confirme o nome exato do item antes de excluir.")
    raw_ids = data.get("ids")
    if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= MAX_BULK_DELETE:
        raise ValueError(f"Selecione de 1 a {MAX_BULK_DELETE} anúncios.")
    ids = [positive_id(value, "ID do anúncio") for value in raw_ids]
    if len(ids) != len(set(ids)):
        raise ValueError("Há IDs duplicados na seleção.")
    if not WRITE_LOCK.acquire(blocking=False):
        raise TraderieError("Outra operação de criação/exclusão está em andamento.")
    try:
        owned = existing_owned(client, uid)
        for lid in ids:
            listing = owned.get(lid)
            if listing is None or (listing.itemName or "").strip().casefold() != exact_name.casefold():
                raise ValueError("Seleção diferente dos anúncios atuais do item. Atualize a lista.")
        done, errors = [], []
        for lid in ids:
            try:
                client.delete_listing(lid)
                done.append(lid)
            except (AuthRequired, traderie.Blocked):
                raise
            except TraderieError as exc:
                errors.append({"id": lid, "error": str(exc)})
        # IDs removidos por qualquer caminho não podem continuar como 'owned'.
        with S.lock:
            for routine in S.rotations:
                routine["owned_ids"] = [n for n in routine.get("owned_ids", []) if n not in done]
            save_rotations()
        return jsonify({"ok": True, "deleted": done, "errors": errors})
    finally:
        WRITE_LOCK.release()


@app.get("/api/rotation-routines")
@api
def api_get_rotations(client, uid):
    with S.lock:
        return jsonify({"ok": True, "routines": [rotation_public(r) for r in S.rotations],
                        "queue_not_before": S.rotation_not_before.isoformat() if S.rotation_not_before else None})


@app.post("/api/rotation-routines")
@api
def api_new_rotation(client, uid):
    require_auth(client)
    data = body()
    template = traderie.validated_creation(data.get("template"))
    name = str(data.get("item_name") or "").strip()
    if not 1 <= len(name) <= 160:
        raise ValueError("Informe um nome para o item (até 160 caracteres).")
    minutes = positive_id(data.get("interval_minutes"), "Intervalo")
    if not MIN_ROTATION_MINUTES <= minutes <= 1440:
        raise ValueError("O timer deve ser de 15 a 1440 minutos.")
    with S.lock:
        if len(S.rotations) >= 20:
            raise ValueError("Máximo de 20 rotinas por conta.")
        r = {"id": uuid.uuid4().hex, "item_name": name, "template": template,
             "interval_minutes": minutes, "enabled": False, "owned_ids": [],
             "next_run": None, "last_run": None, "last_result": "Aguardando ativação."}
        S.rotations.append(r)
        save_rotations()
    return jsonify({"ok": True, "routine": rotation_public(r)})


@app.post("/api/rotation-routines/batch")
@api
def api_rotation_batch(client, uid):
    require_auth(client)
    data = body()
    items = data.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError("Adicione entre 1 e 20 itens à fila.")
    minutes = positive_id(data.get("interval_minutes", 60), "Intervalo")
    if not MIN_ROTATION_MINUTES <= minutes <= 1440:
        raise ValueError("Intervalo de 15 a 1440 minutos.")
    rows = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Item de agendamento inválido.")
        name = str(item.get("item_name") or "").strip()
        if not 1 <= len(name) <= 160:
            raise ValueError("Informe o nome de cada item.")
        rows.append({"id": uuid.uuid4().hex, "item_name": name,
                     "template": traderie.validated_creation(item.get("template")),
                     "interval_minutes": minutes, "enabled": False, "owned_ids": [],
                     "next_run": None, "last_run": None, "last_result": "Pronto para iniciar.", "cycles": 0})
    with S.lock:
        if len(S.rotations) + len(rows) > 20:
            raise ValueError("Máximo de 20 itens agendados por conta.")
        S.rotations.extend(rows)
        save_rotations()
    return jsonify({"ok": True, "routines": rows})


@app.post("/api/rotation-routines/control")
@api
def api_rotation_control(client, uid):
    data = body()
    action = data.get("action")
    if action not in ("start", "stop"):
        raise ValueError("Comando inválido.")
    if action == "start":
        require_auth(client)
        if data.get("confirm") is not True:
            raise ValueError("Confirme a publicação e exclusão recorrentes.")
    with S.lock:
        now = dt.datetime.now(dt.timezone.utc)
        next_slot = max(now, S.rotation_not_before or now)
        for row in S.rotations:
            if action == "stop":
                row["enabled"] = False
                row["last_result"] = "Interrompido. Anúncio existente preservado."
            elif not row.get("enabled"):
                row["enabled"] = True
                # On resume respect the last successful publication's lifetime.
                last = traderie.parse_updated(row.get("last_run"))
                earliest = last + dt.timedelta(minutes=row["interval_minutes"]) if last and row.get("owned_ids") else now
                next_slot = max(next_slot, earliest)
                row["next_run"] = next_slot.isoformat()
                next_slot += dt.timedelta(seconds=60)
                row["last_result"] = "Na fila de publicação."
        save_rotations()
    return jsonify({"ok": True})


@app.post("/api/rotation-routines/action")
@api
def api_rotation_action(client, uid):
    data = body()
    rid = str(data.get("id") or "")
    action = data.get("action")
    if action not in ("enable", "pause", "run_now", "remove"):
        raise ValueError("Ação de rotina inválida.")
    with S.lock:
        row = next((r for r in S.rotations if r["id"] == rid), None)
        if row is None:
            return fail("Rotina não encontrada.", 404)
        if action in ("enable", "run_now"):
            require_auth(client)
            if data.get("confirm") is not True:
                raise ValueError("Confirme a ativação/execução da rotina.")
        if action == "enable":
            row["enabled"] = True
            now = dt.datetime.now(dt.timezone.utc)
            last = traderie.parse_updated(row.get("last_run"))
            earliest = last + dt.timedelta(minutes=row["interval_minutes"]) if last and row.get("owned_ids") else now
            row["next_run"] = max(now, earliest, S.rotation_not_before or now).isoformat()
            row["last_result"] = "Ativa; aguardando próximo ciclo."
        elif action == "pause":
            row["enabled"] = False
            row["last_result"] = "Pausada manualmente."
        elif action == "remove":
            if row["enabled"] or row.get("running"):
                raise ValueError("Pause e aguarde a operação em andamento antes de remover.")
            if data.get("confirm") is not True:
                raise ValueError("Confirme a remoção da configuração.")
            S.rotations.remove(row)  # anúncios já criados NÃO são excluídos.
        save_rotations()
    if action == "run_now":
        with S.lock:
            row["enabled"] = True
            row["next_run"] = dt.datetime.now(dt.timezone.utc).isoformat()
            save_rotations()
    return jsonify({"ok": True, "routines": [rotation_public(r) for r in S.rotations],
                        "queue_not_before": S.rotation_not_before.isoformat() if S.rotation_not_before else None})


# The catalog works without an account and never reads the seller's inventory.
CATALOG_LOCK = threading.Lock()


@app.get("/api/catalog/search")
def api_catalog_search():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', 'species').strip()
    try:
        page = int(request.args.get('page', '0'))
    except ValueError:
        return fail('Página inválida.')
    if category not in ('species', 'slots', 'plushies', 'palettes') or len(query) > 80 or not 0 <= page <= 100:
        return fail('Pesquisa ou categoria inválida.')
    with S.lock:
        client = S.client or CATALOG_CLIENT
    now = dt.datetime.now(dt.timezone.utc)
    key = ('catalog_search', client.slug, category, query.casefold(), page)
    with CATALOG_LOCK:
        cached = S.catalog_cache.get(key)
        if cached and (now-cached[0]).total_seconds() < 300:
            rows = cached[1]
        else:
            try:
                rows = client.search_catalog_items(query, category=category, page=page)
            except TraderieError as error:
                return fail(str(error), 503, catalog_available=False)
            S.catalog_cache[key] = (now, rows)
            if len(S.catalog_cache)>300:
                S.catalog_cache = {key:(now, rows)}
    wanted = 'species' if category == 'slots' else category
    results = [row for row in rows if row.get('category') == wanted]
    return jsonify({'ok': True, 'items': results, 'page':page,
                    'catalog_available': True, 'has_more': len(rows) >= 24})


@app.get("/api/listings/<int:listing_id>/offers")
@api
def api_listing_offers(client, uid, listing_id):
    """Somente ofertas recebidas para um anúncio pertencente ao usuário."""
    if listing_id <= 0 or listing_id not in client.get_all_listings(uid):
        return fail('Anúncio não encontrado na sua conta.', 404)
    offers = client.get_offers(to_seller=uid)
    selected = [v for v in offers.values() if v.listingID == listing_id]
    return jsonify({'ok':True, 'listing_id':listing_id,
                    'offers':to_json(sorted(selected,key=lambda o:o.offerID,reverse=True))})

@app.post("/api/offers/counter-message")
@api
def api_offer_counter_message(client, uid):
    """Negociação por chat, NÃO é a ação de counter-offer nativa."""
    require_auth(client)
    data=body()
    if data.get('confirm') is not True:
        raise ValueError('Confirme o envio da mensagem de negociação.')
    oid=positive_id(data.get('offer_id'), 'ID da oferta')
    text=str(data.get('message') or '').strip()
    if not 1 <= len(text) <= 800:
        raise ValueError('Digite uma proposta de 1 a 800 caracteres.')
    offer = client.get_offers(to_seller=uid).get(oid)
    if offer is None:
        return fail('Oferta não encontrada entre as recebidas.',404)
    if offer.listingID not in client.get_all_listings(uid):
        return fail('O anúncio desta oferta não pertence à sua conta.',403)
    warning=None
    try:
        client.open_conversation(offer.buyerID, offer.buyerUsername, offer.offerID)
    except TraderieError as exc:
        warning='Não foi possível abrir uma nova conversa: '+str(exc)
    # A API de mensagens é a operação confirmada; falhas não são tratadas como sucesso.
    client.send_message(offer.buyerID, text)
    return jsonify({'ok':True,'message':'Mensagem de negociação enviada. A oferta permanece aberta.',
                    'conversation_warning':warning})

def _resolve_offer_chat(client, uid: int, offer_id: int, kind: str):
    if kind not in ('received', 'sent'):
        raise ValueError('Direção da oferta inválida.')
    offers = client.get_offers(to_seller=uid) if kind == 'received' else client.get_offers(from_user=uid)
    offer = offers.get(offer_id)
    if offer is None or (offer.sellerID if kind == "received" else offer.buyerID) != uid:
        raise ValueError('Oferta não encontrada entre suas negociações abertas.')
    partner = offer.buyerID if kind == 'received' else offer.sellerID
    partner_name = offer.buyerUsername if kind == 'received' else offer.sellerUsername
    if partner <= 0 or partner == uid:
        raise ValueError('Usuário destinatário inválido.')
    return offer, partner, partner_name


def _chat_context(client, uid, data):
    """Validate membership on each read/write; an existing chat survives a closed offer."""
    require_auth(client)
    dialogs = client.get_conversations(True, uid)
    dialogs.update({k: v for k, v in client.get_conversations(False, uid).items() if k not in dialogs})
    if data.get('conversation_id'):
        cid = positive_id(data.get('conversation_id'), 'ID da conversa')
        partner = positive_id(data.get('user_id'), 'Usuário da conversa')
        conversation = dialogs.get(partner)
        if conversation is None or conversation.conversationID != cid:
            raise ValueError('Conversa não encontrada nesta conta.')
        return None, partner, '', conversation
    oid = positive_id(data.get('offer_id'), 'ID da oferta')
    kind = data.get('kind', 'received')
    key = (oid, kind)
    with S.lock:
        saved = S.chat_partners.get(key) if S.client is client and S.user_id == uid else None
    try:
        offer, partner, username = _resolve_offer_chat(client, uid, oid, kind)
    except ValueError:
        if saved is None:
            raise
        # A previously verified negotiation may now be closed; keep its chat usable.
        offer, (partner, username) = None, saved
    with S.lock:
        if S.client is client and S.user_id == uid:
            S.chat_partners[key] = (partner, username)
    return offer, partner, username, dialogs.get(partner)


@app.get('/api/offers/chat')
@api
def api_offer_chat(client, uid):
    offer, partner, username, conversation = _chat_context(client, uid, request.args)
    msgs = client.get_messages(partner, conversation.conversationID) if conversation else []
    with S.lock:
        if S.client is not client or S.user_id != uid:
            return fail('A conta mudou. Abra novamente a conversa.', 409)
    return jsonify({'ok': True, 'user_id': partner, 'username': username,
        'conversation_id': conversation.conversationID if conversation else None,
        'offer': to_json(offer) if offer else None, 'messages': to_json(msgs)})


@app.post('/api/offers/chat')
@api
def api_offer_chat_action(client, uid):
    data = body()
    # Prevent changing accounts halfway through a message submission.
    with OFFER_ACTION_LOCK:
        offer, partner, username, conversation = _chat_context(client, uid, data)
        with S.lock:
            if S.client is not client or S.user_id != uid:
                return fail('A conta mudou. Abra novamente a conversa.', 409)
        action = data.get('action')
        if action == 'start':
            if data.get('confirm') is not True:
                raise ValueError('Confirme antes de abrir uma conversa.')
            if conversation is None:
                client.open_conversation(partner, username, positive_id(data.get("offer_id"), "ID da oferta"))
            return jsonify({'ok': True, 'message': 'Solicitação de conversa enviada.'})
        if action == 'send':
            message = str(data.get('message') or '').strip()
            if not message or len(message) > 500:
                raise ValueError('Escreva uma mensagem de até 500 caracteres.')
            if conversation is None:
                raise ValueError('Abra uma conversa antes de enviar mensagens.')
            client.send_message(partner, message, conversation)
            return jsonify({'ok': True, 'message': 'Mensagem enviada.'})
        raise ValueError('Ação de chat inválida.')


@app.get("/api/offers")
@api
def api_offers(client, uid):
    kind = request.args.get("kind", "received")
    if kind not in ("received", "sent"):
        raise ValueError("Tipo de oferta inválido.")
    offers = client.get_offers(to_seller=uid) if kind == "received" else client.get_offers(from_user=uid)
    return jsonify({"ok": True, "offers": to_json(list(offers.values())), "kind": kind})


@app.post("/api/offers/action")
@api
def api_offer_action(client, uid):
    require_auth(client)
    data = body()
    offer_id = int_field(data, "offer_id", "ID de oferta")
    action = data.get("action")
    if action not in ("accept", "decline", "counter"):
        raise ValueError("Ação inválida.")
    if data.get("confirm") is not True:
        raise ValueError("Confirme a ação sobre a oferta.")
    if not OFFER_ACTION_LOCK.acquire(blocking=False):
        return fail("Já existe uma ação de oferta em andamento.", 409)
    try:
        with S.lock:
            if str(offer_id) in S.offer_actions:
                return fail("Esta oferta já foi tratada nesta sessão. Atualize a central.", 409)
        offer = client.get_offers(to_seller=uid).get(offer_id)
        if offer is None or offer.sellerID != uid:
            return fail("Oferta não encontrada entre as recebidas e abertas desta conta.", 404)
        with S.lock:
            if S.client is not client or S.user_id != uid or not client.has_auth:
                return fail("A conta mudou. Atualize a central.", 409)
        if data.get("revision") != offer_revision(offer):
            return fail("A oferta mudou. Atualize a central e revise os valores antes de confirmar.", 409)
        if action == "counter":
            shooms = data.get("shooms")
            if type(shooms) is not int or not 1 <= shooms <= 2147483647:
                raise ValueError("Informe um valor inteiro de 1 a 2147483647 Shooms.")
            client.counter_offer(offer, shooms)
        elif action == "decline":
            reason = str(data.get("reason") or "").strip()[:200] or "the offer was too low"
            client.decline_offer(offer, reason)
        else:
            client.accept_offer(offer)
        with S.lock:
            if S.client is client and S.user_id == uid:
                S.offer_actions[str(offer_id)] = action
                S.listings_snapshot = None
                if "offers" in S.inbox:
                    S.inbox["offers"]["next_check"] = None
        return jsonify({"ok": True, "message": {"accept": "Oferta aceita.", "decline": "Oferta recusada.", "counter": "Contraproposta enviada."}[action]})
    finally:
        OFFER_ACTION_LOCK.release()


@app.get("/api/conversations")
@api
def api_conversations(client, uid):
    active = request.args.get("active", "true").lower() != "false"
    convos = client.get_conversations(active, uid)
    return jsonify({"ok": True, "active": active, "conversations": to_json(list(convos.values()))})


@app.get("/api/messages")
@api
def api_messages(client, uid):
    try:
        user, convo = int(request.args["user_id"]), int(request.args["conversation_id"])
    except (KeyError, ValueError):
        raise ValueError("Informe user_id e conversation_id válidos.")
    return jsonify({"ok": True, "messages": to_json(client.get_messages(user, convo))})


@app.post("/api/messages")
@api
def api_send_message(client, uid):
    data = body()
    user = int_field(data, "user_id", "ID de usuário")
    text = str(data.get("message", "")).strip()
    if not text:
        raise ValueError("A mensagem não pode estar vazia.")
    client.send_message(user, text[:2000])
    return jsonify({"ok": True})


@app.post("/api/conversations/action")
@api
def api_conversation_action(client, uid):
    data = body()
    convo = int_field(data, "conversation_id", "ID de conversa")
    if data.get("action") not in ("accept", "archive"):
        raise ValueError("Ação inválida.")
    client.set_conversation_active(convo, data["action"] == "accept")
    return jsonify({"ok": True})


@app.post("/api/users/action")
@api
def api_user_action(client, uid):
    data = body()
    user = int_field(data, "user_id", "ID de usuário")
    action = data.get("action")
    if action == "block":
        client.block_user(user)
    elif action == "review":
        stars = int_field(data, "stars", "Nota")
        if not 1 <= stars <= 5:
            raise ValueError("A nota deve ir de 1 a 5.")
        client.send_review(user, stars, str(data.get("description", ""))[:500])
    else:
        raise ValueError("Ação inválida.")
    return jsonify({"ok": True})


@app.get("/api/user-search")
@api
def api_user_search(client, uid):
    name = request.args.get("username", "").strip()
    if not name:
        raise ValueError("Informe um nome de usuário.")
    found = client.search_user(name)
    if found is None:
        return fail("Usuário não encontrado.", 404)
    return jsonify({"ok": True, "user_id": found})


def main() -> None:
    autoconnect()
    threading.Thread(target=auto_loop, name="auto-relist", daemon=True).start()
    threading.Thread(target=rotation_loop, name="rotation-routines", daemon=True).start()
    threading.Thread(target=inbox_loop, name="traderie-inbox", daemon=True).start()
    print(f"Painel em http://{HOST}:{PORT}  (Ctrl+C para encerrar)")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)  # nunca use 0.0.0.0


if __name__ == "__main__":
    main()
