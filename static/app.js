"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let state = { configured: false, auth_set: false, policy: {} };
let currentChat = null;
let lastNotif;
let listingsCache = [];
let formFilled = false;
let connectFocusBefore = null;
let loginIntroSeen = false;
let modalSelection = [];
let modalFocusBefore = null;
let currentPage = "market";
let rotationCache = [];
let modalItemName = "";
let rotationModalFocus = null;
let rotationSelectedId = null;
let resolvedImages = new Map();
let imageLookupPending = false;
let imageMisses = 0;
let imageExpected = 0;
let toastTimer = null;
let editorCatalogue = [];
let editorSelected = null;
let editorOpenRequest = 0;
let editorSearchTimer = null;
let editorSubmitting = false;
let editorPage = 0;
let offersForListingId = null;
let offersModalFocus = null;
let activeListCategory = "all";
let activeOffersCategory = "all";
let offersCache = [];
let offersKind = "received";
let editorCategory = "species";
const MARKET_CATEGORIES = ["all","species","slots","plushies","palettes","other"];
let tradeChatContext = null;
let tradeChatRequest = 0;
let audioContext = null;
let audioEnabled = false;
try { audioEnabled = localStorage.getItem('traderie.sound.enabled') === '1'; } catch (_) { /* navegação privada */ }
function updateSoundUi() {
  const el=$('sound-toggle'); if(!el)return;
  el.textContent= audioEnabled ? '♫  Sons ligados' : '♫  Sons desligados';
  el.setAttribute('aria-pressed',String(audioEnabled));
}
function uiTone(kind='tap') {
  if(!audioEnabled || !window.AudioContext && !window.webkitAudioContext)return;
  try {
    audioContext ||= new (window.AudioContext||window.webkitAudioContext)();
    if(audioContext.state==='suspended')audioContext.resume().catch(()=>{});
    const osc=audioContext.createOscillator(), gain=audioContext.createGain();
    const now=audioContext.currentTime;
    osc.type='sine'; osc.frequency.setValueAtTime(kind==='ok'?540:kind==='error'?220:380, now);
    osc.frequency.exponentialRampToValueAtTime(kind==='ok'?730:kind==='error'?170:440, now+0.065);
    gain.gain.setValueAtTime(0.0001,now);gain.gain.exponentialRampToValueAtTime(0.014,now+0.009);
    gain.gain.exponentialRampToValueAtTime(0.0001,now+0.085);
    osc.connect(gain).connect(audioContext.destination);osc.start(now);osc.stop(now+0.092);
  }catch(_){ /* Áudio é opcional. */ }
}
function toggleSound() {
  audioEnabled=!audioEnabled;
  try{localStorage.setItem('traderie.sound.enabled',audioEnabled?'1':'0');}catch(_){}
  updateSoundUi();uiTone('ok');
}




async function api(url, method = "GET", body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (method !== "GET") opts.body = JSON.stringify(body ?? {});
  try {
    const r = await fetch(url, opts);
    const d = await r.json().catch(() => ({ ok: false, error: "Resposta inválida do servidor local." }));
    if (!r.ok && !d.error) d.error = "Erro HTTP " + r.status;
    return d;
  } catch (e) {
    return { ok: false, error: "Servidor local indisponível. O terminal ainda está aberto?" };
  }
}

function showToast(message, positive = true) {
  const el = $('ui-toast');
  el.textContent = message;
  uiTone(positive?'ok':'error');
  el.className = 'ui-toast' + (positive ? '' : ' toast-error');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.classList.add('hidden'); }, 5500);
}

function say(id, msg, ok = false) {
  const el = $(id);
  el.textContent = msg || "";
  el.className = "status " + (msg ? (ok ? "ok" : "err") : "");
}

// ---- estado / liberação dos botões -------------------------------------------
// Um botão com data-ep fica ativo se há token OU o endpoint foi aceito sem token.
const canUse = (ep) => !!state.configured && (state.auth_set || (state.policy || {})[ep] === "public");

function applyState(s) {
  const previousPermission = JSON.stringify([state.auth_set, state.policy]);
  state = s;
  if(editorSelected) editorPreview();
  $("auto-next").dataset.deadline=s.auto_relist ? (s.next_auto_run || "") : "";
  $("auto-next").textContent=s.auto_relist?"Verificando disponibilidade…":"Monitoramento pausado";
  document.querySelectorAll("[data-ep]:not([data-relist]):not([data-offer]):not([data-convo-action])").forEach((b) => {
    b.disabled = !canUse(b.dataset.ep);
    b.title = b.disabled ? "Requer o token Authorization" : "";
  });
  if (JSON.stringify([s.auth_set, s.policy]) !== previousPermission) renderListings(); // preserva detalhes abertos durante atualizações periódicas
  $("connection-dot").classList.toggle("online", !!s.configured);
  $("sidebar-user").textContent = s.username || (s.user_id ? `Conta #${s.user_id}` : "Desconectado");
  $("sidebar-mode").textContent = s.auth_set ? "Modo completo" : s.configured ? "Somente leitura" : "Conecte sua conta";
  if (document.activeElement !== $("routine-minutes") && document.activeElement !== $("routine-auto")) {
    $("routine-auto").checked = !!s.auto_relist;
    $("routine-minutes").value = s.check_minutes || 30;
  }
  $("mode").textContent = !s.configured ? "" : s.auth_set ? "Modo completo (token em memória)." : "Sem token: só endpoints públicos. Use “Testar endpoints”.";

  const auto = $("autostatus");
  auto.className = "status";
  auto.textContent = s.auto_relist
    ? `Monitoramento ativo. ` + (s.last_auto_result ? `Última: ${s.last_auto_result}` : "Aguardando 1ª execução.")
    : s.last_auto_result || "";
  if (!formFilled && s.saved) { // preenche o formulário com a última conexão (sem token)
    formFilled = true;
    if (s.saved.slug) $("slug").value = s.saved.slug;
    if (s.saved.username) $("username").value = s.saved.username;
    if (s.saved.user_id) $("uid").value = s.saved.user_id;
    if (s.saved.check_minutes) $("routine-minutes").value = String(s.saved.check_minutes);
  }
}

async function refreshState() {
  const d = await api("/api/state");
  if (d.ok) {applyState(d.state); connectIntro(d.state);}
}

async function saveConfig() {
  const d = await api("/api/config", "POST", {
    slug: $("slug").value, username: $("username").value, user_id: $("uid").value,
    auth: $("auth").value, auto_relist: $("routine-auto").checked, check_minutes: $("routine-minutes").value,
  });
  if (!d.ok) return say("conn", d.error || "Falha ao conectar.");
  $("auth").value = "";
  $("diag").classList.add("hidden");
  say("conn", `${d.message}${d.status ? " Status no Traderie: " + d.status : ""}`, true);
  applyState(d.state);
  if ($("routine-auto").checked && "Notification" in window && Notification.permission === "default") Notification.requestPermission();
}

async function clearAuth() {
  const d = await api("/api/clear-auth", "POST");
  say("conn", d.message || d.error, d.ok);
  if (d.ok) applyState(d.state);
}

// Falhas de autorização reaproveitam a mesma mensagem em qualquer painel.
function fail(id, d) { say(id, d.error || "Falha."); if (d.auth_required) refreshState(); }

// ---- diagnóstico ---------------------------------------------------------------
const VERDICT = { ok: "OK", auth: "exige token", blocked: "bloqueado", notfound: "404", error: "erro", network: "sem rede" };
const cell = (c) => c ? `${esc(c.status ?? "—")} ${esc(VERDICT[c.verdict] || c.verdict)}${c.count != null ? " (" + esc(c.count) + ")" : ""}` : "—";

async function diagnose() {
  say("conn", "Testando endpoints de leitura (nada é alterado na conta)…", true);
  const d = await api("/api/diagnose", "POST");
  if (!d.ok) return fail("conn", d);
  say("conn", d.has_token ? "Diagnóstico concluído (com e sem token)." : "Diagnóstico sem token. Informe um token e conecte de novo para comparar os dados.", true);
  applyState(d.state);
  const el = $("diag");
  el.classList.remove("hidden");
  el.innerHTML = `<table class="diagtable"><thead><tr><th>Endpoint</th><th>Sem token</th><th>Com token</th><th>Política</th><th>Observação</th></tr></thead><tbody>` +
    d.rows.map((r) => `<tr><td>${esc(r.endpoint)}</td><td>${cell(r.anon)}</td><td>${cell(r.token)}</td><td><span class="tag">${esc(r.policy === "public" ? "público" : "privado")}</span></td><td>${esc(r.note)}</td></tr>`).join("") +
    `</tbody></table>`;
}

// ---- status ------------------------------------------------------------------
async function loadStatus() { const d = await api("/api/status"); d.ok ? say("status", "Status atual: " + d.status, true) : fail("status", d); }
const STATUS_LABELS = { online: "Online", offline: "Offline", busy: "Ocupado" };
async function setAccountStatus(status) {
  if (!Object.hasOwn(STATUS_LABELS, status)) return;
  const d = await api("/api/online", "POST", {status});
  d.ok ? say("status", "Status alterado para " + STATUS_LABELS[d.status], true) : fail("status", d);
}


// ---- anúncios ----------------------------------------------------------------
const imageSafe = (url) => {
  try { const u = new URL(String(url)); return u.protocol === "https:" ? u.href : null; }
  catch { return null; }
};
const propEntries = (listing) => Object.values(listing.properties || {}).filter((p) => p && typeof p === "object");
// Ícones oficiais das propriedades de Creatures of Sonaria. Não usamos o token
// Authorization: as imagens são solicitadas diretamente ao CDN público.
const COS_PROPERTY_CDN = "https://cdn.nookazon.com/creaturesofsonaria/properties/";
const COS_ICON_NAMES = Object.freeze({
  glowtail: "Glow_Tail", glow_tail: "Glow_Tail", glow_tail_mutation: "Glow_Tail",
  bite: "Bite", damage: "Damage", shadow: "Shadow", ghosty: "Ghosty",
  headless: "Headless", healing: "Healing", glimmer: "Glimmer", shimmer: "Shimmer",
  weight: "Weight", health: "Health", speed: "Speed", stamina_regen: "Stamina_Regen",
  albino: "Albino", albinism: "Albino", melanism: "Melanism",
  leucism: "Leucism", frostburn: "Frostburn", piebald: "Piebald"
});
function propertyIconUrl(label) {
  const key = String(label ?? "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .trim().replace(/([a-z])([A-Z])/g, "$1_$2").replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "").toLowerCase();
  // Somente propriedades reconhecidas: evita solicitar imagens para texto livre.
  // Além das opções conhecidas, segue o padrão Nome_Com_Sublinhado.png
  // para traits/mutações recém-adicionados pelo jogo (com fallback visual).
  if (!/^[a-z][a-z0-9_]{1,47}$/.test(key)) return null;
  const basename = COS_ICON_NAMES[key] || key.split("_").map(word => word.charAt(0).toUpperCase() + word.slice(1)).join("_");
  return `${COS_PROPERTY_CDN}${basename}.png`;
}
function propertyIcon(label, providedUrl) {
  const src = propertyIconUrl(label) || imageSafe(providedUrl);
  return src ? `<img class="mutation-icon" src="${esc(src)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" data-property-icon="1">` : `<span class="mutation-symbol" aria-hidden="true">✦</span>`;
}
function propertyBadge(label, providedUrl, kind = "mutation-icon-chip") {
  const clean = String(label || "").trim().replace(/_/g, " ");
  const display = /^glow\s*tail$/i.test(clean) || /^glowtail$/i.test(clean) ? "Glowtail" : clean;
  return `<span class="property-chip ${kind}" title="${esc(display)}">${propertyIcon(display, providedUrl)}<span>${esc(display)}</span></span>`;
}
function propHtml(listing) {
  return propEntries(listing).map((p) => {
    const rawName = String(p.name || "Propriedade");
    const name = rawName.replace(/\s*\([^)]*\)\s*$/, "").replace(/([a-z])([A-Z])/g,"$1 $2").trim();
    const value = String(p.value ?? "").trim();
    const yes = /^(true|yes|sim|1)$/i.test(value);
    const no = /^(false|no|não|0)$/i.test(value);
    const isBool = p.type === "bool" || yes || no;
    // Propriedades booleanas desativadas não precisam ocupar espaço no card.
    if (isBool && no) return "";
    if (isBool && yes) return propertyBadge(name, p.icon_url);
    // Traits e mutações multivalor: exibir ícone + nome de cada seleção.
    if (/^(traits?|mutations?|mutações?|mutacoes?)$/i.test(name) && value) {
      return value.split(/[,;|]+/).map(v => v.trim()).filter(Boolean)
        .map(v => propertyBadge(v, p.icon_url, "trait-chip mutation-icon-chip")).join("");
    }
    // Campos avulsos com valor reconhecido (ex.: Mutation = Glow Tail).
    if (/^(trait|mutation|mutação|mutacao)$/i.test(name) && propertyIconUrl(value)) {
      return propertyBadge(value, p.icon_url, "trait-chip mutation-icon-chip");
    }
    const kind = /trait|mutation|mutação/i.test(name) ? "trait-chip" : /slot|age|weight|damage|health|stamina/i.test(name) ? "slot-chip" : "";
    return `<span class="property-chip ${kind}"><b>${esc(name)}:</b> ${esc(value)}</span>`;
  }).join("");
}

function listingArt(x, group = false) {
  const src = imageSafe(resolvedImages.get(String(x.item_id)) || x.image_url);
  if (src) {
    return `<img class="${group ? "group-image" : "listing-image"}" src="${esc(src)}" loading="lazy" alt="${esc(x.item || "Item")}" referrerpolicy="no-referrer" data-image-fallback="1">`;
  }
  return `<div class="${group ? "group-image" : "listing-image"} listing-image-placeholder group-letter" aria-hidden="true">${esc(String(x.item || "?").trim().charAt(0).toUpperCase())}</div>`;
}
function timeAgo(dateText, now = Date.now()) {
  const time = Date.parse(dateText || '');
  if (!Number.isFinite(time)) return 'em horário desconhecido';
  const elapsed = Math.max(0, Math.floor((now - time) / 1000));
  if (elapsed < 60) return `há ${elapsed} s`;
  if (elapsed < 3600) return `há ${Math.floor(elapsed / 60)} min ${elapsed % 60} s`;
  if (elapsed < 86400) return `há ${Math.floor(elapsed / 3600)} h ${Math.floor(elapsed % 3600 / 60)} min ${elapsed % 60} s`;
  return `há ${Math.floor(elapsed / 86400)} d ${Math.floor(elapsed % 86400 / 3600)} h ${Math.floor(elapsed % 3600 / 60)} min ${elapsed % 60} s`;
}
let lastSync=null;
let syncError=false;
function duration(ms){
  const seconds=Math.max(0,Math.ceil(ms/1000));
  if(seconds<60)return seconds+' s';
  if(seconds<3600)return Math.floor(seconds/60)+' min '+seconds%60+' s';
  return Math.floor(seconds/3600)+' h '+Math.floor(seconds%3600/60)+' min';
}
function markSynced(date){syncError=false;lastSync=date||new Date().toISOString();tickElapsed();}
function tickElapsed() {
  const now = Date.now();
  document.querySelectorAll('[data-available-at]').forEach(node=>{
    const remaining=Date.parse(node.dataset.availableAt)-now;
    node.textContent=remaining>0?'Nova verificação em '+duration(remaining):'Verificando liberação…';
  });
  const deadline=Date.parse($('auto-next').dataset.deadline||'');
  if(Number.isFinite(deadline)) $('auto-next').textContent=deadline>now?'Próxima verificação em '+duration(deadline-now):'Verificando disponibilidade…';
  if(lastSync && !syncError) $('sync-status').textContent='Sincronizado '+timeAgo(lastSync,now);
  document.querySelectorAll('[data-updated]').forEach(node => {
    const label = 'Atualizado ' + timeAgo(node.dataset.updated, now);
    if (node.textContent !== label) node.textContent = label;
  });
}
setInterval(tickElapsed, 1000);
function renderCard(x) {
  const tag = x.eligible ? "Disponível para republicar" : x.refresh_available_at ? "Liberação agendada" : x.availability_known ? "Aguardando liberação" : "Disponibilidade não informada";
  const statusClass = x.eligible ? "" : x.eligible_in_hours != null ? "pending" : "unknown";
  const can = canUse("listings.refresh"); // Disponibilidade sem flag: tentativa manual permitida; API decide.
  const props = propHtml(x);
  return `<article class="listing-card listing-clickable" tabindex="0" role="button" aria-label="Ver ofertas de ${esc(x.item || 'item')}" data-card-offers="${Number(x.id)}">
    <div class="listing-card-layout">
      <div class="listing-art-large">${listingArt(x)}</div>
      <div class="listing-card-body">
        <div class="listing-main"><div class="listing-information">
          <div class="listing-title"><strong>${esc(x.item || "Item desconhecido")}</strong>${x.amount > 1 ? `<span class="listing-quantity">×${esc(x.amount)}</span>` : ""}</div>
          <div class="listing-subtitle">Anúncio #${esc(x.id)}</div></div>
          <span class="eligibility ${statusClass}" ${!x.eligible && x.refresh_available_at ? `data-available-at="${esc(x.refresh_available_at)}"` : ""}>${esc(tag)}</span></div>
        ${props ? `<div class="listing-details"><div class="property-list always-visible">${props}</div></div>` : `<div class="listing-details muted">Sem características informadas.</div>`}
        <div class="listing-bottom"><small class="elapsed-text" data-updated="${esc(x.updated)}">Atualizado ${esc(timeAgo(x.updated))}</small><div class="listing-actions"><a target="_blank" rel="noopener noreferrer" href="${esc(x.url)}">Abrir no site ↗</a><button data-ep="listings.refresh" data-relist="${Number(x.id)}" ${can ? "" : "disabled"}>${x.eligible ? 'Republicar' : 'Tentar relist'}</button><button class="secondary" data-fill-create="${Number(x.id)}" data-ep="listings.create" ${canUse("listings.create") ? "" : "disabled"}>Usar como modelo</button><button class="danger icon-button" data-delete-one="${Number(x.id)}" data-ep="listings.delete" ${canUse("listings.delete") ? "" : "disabled"} title="Excluir anúncio">✕</button></div></div>
      </div>
    </div>
  </article>`;
}
function renderListings() {
  const filter = $("listfilter").value.trim().toLocaleLowerCase("pt-BR");
  const counts = Object.fromEntries(MARKET_CATEGORIES.map(category => [category, category === 'all' ? listingsCache.length : listingsCache.filter(x=> (x.category||'other') === category).length]));
  document.querySelectorAll('[data-cat-count]').forEach(el => { el.textContent = counts[el.dataset.catCount] ?? 0; });
  const rows = listingsCache.filter((x) => {
    if (activeListCategory !== 'all' && (x.category || 'other') !== activeListCategory) return false;
    const haystack = [x.item, x.id, ...propEntries(x).flatMap((p) => [p.name, p.value])].join(" ").toLocaleLowerCase("pt-BR");
    return !filter || haystack.includes(filter);
  });
  const grouped = $("group-toggle").checked;
  if (!rows.length) {
    $("listings").innerHTML = `<div class="empty-state"><span>⌕</span><strong>Nenhum anúncio encontrado</strong><p>${listingsCache.length ? "Tente outro filtro." : "Conecte sua conta e clique em Carregar."}</p></div>`;
    return;
  }
  if (!grouped) {
    $("listings").innerHTML = `<div class="listing-grid">${rows.map(renderCard).join("")}</div>`;
    return;
  }
  const groups = new Map();
  for (const row of rows) {
    const item = String(row.item || "Item desconhecido");
    const key = item.toLocaleLowerCase("pt-BR");
    if (!groups.has(key)) groups.set(key, { name: item, rows: [] });
    groups.get(key).rows.push(row);
  }
  $("listings").innerHTML = Array.from(groups.values()).sort((a,b) => a.name.localeCompare(b.name, "pt-BR")).map((g, i) => {
    const first = g.rows.find((x) => imageSafe(x.image_url)) || g.rows[0];
    return `<section class="listing-group"><div class="group-heading"><div class="group-heading-left">${listingArt(first, true)}<h2>${esc(g.name)}</h2><span class="group-count">${g.rows.length} anúncio(s)</span></div>
    <div class="group-actions"><button class="secondary" data-create-routine="${i}" title="Criar rotina para esse item">Criar rotina</button><button class="danger" data-select-group="${i}" title="Revisar anúncios deste item">Selecionar…</button></div></div>
    <div class="listing-grid">${g.rows.map(renderCard).join("")}</div></section>`;
  }).join("");
  window.__listingGroups = Array.from(groups.values()).sort((a,b) => a.name.localeCompare(b.name, "pt-BR"));
}
function openGroupModal(index) {
  const group = (window.__listingGroups || [])[index];
  if (!group) return;
  modalSelection = group.rows.map((x) => ({ ...x, checked: true }));
  modalItemName = group.name;
  modalFocusBefore = document.activeElement;
  $("modal-title").textContent = `Anúncios de ${group.name}`;
  $("modal-description").textContent = "Selecione os anúncios. Para excluí-los será necessário confirmar o nome exato do item; essa ação não poderá ser desfeita.";
  $("modal-status").textContent = "";
  $("modal-backdrop").classList.remove("hidden");
  $("modal-backdrop").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  renderModal();
  $("modal-close").focus();
}
function renderModal() {
  $("modal-list").innerHTML = modalSelection.map((x, i) => `<label class="modal-entry"><input type="checkbox" data-modal-index="${i}" ${x.checked ? "checked" : ""}><div class="entry-text"><strong>${esc(x.item)} · Anúncio #${esc(x.id)}</strong><small>${esc(timeAgo(x.updated))}</small></div></label>`).join("");
  const selected = modalSelection.filter((x) => x.checked).length;
  $("modal-count").textContent = `${selected} de ${modalSelection.length} selecionados`;
  $("modal-export").disabled = selected === 0;
  $("modal-delete").disabled = selected === 0 || !canUse("listings.delete");
}
function closeGroupModal() {
  $("modal-backdrop").classList.add("hidden");
  $("modal-backdrop").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  modalFocusBefore?.focus();
}
async function exportSelection() {
  const links = modalSelection.filter((x) => x.checked).map((x) => x.url);
  if (!links.length) return;
  try {
    await navigator.clipboard.writeText(links.join("\n"));
    say("modal-status", `${links.length} link(s) copiado(s).`, true);
  } catch {
    say("modal-status", "Não foi possível acessar a área de transferência. Abra o anúncio no site.");
  }
}
const PAGE_FOR_SECTION = {listings:"market", routines:"market", connection:"account", users:"account", advanced:"account"};
function navigate(page) {
  const section = PAGE_FOR_SECTION[page];
  const target = section || page;
  if (!document.querySelector(`[data-view="${target}"]`)) return;
  currentPage = target;
  document.querySelectorAll("[data-view]").forEach((el) => {
    const showing = el.dataset.view === target;
    el.hidden = !showing;
    el.classList.toggle("active-page", showing);
  });
  document.querySelectorAll("[data-page]").forEach((el) => {
    const active = el.dataset.page === target;
    el.classList.toggle("active", active);
    if (active) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current");
  });
  if (target === "market") {
    $("routine-auto").checked = !!state.auto_relist;
    $("routine-minutes").value = state.check_minutes || 30;
    if (state.configured) loadRotations();
  }
  if (section && page !== "listings" && page !== "connection" && page !== "offers") {
    const panel = $("panel-"+page);
    if (panel) {
      panel.open = true;
      requestAnimationFrame(() => panel.scrollIntoView({behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block:"start"}));
    }
  } else if (page !== "routines") {
    window.scrollTo({top:0,behavior:"instant"});
  }
}
async function saveRoutine() {
  const minutes = Number($("routine-minutes").value);
  if (!Number.isInteger(minutes) || minutes < 5 || minutes > 1440) return say("routine-status", "Escolha um intervalo de 5 a 1440 minutos.");
  const d = await api("/api/auto-relist", "POST", { enabled: $("routine-auto").checked, check_minutes: minutes });
  if (!d.ok) return fail("routine-status", d);
  applyState(d.state);

  say("routine-status", d.state.auto_relist ? `Ativada. Acompanhando a disponibilidade no Traderie.` : "Monitoramento pausado.", true);
}

async function loadListings() {
  const d = await api("/api/listings");
  if (!d.ok) { syncError=true;$("sync-status").textContent="Sincronização indisponível · dados anteriores preservados"; return fail("listingstatus", d); }
  listingsCache = d.listings;
  markSynced(d.checked_at);
  resolvedImages.clear();
  imageMisses = 0;
  const imageCount = listingsCache.filter(x => imageSafe(resolvedImages.get(String(x.item_id)) || x.image_url)).length;
  $("image-summary").textContent = `Imagens fornecidas: ${imageCount}/${listingsCache.length}. ${imageCount < listingsCache.length ? "Buscando imagens pelo catálogo público, sem compartilhar seu token..." : "Carregamento das imagens depende da disponibilidade do CDN."}`;
  const eligible = d.listings.filter((x) => x.eligible).length;
  const unknown = d.listings.filter(x => !x.availability_known).length;
  say("listingstatus", `${d.listings.length} anúncio(s), ${eligible} disponíveis para republicar.${unknown ? ` ${unknown} sem dados de disponibilidade.` : ''}`, true);
  $("listing-summary").textContent = `${d.listings.length} anúncios, ${eligible} prontos para republicar.`;
  renderListings();
  tickElapsed();
  void resolveMissingImages();
}

async function resolveMissingImages() {
  if (imageLookupPending) return;
  const seen = new Set();
  const missing = [];
  for (const x of listingsCache) {
    const id = String(x.item_id || "");
    if (!/^\d+$/.test(id) || seen.has(id) || x.image_url || resolvedImages.has(id)) continue;
    seen.add(id); missing.push(id);
  }
  if (!missing.length) return;
  imageLookupPending = true;
  let resolved = 0;
  try {
    for (let i = 0; i < Math.min(missing.length, 24); i += 12) {
      const batch = missing.slice(i, i + 12);
      const d = await api('/api/item-images?ids=' + encodeURIComponent(batch.join(',')));
      if (!d.ok) { $("image-summary").textContent = 'Falha ao consultar imagens do catálogo: ' + (d.error || 'API indisponível'); break; }
      for (const [id, url] of Object.entries(d.images || {})) {
        if (imageSafe(url)) { resolvedImages.set(id, url); resolved++; }
      }
      renderListings();
    }
  } finally {
    imageLookupPending = false;
    const current = listingsCache.filter(x => imageSafe(resolvedImages.get(String(x.item_id)) || x.image_url)).length;
    $("image-summary").textContent = `${current}/${listingsCache.length} anúncios com URL de imagem. ${resolved ? `${resolved} imagem(ns) do catálogo encontradas. ` : ''}Se faltarem imagens, use Usuário → Status e diagnóstico → Imagens dos itens para associar uma URL HTTPS pública. URLs que falham no navegador mostram um marcador.`;
  }
}
async function setManualImage(clear = false) {
  const itemId = $('image-item-id').value.trim();
  const url = clear ? '' : $('image-item-url').value.trim();
  if (!/^\d+$/.test(itemId)) return say('image-status', 'Informe um ID de item numérico.');
  if (!clear && !imageSafe(url)) return say('image-status', 'Informe uma URL HTTPS pública de imagem.');
  const d = await api('/api/item-images', 'POST', {item_id:itemId, image_url:url});
  if (!d.ok) return fail('image-status', d);
  if (clear) resolvedImages.delete(itemId); else resolvedImages.set(itemId, d.image_url);
  renderListings();
  say('image-status', clear ? 'Associação removida.' : 'Imagem salva. Se o endereço funcionar, aparecerá nos anúncios deste item.', true);
}

async function relistOne(id) {
  if (!confirm("Republicar o anúncio #" + id + "?")) return;
  const d = await api("/api/relist", "POST", { listing_id: id });
  d.ok ? (say("listingstatus", "Anúncio #" + id + " republicado.", true), loadListings()) : fail("listingstatus", d);
}

async function relistAll() {
  if (!confirm("Republicar somente anúncios cuja disponibilidade foi confirmada pela API?")) return;
  say("listingstatus", "Processando…", true);
  const d = await api("/api/relist-all", "POST", {});
  if (!d.ok) return fail("listingstatus", d);
  const failed = d.results.filter((r) => !r.ok);
  say("listingstatus", `${d.relisted}/${d.results.length} republicados (${d.checked} verificados).` + (failed.length ? ` Falha: ${failed[0].error}` : ""), !failed.length);
  loadListings();
}

// ---- Catálogo, editor por categoria e propriedades selecionáveis ----------------
const EDITOR_NAMES = {species:'Espécie',slots:'Slot',plushies:'Plushie',palettes:'Paleta'};
const PROP_ORDER = ['gender','palette','mutation','trait','veneration','elder'];
function editorPropertyGroup(name) {
  const n = String(name||'').toLowerCase();
  if (/species or slot|species or stored/.test(n)) return 'species-mode';
  if (/gender|gênero/.test(n)) return 'gender';
  if (/palette|paleta/.test(n)) return 'palette';
  if (/mutation|mutação/.test(n)) return 'mutation';
  if (/traits?|traços?/.test(n)) return 'trait';
  if (/veneration/.test(n)) return 'veneration';
  if (/elder type/.test(n)) return 'elder';
  return 'other';
}
// A criação usa APENAS o catálogo público; nunca os próprios anúncios.
function combineCatalogue(remote = []) {
  const map = new Map();
  for (const item of remote) {
    const id = Number(item?.id);
    if (!Number.isSafeInteger(id) || id <= 0 || !item?.name) continue;
    map.set(String(id), {...item, id, properties: item.properties || []});
  }
  return [...map.values()];
}
function editorMatching(item) {
  if(editorCategory==='slots'||editorCategory==='species')return item.category==='species'||item.category==='slots';
  return item.category===editorCategory;
}
function renderEditorSuggestions(items, query='') {
  const target=$('editor-results');
  const filtered=items.filter(editorMatching).filter(x=>!query||x.name.toLowerCase().includes(query.toLowerCase()));
  if(!filtered.length) {
    target.innerHTML='<p class="muted editor-no-results">Nenhum item encontrado nesta categoria. Verifique a conexão ou tente outra pesquisa.</p>';
    return;
  }
  const selectedId=String(editorSelected?.id||'');
  target.innerHTML=filtered.map(x=>{
    const img=imageSafe(x.image_url);
    const icon=img?`<img src="${esc(img)}" loading="lazy" alt="" referrerpolicy="no-referrer" data-image-fallback="1">`:'<span class="editor-result-fallback">✧</span>';

    return `<button type="button" class="editor-result ${String(x.id)===selectedId?'selected':''}" data-editor-select="${Number(x.id)}" aria-pressed="${String(x.id)===selectedId}">${icon}<span class="editor-result-meta"><strong>${esc(x.name)}</strong><small>${esc(EDITOR_NAMES[editorCategory])}</small></span><span class="editor-result-action">${String(x.id)===selectedId?'Selecionado ✓':'Selecionar →'}</span></button>`;
  }).join('');
}
function editorSpeciesOptions(items) {
  const currentId=$('editor-item-id').value;
  editorCatalogue=items;
  const filtered=items.filter(editorMatching);
  $('editor-species').innerHTML='<option value="">Selecione um item…</option>'+filtered.map(item=>
    htmlOption(item.id,`${item.name} · ${item.source||'Traderie'}`,String(item.id)===String(currentId))).join('');
  renderEditorSuggestions(items, $('editor-search').value.trim().toLowerCase());
}
async function searchEditorSpecies(append=false){
  const query=$('editor-search').value.trim();
  const category=editorCategory;
  const page=append?editorPage+1:0;
  const token=++editorOpenRequest;
  $('editor-more').disabled=true;
  $('editor-results').setAttribute('aria-busy','true');
  if(!append) $('editor-results').innerHTML='<div class="catalog-state">Buscando no catálogo do Traderie…</div>';
  $('editor-result-count').textContent='Carregando';
  say('editor-status','');
  const d=await api('/api/catalog/search?q='+encodeURIComponent(query)+'&category='+encodeURIComponent(category)+'&page='+page);
  if(token!==editorOpenRequest||$('editor-backdrop').classList.contains('hidden'))return;
  $('editor-results').setAttribute('aria-busy','false');
  if(!d.ok){
    $('editor-more').disabled=false;
    if(append){say('editor-status',d.error||'Não foi possível carregar mais itens.');return;}
    $('editor-more').hidden=true;
    editorCatalogue=[];
    $('editor-result-count').textContent='Indisponível';
    $('editor-results').innerHTML='<div class="catalog-state"><strong>Não foi possível carregar o catálogo</strong><p></p><button class="secondary" id="editor-retry">Tentar novamente</button></div>';
    $('editor-results').querySelector('p').textContent=d.error||'Verifique sua conexão.';
    return;
  }
  const items=combineCatalogue(append?[...editorCatalogue,...(d.items||[])]:d.items||[]);
  editorPage=page;
  editorSpeciesOptions(items);
  $('editor-result-count').textContent=`${items.length} itens carregados`;
  $('editor-more').hidden=!d.has_more;
  $('editor-more').disabled=false;
}
function editorSchema(){
  // Somente propriedades e IDs provenientes do catálogo público entram no editor.
  const byId=new Map();
  for(const item of (editorSelected?[editorSelected]:[])){
    if(editorSelected && item.id!==editorSelected.id && !['species','slots'].includes(editorCategory))continue;
    for(const pr of item.properties||[]){
      const id=Number(pr.id);if(!Number.isSafeInteger(id)||id<=0)continue;
      if(!byId.has(id))byId.set(id,{...pr,id,name:pr.name,type:pr.type||'string',options:[]});
      const existing=byId.get(id);
      existing.options=[...new Set([...(existing.options||[]),...(pr.options||[])])];
    }
  }
  return [...byId.values()].filter(p=>editorPropertyGroup(p.name)!=='species-mode');
}
function editorPreview(){
  const item=editorSelected;
  $('editor-preview-name').textContent=item?.name||'Selecione um item';
  $('editor-preview-type').textContent=EDITOR_NAMES[editorCategory];
  $('editor-submit').disabled=editorSubmitting || !item || !state.auth_set;
  $('editor-connect').hidden=!!state.auth_set;
  $('editor-account-hint').textContent=state.auth_set?'Tudo pronto? Revise o item e publique.':'Conecte sua conta para publicar. Você já pode explorar o catálogo.';
  const img=imageSafe(item?.image_url);
  $('editor-preview').querySelector('.editor-preview-art').innerHTML=img?
    `<img src="${esc(img)}" alt="${esc(item?.name||"Item")}" referrerpolicy="no-referrer" data-image-fallback="1">`:'✦';
}
function setEditorCategory(category){
  if(!EDITOR_NAMES[category])return;
  editorOpenRequest++; clearTimeout(editorSearchTimer);
  editorCategory=category;
  document.querySelectorAll('[data-editor-category]').forEach(b=>{
    const active=b.dataset.editorCategory===category;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));
  });
  editorSpeciesOptions(editorCatalogue);
  if(editorSelected && !editorMatching(editorSelected)) {
    editorSelected=null; $('editor-item-id').value=''; $('editor-item-name').value='';
    $('editor-species').value='';
  }
  $('editor-slot-fields').classList.toggle('hidden',category!=='slots');
  renderEditorTraits();editorPreview();
  void searchEditorSpecies();
}
function setEditorSpecies(id){
  const item=editorCatalogue.find(x=>String(x.id)===String(id));
  editorSelected=item||null;
  if(item){$('editor-item-id').value=item.id;$('editor-item-name').value=item.name;}
  else {$('editor-item-id').value='';$('editor-item-name').value='';}
  renderEditorTraits();editorPreview();
  renderEditorSuggestions(editorCatalogue, $('editor-search').value.trim().toLowerCase());
}
function renderEditorTraits(){
  if(editorCategory!=='slots')return;
  const defs=editorSchema();
  $('editor-traits-hint').textContent=editorSelected?'Escolha as características do seu slot.':'Escolha uma criatura do catálogo para continuar.';
  if(!defs.length){$('editor-traits').innerHTML='<p class="muted">O catálogo não disponibilizou características adicionais.</p>';return;}
  const groups=new Map();
  for(const prop of defs){
    const group=editorPropertyGroup(prop.group||prop.name);
    if(!groups.has(group))groups.set(group,[]);
    groups.get(group).push(prop);
  }
  const labels={gender:'Gênero',palette:'Paleta',mutation:'Mutações',trait:'Traits',veneration:'Veneration',elder:'Elder Type',other:'Outras características'};
  $('editor-traits').innerHTML=[...PROP_ORDER,'other'].map(group=>{
    const list=groups.get(group)||[];
    if(!list.length)return '';
    const limit=list.find(p=>p.group_limit)?.group_limit;
    return `<fieldset class="trait-group"><legend>${esc(labels[group])}${limit?` · até ${Number(limit)}`:''}</legend>${list.map(prop=>{
      const id=`editor-prop-${prop.id}`;
      if(prop.type==='bool')return `<label class="trait-choice"><input id="${id}" type="checkbox" data-editor-prop="${prop.id}"/><span>${esc(prop.name)}</span></label>`;
      const opts=[...new Set((prop.options||[]).map(String).filter(Boolean))];
      if(prop.type==='number')return `<label class="trait-row">${esc(prop.name)}<input id="${id}" type="number" data-editor-prop="${prop.id}"/></label>`;
      return `<div class="trait-row"><label for="${id}">${esc(prop.name)}</label><select id="${id}" data-editor-prop="${prop.id}" aria-label="${esc(prop.name)}"><option value="">Não informar</option>${opts.map(v=>htmlOption(v,v)).join('')}</select></div>`;
    }).join('')}</fieldset>`;
  }).join('');
}
let editorFocusBefore=null;
function openEditor(x=null){
  editorFocusBefore=document.activeElement;
  editorOpenRequest++;
  editorSelected=null;
  $('editor-search').value=x?.item||'';
  $('editor-item-id').value='';
  $('editor-item-name').value='';
  $('editor-amount').value=x?.amount||1;
  $('editor-backdrop').classList.remove('hidden');
  $('editor-backdrop').setAttribute('aria-hidden','false');
  editorSpeciesOptions(combineCatalogue());
  setEditorCategory(['species','slots','plushies','palettes'].includes(x?.category)?x.category:'species');

  say('editor-status','');
  $('editor-search').focus();
}
function closeEditor(){
  editorOpenRequest++; clearTimeout(editorSearchTimer);
  $('editor-backdrop').classList.add('hidden');
  $('editor-backdrop').setAttribute('aria-hidden','true');
  editorFocusBefore?.focus();
}
function buildEditorTemplate(){
  const id=$('editor-item-id').value.trim();
  if(!/^\d+$/.test(id)||!Number.isSafeInteger(Number(id))||Number(id)<=0)throw Error('Selecione um item no catálogo.');
  const amount=Number($('editor-amount').value);
  if(!Number.isInteger(amount)||amount<1||amount>999)throw Error('Quantidade inválida (1 a 999).');
  const props=[];
  if(!editorSelected || String(editorSelected.id)!==id || !editorMatching(editorSelected))throw Error('Escolha um item da categoria correta na lista pesquisada.');
  if(['species','slots'].includes(editorCategory)){
    const mode=(editorSelected?.properties||[]).find(p=>editorPropertyGroup(p.name)==='species-mode');
    if(!mode)throw Error('Este item não disponibilizou a opção de espécie ou slot. Atualize o catálogo e tente novamente.');
    props.push({id:Number(mode.id),name:mode.name,type:'string',string:editorCategory==='slots'?'Slot':'Species'});
  }
  if(editorCategory==='slots'){
    const defs=editorSchema();
    for(const prop of defs){
      const selection=$(`editor-prop-${prop.id}`);
      if(!selection || (prop.type==='bool'?!selection.checked:!selection.value))continue;
      const raw=prop.type==='bool'?'true':selection.value;
      const kind=prop.type||'string';
      if(!['string','number','bool'].includes(kind))throw Error('Tipo de atributo não suportado.');
      const value=kind==='string'?raw:kind==='number'?Number(raw):raw==='true';
      if(kind==='number'&&!Number.isFinite(value))throw Error('Valor numérico inválido.');
      props.push({id:Number(prop.id),name:String(prop.name),type:kind,[kind]:value});
    }
  }
  const defs=editorSchema();
  for(const group of new Set(defs.map(p=>p.group).filter(Boolean))){
    const members=defs.filter(p=>p.group===group);
    const limit=members.find(p=>p.group_limit)?.group_limit;
    if(limit && props.filter(p=>members.some(m=>m.id===p.id)).length>limit)throw Error(`Escolha no máximo ${limit} em ${group}.`);
  }
  const itemType=editorSelected.item_type || {species:'Creatures',slots:'Creatures',plushies:'plushies',palettes:'palettes'}[editorCategory];
  return {item:id,amount:String(amount),itemType,makeOffer:true,free:false,selling:true,properties:props};
}
async function submitEditor() {
  let template;
  try { template = buildEditorTemplate(); }
  catch(error) { return say('editor-status',error.message); }
  const name = editorSelected.name;
  if (!confirm(`Publicar ${template.amount}x ${name} (${ EDITOR_NAMES[editorCategory] }) no Traderie?`)) return;
  editorSubmitting = true;
  $('editor-submit').disabled = true;
  say('editor-status','Publicando…',true);
  const d = await api('/api/listings/create','POST',{template, confirm:true});
  editorSubmitting = false;
  editorPreview();
  if (!d.ok) return fail('editor-status',d);
  showToast('Anúncio #'+d.listing_id+' criado.',true);
  closeEditor();
  loadListings();
}

async function deleteOne(id) {
  const x = listingsCache.find(r => Number(r.id) === id);
  if (!x) return;
  const typed = prompt(`Exclusão definitiva do anúncio #${id}. Digite EXCLUIR para confirmar:`, "");
  if (typed !== "EXCLUIR") return;
  const d = await api("/api/listings/delete", "POST", {listing_id: id, confirm: true});
  if (!d.ok) return fail("listingstatus", d);
  say("listingstatus", `Anúncio #${id} excluído.`, true);
  loadListings();
}
async function deleteSelected() {
  const chosen = modalSelection.filter(x => x.checked);
  if (!chosen.length) return;
  const typed = prompt(`Apagar definitivamente ${chosen.length} anúncio(s) de “${modalItemName}”? Digite exatamente o nome do item para confirmar:`, "");
  if (typed !== modalItemName) return;
  $("modal-delete").disabled = true;
  say("modal-status", "Excluindo…", true);
  const d = await api("/api/listings/bulk-delete", "POST", {
    item_name: modalItemName, confirm_name: typed, ids: chosen.map(x => x.id),
  });
  $("modal-delete").disabled = false;
  if (!d.ok) return fail("modal-status", d);
  say("modal-status", `${d.deleted.length} excluídos, ${d.errors.length} falhas.` + (d.errors.length ? " " + d.errors[0].error : ""), !d.errors.length);
  await loadListings();
  if (!d.errors.length) closeGroupModal();
}
async function loadRotations() {
  if (!state.configured) return;
  const d = await api("/api/rotation-routines");
  if (!d.ok) return fail("rotation-status", d);
  rotationCache = d.routines || [];
  $("rotation-list").innerHTML = rotationCache.map(r => `<article class="rotation-card"><div class="rotation-head"><strong>${esc(r.item_name)}</strong><span class="eligibility ${r.enabled ? "" : "pending"}">${r.enabled ? "Ativa" : "Pausada"}</span></div>
    <p class="muted">ID item: ${esc(r.template.item)} · A cada ${esc(r.interval_minutes)} min · ${esc(r.owned_ids.length)} anúncio(s) rastreado(s)</p>
    <p class="muted">Próximo ciclo: ${esc(r.next_run ? new Date(r.next_run).toLocaleString("pt-BR") : "não agendado")}</p>
    <p class="routine-note">${esc(r.last_result || "—")}</p>
    <div class="actions"><button class="${r.enabled ? "secondary" : ""}" data-rotation-id="${esc(r.id)}" data-rotation-action="${r.enabled ? "pause" : "enable"}" ${!r.enabled && !state.auth_set ? "disabled" : ""}>${r.enabled ? "Pausar" : "Ativar"}</button>
    <button class="secondary" data-rotation-id="${esc(r.id)}" data-rotation-action="run_now" ${!state.auth_set ? "disabled" : ""}>Executar agora</button>
    <button class="secondary" data-rotation-id="${esc(r.id)}" data-rotation-action="edit">Ver modelo</button>
    <button class="danger" data-rotation-id="${esc(r.id)}" data-rotation-action="remove" ${r.enabled ? "disabled" : ""}>Remover rotina</button></div></article>`).join("") || '<div class="empty-state"><strong>Nenhuma rotina criada</strong><p>Preencha os campos acima e salve uma rotina pausada.</p></div>';
}
function htmlOption(value, text, selected = false) {
  return `<option value="${esc(value)}" ${selected ? 'selected' : ''}>${esc(text)}</option>`;
}
function populateRotationSources(selectedId = null) {
  const choices = listingsCache.filter(x => x.item_id && Number(x.item_id) > 0);
  const sel = $('rotation-source');
  sel.innerHTML = '<option value="">Selecione um anúncio carregado</option>' + choices.map(x =>
    htmlOption(x.id, `${x.item || 'Item'} · #${x.id} · ${propEntries(x).length} característica(s)`, Number(x.id) === Number(selectedId))
  ).join('');
  sel.disabled = choices.length === 0;
  if (!choices.length) say('rotation-modal-status', 'Carregue os anúncios primeiro. A API precisa informar o ID do item para criar a rotina.');
  return choices;
}
function showRotationModal(listingId = null) {
  rotationModalFocus = document.activeElement;
  $('rotation-modal-title').textContent = 'Criar rotina';
  $('rotation-backdrop').classList.remove('hidden');
  $('rotation-backdrop').setAttribute('aria-hidden', 'false');
  document.body.style.overflow = 'hidden';
  $('rotation-name').value = '';
  $('rotation-minutes').value = '60';
  $('rotation-amount').value = '1';
  $('rotation-item-type').value = 'sub-species';
  $('rotation-offer').value = 'offer';
  say('rotation-modal-status', '');
  const choices = populateRotationSources(listingId);
  const selected = choices.find(x => Number(x.id) === Number(listingId));
  if (selected) setRotationSource(selected.id);
  else {
    rotationSelectedId = null;
    $('rotation-traits').innerHTML = '<p class="muted">Selecione um anúncio acima para escolher traits e propriedades.</p>';
    $('trait-hint').textContent = 'Nenhum modelo selecionado.';
  }
  $('rotation-source').focus();
}
function closeRotationModal() {
  $('rotation-backdrop').classList.add('hidden');
  $('rotation-backdrop').setAttribute('aria-hidden', 'true');
  document.body.style.overflow = '';
  rotationModalFocus?.focus();
}
function setRotationSource(id) {
  const x = listingsCache.find(row => Number(row.id) === Number(id));
  rotationSelectedId = x ? Number(x.id) : null;
  if (!x) {
    $('rotation-traits').innerHTML = '<p class="muted">Selecione um modelo para continuar.</p>';
    return;
  }
  $('rotation-name').value = x.item || '';
  $('rotation-amount').value = x.amount || 1;
  const props = propEntries(x);
  $('trait-hint').textContent = `${props.length} propriedade(s) disponíveis no anúncio escolhido.`;
  $('rotation-traits').innerHTML = props.map((property, i) => {
    const sameItem = listingsCache.filter(row => row.item_id && row.item_id === x.item_id);
    const possible = [...new Set(sameItem.flatMap(row => propEntries(row)
      .filter(p => String(p.id) === String(property.id)).map(p => String(p.value ?? ''))))];
    const values = possible.slice(0, 30);
    const choices = values.map(v => htmlOption(v, v, String(v) === String(property.value))).join('');
    return `<div class="trait-row"><label class="check"><input type="checkbox" data-trait-index="${i}" checked> ${esc(property.name)} <small class="muted">(${esc(property.type || 'string')})</small></label><div class="trait-field"><select data-trait-value="${i}" aria-label="Valor de ${esc(property.name)}">${choices}${htmlOption('__custom__', 'Outro valor...')}</select><input class="hidden" data-trait-custom="${i}" placeholder="Valor personalizado" aria-label="Outro valor de ${esc(property.name)}" /></div></div>`;
  }).join('') || '<div class="muted">Este anúncio não possui propriedades adicionais.</div>';
}
function buildRotationTemplate() {
  const listing = listingsCache.find(x => x.id === rotationSelectedId);
  if (!listing || !listing.item_id) throw new Error('Selecione um anúncio com ID de item válido.');
  const amount = Number($('rotation-amount').value);
  if (!Number.isInteger(amount) || amount < 1 || amount > 999) throw new Error('Quantidade deve ser de 1 a 999.');
  const properties = propEntries(listing).flatMap((p, i) => {
    if (!document.querySelector(`[data-trait-index="${i}"]`)?.checked) return [];
    const select = document.querySelector(`[data-trait-value="${i}"]`);
    const custom = document.querySelector(`[data-trait-custom="${i}"]`);
    const raw = select.value === '__custom__' ? custom.value.trim() : select.value;
    const type = p.type || 'string';
    if (!['string','number','bool'].includes(type)) throw new Error('Propriedade com tipo não suportado: ' + p.name);
    if (!Number.isSafeInteger(Number(p.id))) throw new Error('ID de propriedade inválido: ' + p.name);
    let value = raw;
    if (type === 'number') {
      if (raw === '' || !Number.isFinite(Number(raw))) throw new Error('Valor numérico inválido: ' + p.name);
      value = Number(raw);
    } else if (type === 'bool') {
      if (!['true','false'].includes(String(raw).toLowerCase())) throw new Error('Escolha verdadeiro ou falso para: ' + p.name);
      value = String(raw).toLowerCase() === 'true';
    }
    return [{id:Number(p.id), name:p.name, type, [type]:value}];
  });
  const mode = $('rotation-offer').value;
  return {
    item: String(listing.item_id), itemType:$('rotation-item-type').value, amount:String(amount),
    selling:true, makeOffer:mode==='offer', free:mode==='free', properties,
  };
}
async function addRotation() {
  let template;
  try { template = buildRotationTemplate(); } catch(e) { return say('rotation-modal-status', e.message); }
  const item_name = $('rotation-name').value.trim();
  const interval_minutes = Number($('rotation-minutes').value);
  if (!item_name || !Number.isInteger(interval_minutes) || interval_minutes < 15 || interval_minutes > 1440)
    return say('rotation-modal-status', 'Informe um nome e intervalo válido.');
  $('rotation-submit').disabled = true;
  const d = await api('/api/rotation-routines', 'POST', {item_name, interval_minutes, template});
  $('rotation-submit').disabled = false;
  if (!d.ok) return fail('rotation-modal-status', d);
  closeRotationModal();
  say('rotation-status', 'Rotina salva pausada. Revise os dados antes de ativá-la.', true);
  showToast('Rotina criada e salva como pausada.');
  await loadRotations();
}
async function rotationAction(id, action) {
  const r = rotationCache.find(x => x.id === id);
  if (!r) return;
  if (action === 'edit') {
    const raw = listingsCache.find(x => x.item_id && String(x.item_id) === String(r.template.item));
    showRotationModal(raw?.id || null);
    $('rotation-name').value = r.item_name;
    $('rotation-minutes').value = String(r.interval_minutes);
    if (raw) {
      $('rotation-amount').value = r.template.amount;
      $('rotation-item-type').value = r.template.itemType || 'sub-species';
      $('rotation-offer').value = r.template.free ? 'free' : 'offer';
      $('rotation-traits').querySelectorAll('input[data-trait-index]').forEach((cb, i) => {
        const orig = propEntries(raw)[i];
        const selected = (r.template.properties || []).find(p => String(p.id) === String(orig.id));
        cb.checked = !!selected;
        if (selected) {
          const sel = $('rotation-traits').querySelector(`[data-trait-value="${i}"]`);
          const custom = $('rotation-traits').querySelector(`[data-trait-custom="${i}"]`);
          const val = String(selected[selected.type]);
          if ([...sel.options].some(o => o.value === val)) sel.value = val;
          else { sel.value='__custom__'; custom.classList.remove('hidden'); custom.value=val; }
        }
      });
    }
    $('rotation-modal-title').textContent = 'Duplicar configuração';
    say('rotation-modal-status', 'Salvar gera uma NOVA rotina pausada; a existente não será alterada.', true);
    return;
  }
  if (action === "enable" && !confirm(`Ativar rotação de ${r.item_name} a cada ${r.interval_minutes} min? O programa criará anúncios reais e excluirá apenas os IDs criados pela rotina.`)) return;
  if (action === "run_now" && !confirm(`Executar AGORA uma criação real de ${r.item_name} e, se houver, excluir o anúncio anterior criado pela rotina?`)) return;
  if (action === "remove" && !confirm("Remover a configuração? Anúncios já criados permanecerão no Traderie.")) return;
  const d = await api("/api/rotation-routines/action", "POST", {id, action, confirm: true});
  if (!d.ok) return fail("rotation-status", d);
  say("rotation-status", d.message || "Rotina atualizada.", true);
  await loadRotations();
  if (action === "run_now") await loadListings();
}

// ---- Ofertas no contexto do anúncio ------------------------------------------
async function openListingOffers(id) {
  offersForListingId = id;
  offersModalFocus = document.activeElement;
  const listing = listingsCache.find(x => Number(x.id) === id);
  $('listing-offers-title').textContent = listing?.item || 'Anúncio #'+id;
  $('offer-modal-description').textContent = `Anúncio #${id} · Ofertas abertas recebidas. Contrapropostas são mensagens de negociação, não uma alteração formal da oferta.`;
  $('offer-backdrop').classList.remove('hidden');
  $('offer-backdrop').setAttribute('aria-hidden','false');
  $('offer-close').focus();
  await loadListingOffers(id);
}
function closeListingOffers() {
  offersForListingId = null;
  $('offer-backdrop').classList.add('hidden');
  $('offer-backdrop').setAttribute('aria-hidden','true');
  offersModalFocus?.focus();
}
async function loadListingOffers(id = offersForListingId) {
  if (!id) return;
  $('listing-offers-list').innerHTML = '<p class="muted">Carregando ofertas…</p>';
  say('listing-offers-status','');
  const d = await api('/api/listings/'+id+'/offers');
  if (offersForListingId !== id) return;
  if (!d.ok) {
    $('listing-offers-list').innerHTML = '<p class="muted">Não foi possível carregar as ofertas.</p>';
    return fail('listing-offers-status', d);
  }
  const offers = d.offers || [];
  $('listing-offers-list').innerHTML = offers.map(o => `<article class="offer-modal-entry">
     <div class="offer-modal-top"><strong>${esc(o.buyerUsername || 'Usuário #'+o.buyerID)}</strong><span class="muted">Oferta #${esc(o.offerID)}</span></div>
     <p class="muted">Comprador #${esc(o.buyerID)}</p>
     <div class="actions"><button class="secondary" data-offer-chat="${Number(o.offerID)}" data-offer-chat-kind="received">✉ Chat</button><button class="secondary" data-counter-offer="${Number(o.offerID)}" ${canUse('messages.send')?'':'disabled'}>Contraproposta via mensagem</button>
     <button class="danger" data-decline-offer="${Number(o.offerID)}" ${canUse('offers.deny')?'':'disabled'}>Recusar</button></div>
     <div class="counter-editor hidden" data-counter-box="${Number(o.offerID)}"><label for="counter-message-${Number(o.offerID)}">Sua proposta por mensagem (não é oferta formal)</label><textarea id="counter-message-${Number(o.offerID)}" data-counter-text="${Number(o.offerID)}" maxlength="800" rows="3" placeholder="Ex.: Obrigado pela oferta! Aceitaria 2x ...?"></textarea><div class="actions"><button data-send-counter="${Number(o.offerID)}">Enviar mensagem</button><button class="secondary" data-counter-cancel="${Number(o.offerID)}">Cancelar</button></div></div>
  </article>`).join('') || '<div class="empty-state"><strong>Nenhuma oferta aberta</strong><p>As ofertas recebidas para este anúncio aparecerão aqui.</p></div>';
  say('listing-offers-status',offers.length+' oferta(s) recebida(s).',true);
}
async function declineListingOffer(id) {
  if (!confirm('Recusar a oferta #'+id+'?')) return;
  const d = await api('/api/offers/action','POST',{offer_id:id,action:'decline'});
  if (!d.ok) return fail('listing-offers-status',d);
  showToast('Oferta #'+id+' recusada.',true);
  loadListingOffers();
}
async function sendListingCounterMessage(id) {
  const value = document.querySelector(`[data-counter-text="${id}"]`)?.value.trim();
  if (!value) return say('listing-offers-status','Escreva a mensagem de contraproposta.');
  if (!confirm('Enviar esta mensagem de negociação? A oferta original permanecerá aberta.')) return;
  const d = await api('/api/offers/counter-message','POST',{offer_id:id,message:value,confirm:true});
  if (!d.ok) return fail('listing-offers-status',d);
  say('listing-offers-status',d.message+(d.conversation_warning?' '+d.conversation_warning:''),true);
  showToast('Mensagem de contraproposta enviada.',true);
  document.querySelector(`[data-counter-box="${id}"]`)?.classList.add('hidden');
}

// ---- notificações ------------------------------------------------------------
async function loadNotifications() {
  const d = await api("/api/notifications?limit=50");
  if (!d.ok) return fail("notifstatus", d);
  say("notifstatus", `${d.notifications.length} notificação(ões).`, true);
  $("notifications").innerHTML = d.notifications.map((n) => `
    <div class="item"><div class="itemtop"><b>${esc(n.text)}</b><input type="checkbox" class="notifcheck" value="${esc(n.notificationID)}" aria-label="Selecionar"></div>
    <small>${esc(n.date || "")} · Usuário ${esc(n.fromUserID ?? "—")} · Anúncio ${esc(n.listingID ?? "—")}</small></div>`).join("") || '<span class="muted">Sem notificações.</span>';
}

async function markRead() {
  const ids = [...document.querySelectorAll(".notifcheck:checked")].map((x) => x.value);
  if (!ids.length) return say("notifstatus", "Selecione as notificações primeiro.");
  const d = await api("/api/notifications/read", "POST", { ids });
  d.ok ? (say("notifstatus", "Marcadas como lidas.", true), loadNotifications()) : fail("notifstatus", d);
}

// ---- ofertas -----------------------------------------------------------------
async function loadOffers(kind) {
  $("recvtab").classList.toggle("active", kind === "received");
  $("senttab").classList.toggle("active", kind === "sent");
  const d = await api("/api/offers?kind=" + kind);
  if (!d.ok) return fail("offerstatus", d);
  offersCache = d.offers || [];
  offersKind = kind;
  renderOffersByCategory();
}
function offerCategory(o) {
  const linked = listingsCache.find(x=>Number(x.id)===Number(o.listingID)) ||
    listingsCache.find(x=>Number(x.item_id)===Number(o.itemID));
  return o.item_category && o.item_category !== 'other' ? o.item_category : (linked?.category || 'other');
}
function renderOffersByCategory() {
  const offers = offersCache.filter(o=>activeOffersCategory==='all'||offerCategory(o)===activeOffersCategory);
  document.querySelectorAll('[data-offers-cat-count]').forEach(el=>{const key=el.dataset.offersCatCount;el.textContent=key==='all'?offersCache.length:offersCache.filter(o=>offerCategory(o)===key).length;});
  say("offerstatus", offers.length + " oferta(s) nesta categoria.", true);
  const kind = offersKind;
  $("offers").innerHTML = offers.map(o => {
    const linked = listingsCache.find(x=>Number(x.id)===Number(o.listingID)) || listingsCache.find(x=>Number(x.item_id)===Number(o.itemID));
    const src = imageSafe(o.image_url || linked?.image_url || resolvedImages.get(String(o.itemID)));
    const image = src ? `<img class="offer-art" src="${esc(src)}" alt="${esc(o.itemName)}" loading="lazy" referrerpolicy="no-referrer" data-image-fallback="1">` : `<div class="offer-art offer-art-placeholder" aria-hidden="true">${esc(String(o.itemName || '?').slice(0,1))}</div>`;
    const chatActions=`<div class="actions offer-actions"><button class="secondary" data-offer-chat="${Number(o.offerID)}" data-offer-chat-kind="${esc(kind)}" ${canUse('conversations')?'':'disabled'}>✉ Chat</button><button class="secondary" data-offer-chat="${Number(o.offerID)}" data-offer-chat-kind="${esc(kind)}" ${canUse('conversations')?'':'disabled'}>Negociar por mensagem</button>${kind==='received'?`<button data-ep="offers.accept" data-offer="accept" data-id="${Number(o.offerID)}" ${canUse('offers.accept')?'':'disabled'}>Aceitar</button><button class="danger" data-ep="offers.deny" data-offer="decline" data-id="${Number(o.offerID)}" ${canUse('offers.deny')?'':'disabled'}>Recusar</button>`:''}</div>`;
    return `<div class="item offer-card" data-offer-item-id="${Number(o.itemID)}"><div class="offer-card-header">${image}<div class="offer-card-text"><b>${esc(o.itemName)} — oferta #${esc(o.offerID)}</b><p>${kind === "received" ? "De: " + esc(o.buyerUsername) + " (ID " + esc(o.buyerID) + ")" : "Para: " + esc(o.sellerUsername) + " (ID " + esc(o.sellerID) + ")"}</p><small>Anúncio #${esc(o.listingID)} · quantidade ${esc(o.amount)}</small></div></div>${chatActions}</div>`;
  }).join("") || '<span class="muted">Nenhuma oferta aberta.</span>';
  void resolveOfferImages();
}
async function resolveOfferImages() {
  const pending = offersCache.filter(o=>o.itemID && !imageSafe(o.image_url) && !resolvedImages.has(String(o.itemID)));
  const ids = [...new Set(pending.map(o=>String(o.itemID)))].slice(0,36);
  for(let i=0;i<ids.length;i+=12){
    const d=await api('/api/item-images?ids='+ids.slice(i,i+12).join(','));
    if(!d.ok)break;
    for(const [key,url] of Object.entries(d.images||{})) if(imageSafe(url))resolvedImages.set(String(key),url);
  }
  // Atualiza só as imagens: não recria a lista (nem dispara uma nova consulta).
  document.querySelectorAll('.offer-card').forEach((card)=>{
    const id = card.dataset.offerItemId;
    const o=offersCache.find(entry=>String(entry.itemID)===id); if(!o)return;
    const img=imageSafe(o.image_url || resolvedImages.get(id));
    const placeholder=card.querySelector('.offer-art-placeholder');
    if(img && placeholder){const node=document.createElement('img');node.className='offer-art';node.loading='lazy';node.referrerPolicy='no-referrer';node.src=img;node.alt=o.itemName||'Item';placeholder.replaceWith(node);}
  });
}

async function offerAction(id, action) {
  let reason;
  if (action === "decline") {
    reason = prompt("Motivo da recusa (vazio = padrão: “the offer was too low”):", "");
    if (reason === null) return; // cancelou
  } else if (!confirm(`Tem certeza que deseja aceitar a oferta #${id}?`)) return;
  const d = await api("/api/offers/action", "POST", { offer_id: id, action, reason });
  if (!d.ok) return fail("offerstatus", d);
  say("offerstatus", (d.message || "Concluído.") + (d.conversation_warning ? " Aviso ao abrir conversa: " + d.conversation_warning : ""), true);
  if (action === "accept" && d.buyer_id && confirm("Enviar um cumprimento para " + (d.buyer_username || "#" + d.buyer_id) + "?")) {
    const msg = prompt("Mensagem:", "Hello! wanna trade? which region are you in?");
    if (msg && msg.trim()) {
      const s = await api("/api/messages", "POST", { user_id: d.buyer_id, message: msg.trim() });
      say("offerstatus", s.ok ? "Oferta aceita e cumprimento enviado." : "Oferta aceita; falha no cumprimento: " + s.error, s.ok);
    }
  }
  loadOffers("received");
}

// ---- Chat vinculado à oferta (API de mensagens confirmada no cliente) ----------
async function showOfferChat(id, kind='received') {
  tradeChatContext={id,kind};
  $('trade-chat-backdrop').classList.remove('hidden');
  $('trade-chat-backdrop').setAttribute('aria-hidden','false');
  $('trade-chat-text').value='';
  $('trade-chat-title').textContent='Conversa da oferta #'+id;
  $('trade-chat-subtitle').textContent='Verificando mensagens…';
  $('trade-chat-close').focus();
  uiTone();
  await reloadOfferChat();
}
function closeOfferChat() {
  tradeChatRequest++;
  tradeChatContext=null;
  $('trade-chat-backdrop').classList.add('hidden');
  $('trade-chat-backdrop').setAttribute('aria-hidden','true');
}
async function reloadOfferChat(){
  if(!tradeChatContext)return;
  const token=++tradeChatRequest;
  const {id,kind}=tradeChatContext;
  say('trade-chat-status','');
  $('trade-chat-messages').innerHTML='<p class="muted">Carregando mensagens do Traderie…</p>';
  const d=await api('/api/offers/chat?offer_id='+encodeURIComponent(id)+'&kind='+encodeURIComponent(kind));
  if(token!==tradeChatRequest)return;
  if(!d.ok){$('trade-chat-messages').innerHTML='<p class="muted">Mensagens indisponíveis.</p>';return fail('trade-chat-status',d);}
  $('trade-chat-subtitle').textContent='Com '+(d.username||'#'+d.user_id);
  const hasConvo=!!d.conversation_id;
  $('trade-chat-start').classList.toggle('hidden',hasConvo);
  $('trade-chat-send').disabled=!hasConvo;
  $('trade-chat-text').disabled=!hasConvo;
  $('trade-chat-messages').innerHTML=hasConvo ? (d.messages||[]).map(m=>{
     const incoming=Number(m.fromID)===Number(d.user_id);
     return `<div class="trade-bubble ${incoming?'incoming':'outgoing'}"><small>${incoming?esc(d.username||'Contato'):'Você'}</small><p>${esc(m.text)}</p></div>`;
  }).join('') || '<p class="muted">Nenhuma mensagem nesta conversa.</p>' : '<p class="muted">Ainda não há uma conversa para esta oferta. Inicie-a para negociar usando o chat do Traderie.</p>';
  $('trade-chat-messages').scrollTop=$('trade-chat-messages').scrollHeight;
}
async function offerChatAction(action){
  if(!tradeChatContext)return;
  const {id,kind}=tradeChatContext;
  const message=$('trade-chat-text').value.trim();
  if(action==='send'&&!message)return say('trade-chat-status','Digite uma mensagem.');
  if(action==='start'&&!confirm('Iniciar uma conversa do Traderie com o usuário desta oferta?'))return;
  const btn=action==='send' ? $('trade-chat-send') : $('trade-chat-start');
  btn.disabled=true;
  const d=await api('/api/offers/chat','POST',{offer_id:id,kind,action,confirm:action==='start',message});
  btn.disabled=false;
  if(!d.ok)return fail('trade-chat-status',d);
  if(action==='send')$('trade-chat-text').value='';
  showToast(d.message||'Concluído.',true);
  await reloadOfferChat();
}

// ---- conversas ---------------------------------------------------------------
async function loadConversations(active) {
  const d = await api("/api/conversations?active=" + active);
  if (!d.ok) return fail("convstatus", d);
  const vals = d.conversations || [];
  say("convstatus", vals.length + " conversa(s).", true);
  $("conversations").innerHTML = vals.map((c) => `
    <div class="item"><b>Usuário #${esc(c.userID)}</b><p><small>Conversa #${esc(c.conversationID)}</small></p>
    <div class="actions"><button data-chat-user="${Number(c.userID)}" data-chat-id="${Number(c.conversationID)}">Mensagens</button>
    <button class="secondary" data-ep="conversations.update" data-convo-action="${active ? "archive" : "accept"}" data-id="${Number(c.conversationID)}" data-active="${active}" ${canUse("conversations.update") ? "" : "disabled"}>${active ? "Arquivar" : "Reativar"}</button></div></div>`).join("") || '<span class="muted">Nenhuma conversa.</span>';
}

async function openChat(user, convo) {
  currentChat = { user, convo };
  $("chatbox").classList.remove("hidden");
  $("chatheading").textContent = "Conversa com usuário #" + user;
  const d = await api(`/api/messages?user_id=${user}&conversation_id=${convo}`);
  if (!d.ok) return fail("chatstatus", d);
  $("messages").innerHTML = d.messages.map((m) => `<div class="msg"><small>${Number(m.fromID) === user ? "Outro usuário" : "Você"} · ${esc(m.msgID)}</small><div>${esc(m.text)}</div></div>`).join("") || '<span class="muted">Sem mensagens.</span>';
  say("chatstatus", "");
}

async function sendMessage() {
  const msg = $("message").value.trim();
  if (!currentChat || !msg) return;
  const d = await api("/api/messages", "POST", { user_id: currentChat.user, message: msg });
  if (!d.ok) return fail("chatstatus", d);
  $("message").value = "";
  openChat(currentChat.user, currentChat.convo);
}

async function convoAction(id, action, wasActive) {
  if (!confirm(action === "archive" ? "Arquivar esta conversa?" : "Reativar esta conversa?")) return;
  const d = await api("/api/conversations/action", "POST", { conversation_id: id, action });
  d.ok ? loadConversations(wasActive) : fail("convstatus", d);
}

// ---- usuários ----------------------------------------------------------------
async function searchUser() {
  const name = $("searchname").value.trim();
  if (!name) return say("userstatus", "Informe um nome de usuário.");
  const d = await api("/api/user-search?username=" + encodeURIComponent(name));
  if (d.ok) { $("targetuid").value = d.user_id; say("userstatus", "ID encontrado: " + d.user_id, true); } else fail("userstatus", d);
}
function targetId() { const id = $("targetuid").value.trim(); if (!/^\d+$/.test(id)) { say("userstatus", "Informe um ID numérico."); return null; } return id; }
async function blockUser() {
  const id = targetId(); if (!id || !confirm("Bloquear o usuário #" + id + "?")) return;
  const d = await api("/api/users/action", "POST", { user_id: id, action: "block" });
  d.ok ? say("userstatus", "Usuário bloqueado.", true) : fail("userstatus", d);
}
async function reviewUser() {
  const id = targetId(); if (!id) return;
  const stars = Number(prompt("Nota de 1 a 5", "5"));
  if (!Number.isInteger(stars) || stars < 1 || stars > 5) return;
  const d = await api("/api/users/action", "POST", { user_id: id, action: "review", stars, description: prompt("Comentário (opcional)", "") || "" });
  d.ok ? say("userstatus", "Avaliação enviada.", true) : fail("userstatus", d);
}

// ---- Conexão guiada: não envia a senha do Traderie -------------------------
function openConnect() {
  connectFocusBefore = document.activeElement;
  $("login-username").value = $("username").value || state.username || state.saved?.username || "";
  $("login-id").value = $("uid").value || state.user_id || state.saved?.user_id || "";
  $("login-slug").value = $("slug").value || "creaturesofsonaria";
  $("login-auth").value = "";
  $("login-status").textContent = "";
  $("connect-backdrop").classList.remove("hidden");
  $("connect-backdrop").setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  $("login-username").focus();
}
function closeConnect() {
  $("connect-backdrop").classList.add("hidden");
  $("connect-backdrop").setAttribute("aria-hidden", "true");
  $("login-auth").value = "";
  document.body.classList.remove("modal-open");
  connectFocusBefore?.focus?.();
}
async function loginConnect() {
  const username = $("login-username").value.trim();
  const uid = $("login-id").value.trim();
  if (!username && !uid) return say("login-status", "Informe seu nickname ou o ID numérico.");
  if (uid && !/^\d+$/.test(uid)) return say("login-status", "ID deve conter somente números.");
  const btn=$("connect-submit");
  btn.disabled=true;
  btn.textContent="Conectando…";
  try {
    const d=await api("/api/config", "POST", {
      slug:$("login-slug").value, username, user_id:uid,
      auth:$("login-auth").value, auto_relist:false,
      check_minutes:Number($("routine-minutes").value || 30)
    });
    if(!d.ok) return say("login-status", d.error||"Falha na conexão.");
    $("username").value=username; $("uid").value=uid || d.state.user_id;
    $("slug").value=$("login-slug").value;
    $("auth").value="";
    applyState(d.state);
    say("conn", d.message || "Conectado.", true);
    closeConnect();
    showToast("Conexão estabelecida. Agora carregue seus anúncios.");
    navigate("market");
    void loadListings();
  } finally {
    btn.disabled=false;
    btn.textContent="Conectar painel";
  }
}
function connectIntro(stateData) {
  if(!loginIntroSeen && !stateData.configured) {
    loginIntroSeen=true;
    openConnect();
  }
}

// ---- eventos -------------------------------------------------------------------
document.addEventListener("click", (e) => {
  const t = e.target.closest("button");
  if (!t) {
    if (e.target.closest("a, input, select, textarea, label")) return;
    const card = e.target.closest("[data-card-offers]");
    if (card) openListingOffers(Number(card.dataset.cardOffers));
    return;
  }
  if (t.disabled) return;
  const d = t.dataset;
  if (t.id === 'sound-toggle') toggleSound();
  else if (t.id === 'editor-retry') searchEditorSpecies();
  else if (t.id === 'editor-more') searchEditorSpecies(true);
  else if (t.id === 'editor-connect') openConnect();
  else if (t.dataset.editorSelect) {
    $('editor-species').value=t.dataset.editorSelect;
    setEditorSpecies(t.dataset.editorSelect);
    uiTone();
  }
  else if (t.dataset.offerChat) showOfferChat(Number(t.dataset.offerChat),t.dataset.offerChatKind||'received');
  else if (t.id === 'trade-chat-close') closeOfferChat();
  else if (t.id === 'trade-chat-start') offerChatAction('start');
  else if (t.id === 'trade-chat-send') offerChatAction('send');
  else if (t.id === 'trade-chat-reload') reloadOfferChat();
  else if (t.dataset.page) navigate(t.dataset.page);
  else if (t.id === "menu-toggle") $("sidebar").classList.toggle("open");
  else if (t.id === "modal-close" || t.id === "modal-cancel") closeGroupModal();
  else if (t.id === "modal-export") exportSelection();
  else if (t.id === "modal-delete") deleteSelected();
  else if (t.id === "btn-open-create") openEditor();
  else if (t.dataset.listCategory) {activeListCategory=t.dataset.listCategory; document.querySelectorAll("[data-list-category]").forEach(b=>{const a=b.dataset.listCategory===activeListCategory;b.classList.toggle("active",a);b.setAttribute("aria-pressed",String(a));});renderListings();}
  else if (t.dataset.offersCategory) {activeOffersCategory=t.dataset.offersCategory;document.querySelectorAll('[data-offers-category]').forEach(b=>b.classList.toggle('active',b.dataset.offersCategory===activeOffersCategory));renderOffersByCategory();}
  else if (t.dataset.editorCategory) setEditorCategory(t.dataset.editorCategory);
  else if (t.id === 'offer-close' || t.id === 'offer-cancel') closeListingOffers();
  else if (t.id === 'offer-refresh') loadListingOffers();
  else if (d.showOffers) openListingOffers(Number(d.showOffers));
  else if (d.counterOffer) document.querySelector(`[data-counter-box="${d.counterOffer}"]`)?.classList.remove('hidden');
  else if (d.counterCancel) document.querySelector(`[data-counter-box="${d.counterCancel}"]`)?.classList.add('hidden');
  else if (d.sendCounter) sendListingCounterMessage(Number(d.sendCounter));
  else if (d.declineOffer) declineListingOffer(Number(d.declineOffer));
  else if (t.id === 'btn-open-rotation') showRotationModal();
  else if (t.id === 'rotation-close' || t.id === 'rotation-cancel') closeRotationModal();
  else if (t.id === 'rotation-submit') addRotation();
  else if (t.id === 'btn-image-save') setManualImage();
  else if (t.id === 'btn-image-clear') setManualImage(true);
  else if (t.id === "editor-close" || t.id === "editor-cancel") closeEditor();
  else if (t.id === "editor-submit") submitEditor();
  else if (t.dataset.deleteOne) deleteOne(Number(t.dataset.deleteOne));
  else if (t.dataset.fillCreate) openEditor(listingsCache.find(x => x.id === Number(t.dataset.fillCreate)));
  else if (t.dataset.rotationAction) rotationAction(t.dataset.rotationId, t.dataset.rotationAction);
  else if (t.dataset.selectGroup !== undefined) openGroupModal(Number(t.dataset.selectGroup));
  else if (t.dataset.createRoutine !== undefined) {
    const g = (window.__listingGroups || [])[Number(t.dataset.createRoutine)];
    if (g) showRotationModal(g.rows[0]?.id);
  }
  else if (["btn-connect-sidebar","btn-connect-header"].includes(t.id)) openConnect();
  else if (["connect-close","connect-cancel"].includes(t.id)) closeConnect();
  else if (t.id === "connect-submit") loginConnect();
  else if (t.id === "btn-save-routine") saveRoutine();
  else if (t.id === "btn-save") saveConfig();
  else if (t.id === "btn-clear") clearAuth();
  else if (t.id === "btn-diagnose") diagnose();
  else if (t.id === "btn-status") loadStatus();
  else if (t.id === "btn-listings") loadListings();
  else if (t.id === "btn-notifs") loadNotifications();
  else if (t.id === "btn-markread") markRead();
  else if (t.id === "btn-send") sendMessage();
  else if (t.id === "btn-search") searchUser();
  else if (t.id === "btn-block") blockUser();
  else if (t.id === "btn-review") reviewUser();
  else if (d.status !== undefined) setAccountStatus(d.status);
  else if (d.relistall !== undefined) relistAll();
  else if (d.relist) relistOne(Number(d.relist));
  else if (d.offers) loadOffers(d.offers);
  else if (d.offer) offerAction(Number(d.id), d.offer);
  else if (d.convos !== undefined) loadConversations(d.convos === "1");
  else if (d.chatUser) openChat(Number(d.chatUser), Number(d.chatId));
  else if (d.convoAction) convoAction(Number(d.id), d.convoAction, d.active === "true");
});

$("listfilter").addEventListener("input", renderListings);
$("group-toggle").addEventListener("change", renderListings);
$("modal-list").addEventListener("change", (e) => {
  const input = e.target.closest("input[data-modal-index]");
  if (!input) return;
  const row = modalSelection[Number(input.dataset.modalIndex)];
  if (row) row.checked = input.checked;
  renderModal();
});
$("modal-backdrop").addEventListener("click", (e) => { if (e.target === $("modal-backdrop")) closeGroupModal(); });
$("editor-backdrop").addEventListener("click", (e) => { if (e.target === $("editor-backdrop")) closeEditor(); });
$('offer-backdrop').addEventListener('click', e => { if (e.target === $('offer-backdrop')) closeListingOffers(); });
$('trade-chat-backdrop').addEventListener('click',e=>{if(e.target===$('trade-chat-backdrop'))closeOfferChat();});

$('editor-species').addEventListener('change', e=>setEditorSpecies(e.target.value));
$('editor-item-id').addEventListener('input',()=>{if(String(editorSelected?.id)!==$('editor-item-id').value){editorSelected=null;renderEditorTraits();editorPreview();$('editor-traits-hint').textContent='Para ter opções, selecione um item retornado na pesquisa.';}});
$('editor-search').addEventListener('input',()=>{editorOpenRequest++;clearTimeout(editorSearchTimer);editorSearchTimer=setTimeout(searchEditorSpecies,300);});

$("rotation-backdrop").addEventListener("click", (e) => { if (e.target === $("rotation-backdrop")) closeRotationModal(); });
$("rotation-source").addEventListener('change', (e) => setRotationSource(e.target.value));
$("rotation-traits").addEventListener('change', (e) => {
  const input = e.target.closest('[data-trait-value]');
  if (!input) return;
  const custom = $("rotation-traits").querySelector(`[data-trait-custom="${input.dataset.traitValue}"]`);
  custom.classList.toggle('hidden', input.value !== '__custom__');
  if (input.value === '__custom__') custom.focus();
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-card-offers]")) {
    e.preventDefault(); openListingOffers(Number(e.target.dataset.cardOffers)); return;
  }
  if (e.key !== "Escape") return; if (!$('trade-chat-backdrop').classList.contains('hidden')) closeOfferChat(); else if (!$('offer-backdrop').classList.contains('hidden')) closeListingOffers(); else if (!$('rotation-backdrop').classList.contains('hidden')) closeRotationModal(); else if (!$('editor-backdrop').classList.contains('hidden')) closeEditor(); else if (!$('modal-backdrop').classList.contains('hidden')) closeGroupModal(); });
document.addEventListener("error", (e) => {
  if (!(e.target instanceof HTMLImageElement) || !e.target.matches("[data-property-icon]")) return;
  const fallback = document.createElement("span");
  fallback.className = "mutation-symbol";
  fallback.setAttribute("aria-hidden", "true");
  fallback.textContent = "✦";
  e.target.replaceWith(fallback);
}, true);
document.addEventListener("error", (e) => {
  if (!(e.target instanceof HTMLImageElement) || !e.target.matches("[data-image-fallback]")) return;
  const image = e.target;
  const fallback = document.createElement("div");
  fallback.className = `${image.className} listing-image-placeholder group-letter`;
  fallback.textContent = (image.alt || "?").charAt(0).toUpperCase();
  imageMisses += 1;
  const summary = $("image-summary");
  if (summary && imageMisses <= 3) {
    summary.title = `${imageMisses} falha(s) ao carregar arte externa; o CDN pode bloquear hotlink.`;
    if (!summary.textContent.includes('URL(s) recusada(s)')) summary.textContent += ' Algumas URL(s) recusada(s) pelo CDN serão mostradas como marcador.';
  }
  image.replaceWith(fallback);
}, true);
$("message")?.addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });

// A API é consultada periodicamente para refletir republicações externas,
// sem interromper a digitação ou fechar modais. Tempos são atualizados sem rede.
let listingSyncBusy = false;
async function syncListingsQuietly() {
  if (listingSyncBusy || document.hidden || !state.configured || currentPage !== 'market') return;
  listingSyncBusy = true;
  try {
    const result = await api('/api/listings?cached=1');
    if (!result.ok || !Array.isArray(result.listings)) { syncError=true;$("sync-status").textContent="Sem conexão · tentando novamente"; return; }
    markSynced(result.checked_at);
    const fingerprint = list => JSON.stringify(list);
    if (fingerprint(result.listings) === fingerprint(listingsCache)) return;
    listingsCache = result.listings;
    renderListings(); tickElapsed();
    const eligible = result.listings.filter(x => x.eligible).length;
    $('listing-summary').textContent = `${result.listings.length} anúncios, ${eligible} disponíveis para republicar.`;
    void resolveMissingImages();
  } finally { listingSyncBusy = false; }
}
setInterval(syncListingsQuietly, 10000);
// Atualiza apenas o estado da automação; as datas são atualizadas localmente a cada segundo.
setInterval(async () => {
  if (document.hidden) return;
  await refreshState();
}, 10000);

refreshState();

// O login permanece isolado das caixas de ofertas e rotinas.
$("connect-backdrop").addEventListener("click", (event) => {
  if (event.target === $("connect-backdrop")) closeConnect();
});
document.querySelector(".sidebar-bottom").addEventListener("click", openConnect);
document.querySelector(".sidebar-bottom").addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {event.preventDefault();openConnect();}
});
$("login-auth").addEventListener("keydown", (event) => {
  if(event.key === "Enter") loginConnect();
});

updateSoundUi();

// Keep keyboard focus inside the active dialog and restore it when it closes.
document.addEventListener('keydown',event=>{
  if(event.key!=='Tab')return;
  const backdrops=[...document.querySelectorAll('.modal-backdrop:not(.hidden)')];
  const dialog=backdrops.at(-1);
  if(!dialog)return;
  const nodes=[...dialog.querySelectorAll('button:not(:disabled),a[href],input:not([type="hidden"]),select,textarea,[tabindex="0"]')].filter(el=>el.getClientRects().length);
  const first=nodes[0],last=nodes.at(-1);
  if(!first)return;
  if(event.shiftKey&&(document.activeElement===first||!dialog.contains(document.activeElement))){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&(document.activeElement===last||!dialog.contains(document.activeElement))){event.preventDefault();first.focus();}
});
document.addEventListener('visibilitychange',()=>{if(!document.hidden){tickElapsed();void syncListingsQuietly();void refreshState();}});
