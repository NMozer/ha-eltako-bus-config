// Bus-Konfigurator für Eltako – Home Assistant Seitenpanel (ohne Build-Schritt, reines Web Component)
const D = "eltako_bus_config";

const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const hexToBytes = (h) => (h ? h.match(/../g).map((x) => parseInt(x, 16)) : null);
const bytesToHex = (b) => b.map((x) => x.toString(16).padStart(2, "0")).join("");
const spaced = (h) => (h ? h.match(/../g).join(" ").toUpperCase() : "– – –");
const idStr = (b) => b.slice(0, 4).map((x) => x.toString(16).padStart(2, "0").toUpperCase()).join("-");
const cleanHex = (s) => String(s || "").replace(/[\s\-:]/g, "").toLowerCase();
const isEmptyRow = (h) => !h || /^0+$/.test(h);
const fmtDate = (s) => (s ? new Date(s).toLocaleString("de-DE") : "–");

const STYLE = `
:host{display:block;height:100%;background:var(--primary-background-color);color:var(--primary-text-color);font-family:var(--paper-font-body1_-_font-family, Roboto, sans-serif);}
.toolbar{display:flex;align-items:center;gap:8px;height:56px;padding:0 12px;background:var(--app-header-background-color, var(--primary-color));color:var(--app-header-text-color, #fff);border-bottom:1px solid var(--divider-color);}
.toolbar h1{font-size:20px;font-weight:400;margin:0;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toolbar .tabs button{background:none;border:none;color:inherit;opacity:.75;padding:8px 12px;font-size:14px;cursor:pointer;border-bottom:2px solid transparent;height:56px}
.toolbar .tabs button.on{opacity:1;border-bottom-color:currentColor}
main{padding:16px;max-width:1400px;margin:0 auto;box-sizing:border-box}
.card{background:var(--card-background-color);border-radius:var(--ha-card-border-radius,12px);border:1px solid var(--divider-color);padding:16px;margin-bottom:16px}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.grow{flex:1}
button.b{font:inherit;font-size:14px;padding:7px 14px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer}
button.b:hover{background:var(--secondary-background-color)}
button.b.p{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:var(--primary-color)}
button.b.d{color:var(--error-color)}
button.b.sm{padding:3px 9px;font-size:13px}
button.b:disabled{opacity:.45;cursor:default}
.muted{color:var(--secondary-text-color);font-size:13px}
.layout{display:grid;grid-template-columns:320px minmax(0,1fr);gap:16px}
@media(max-width:900px){.layout{grid-template-columns:minmax(0,1fr)}}
.dev{padding:10px 12px;border-radius:8px;cursor:pointer;border:1px solid transparent;display:flex;gap:10px;align-items:center}
.dev:hover{background:var(--secondary-background-color)}
.dev.on{border-color:var(--primary-color);background:var(--secondary-background-color)}
.adr{font-family:monospace;font-size:13px;min-width:54px;text-align:center;padding:3px 6px;border-radius:6px;background:var(--secondary-background-color)}
.dev .n{font-weight:500}
.badge{font-size:11px;padding:2px 7px;border-radius:10px;background:var(--secondary-background-color);color:var(--secondary-text-color)}
.badge.w{background:rgba(255,152,0,.15);color:var(--warning-color,#e65100)}
.badge.e{background:rgba(219,68,55,.12);color:var(--error-color)}
.badge.ok{background:rgba(67,160,71,.14);color:var(--success-color,#2e7d32)}
.subtabs{display:flex;gap:4px;border-bottom:1px solid var(--divider-color);margin:12px 0}
.subtabs button{background:none;border:none;padding:8px 12px;cursor:pointer;color:var(--secondary-text-color);font:inherit;font-size:14px;border-bottom:2px solid transparent}
.subtabs button.on{color:var(--primary-color);border-bottom-color:var(--primary-color)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-weight:500;color:var(--secondary-text-color);font-size:12px;padding:6px 8px;border-bottom:1px solid var(--divider-color)}
td{padding:6px 8px;border-bottom:1px solid var(--divider-color);vertical-align:middle}
tr.pending td{background:rgba(255,152,0,.10)}
tr.empty td{color:var(--disabled-text-color, #999)}
.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
input.hex{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;width:190px;padding:4px 6px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
input.hex.bad{border-color:var(--error-color)}
input.hex.chg{border-color:var(--warning-color,#ff9800);background:rgba(255,152,0,.08)}
.group h3{font-size:15px;font-weight:500;margin:18px 0 4px}
.progress{height:4px;background:var(--divider-color);border-radius:2px;overflow:hidden;margin-top:8px}
.progress div{height:100%;background:var(--primary-color);transition:width .3s}
.pendingbar{position:sticky;bottom:12px;display:flex;gap:8px;align-items:center;padding:10px 14px;border-radius:12px;background:var(--card-background-color);border:1px solid var(--warning-color,#ff9800);box-shadow:0 4px 18px rgba(0,0,0,.15);margin-top:12px}
.err{color:var(--error-color);font-size:13px;margin-top:6px}
.note{color:var(--secondary-text-color);font-size:12px}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10;padding:16px}
.dialog{background:var(--card-background-color);border-radius:16px;padding:20px;width:min(640px,100%);max-height:90vh;overflow:auto;box-sizing:border-box}
.dialog h2{margin:0 0 12px;font-size:18px;font-weight:500}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:12px}
.field label{font-size:12px;color:var(--secondary-text-color)}
.field input,.field select{font:inherit;padding:7px 8px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
.chk{display:flex;gap:10px;flex-wrap:wrap}
.chk label{display:flex;gap:4px;align-items:center;font-size:14px}
.empty-state{padding:32px;text-align:center;color:var(--secondary-text-color)}
.learn{display:grid;grid-template-columns:380px minmax(0,1fr);gap:16px}
@media(max-width:1000px){.learn{grid-template-columns:minmax(0,1fr)}}
.scard{border:1px solid var(--divider-color);border-radius:10px;padding:8px 10px;margin-bottom:8px;background:var(--card-background-color)}
.scard.hot{border-color:var(--primary-color);box-shadow:0 0 0 2px rgba(3,169,244,.25)}
.scard input.name{font:inherit;font-weight:500;border:1px solid transparent;border-radius:6px;padding:2px 4px;width:100%;box-sizing:border-box;background:transparent;color:var(--primary-text-color)}
.scard input.name:hover,.scard input.name:focus{border-color:var(--divider-color)}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;padding:3px 9px;border-radius:14px;border:1px dashed var(--primary-color);color:var(--primary-color);cursor:grab;user-select:none;margin:4px 4px 0 0;background:var(--card-background-color)}
.chip:active{cursor:grabbing}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px;margin-top:8px}
.tile{border:1px dashed var(--divider-color);border-radius:10px;padding:8px;min-height:72px;transition:background .15s,border-color .15s}
.tile.over{border-color:var(--primary-color);background:rgba(3,169,244,.08)}
.tile .t{font-weight:500;font-size:13px;margin-bottom:4px}
.entry{display:flex;gap:6px;align-items:center;font-size:12.5px;padding:4px 2px;border-top:1px solid var(--divider-color)}
.entry .nm{font-weight:500}
.entry.removed .nm,.entry.removed .muted{text-decoration:line-through;opacity:.6}
.entry.pending{background:rgba(255,152,0,.10)}
.entry .x{margin-left:auto;cursor:pointer;color:var(--error-color);border:none;background:none;font-size:14px}
.tile select{width:100%;margin-top:6px;font:inherit;font-size:12.5px;padding:4px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-size:14px}
`;

class EltakoPctPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.s = {
      view: "devices", info: null, devices: [], sel: null, sub: "table", showEmpty: false,
      pending: {}, progress: null, busy: false, error: null, backups: [], dialog: null, toast: null,
      senders: [], monitorSecs: 120, monitorLock: false, hideBus: true, flash: {}, monitoring: false,
    };
    this._hass = null;
    this._unsub = null;
    this.shadowRoot.addEventListener("click", (e) => this._onClick(e));
    this.shadowRoot.addEventListener("change", (e) => this._onChange(e));
    this.shadowRoot.addEventListener("input", (e) => this._onInput(e));
    this.shadowRoot.addEventListener("dragstart", (e) => {
      const el = e.target.closest?.("[data-drag]"); if (!el) return;
      e.dataTransfer.setData("text/plain", el.dataset.drag); e.dataTransfer.effectAllowed = "copy";
    });
    this.shadowRoot.addEventListener("dragover", (e) => {
      const t = e.target.closest?.("[data-drop]"); if (!t) return;
      e.preventDefault(); e.dataTransfer.dropEffect = "copy"; t.classList.add("over");
    });
    this.shadowRoot.addEventListener("dragleave", (e) => { e.target.closest?.("[data-drop]")?.classList.remove("over"); });
    this.shadowRoot.addEventListener("drop", (e) => {
      const t = e.target.closest?.("[data-drop]"); if (!t) return;
      e.preventDefault(); t.classList.remove("over");
      const [sid, key] = (e.dataTransfer.getData("text/plain") || "").split("|");
      const [addr, bit] = t.dataset.drop.split("|").map(Number);
      if (sid) this._assign(addr, bit, sid, +key);
    });
  }

  set hass(h) {
    const first = !this._hass;
    this._hass = h;
    if (this._menu) { this._menu.hass = h; }
    if (first) this._init();
  }
  set narrow(n) { this._narrow = n; if (this._menu) this._menu.narrow = n; }
  set panel(_p) {}

  disconnectedCallback() { if (this._unsub) { this._unsub.then((u) => u()); this._unsub = null; } }
  connectedCallback() { if (this._hass && !this._unsub) this._subscribe(); }

  async _init() {
    this._subscribe();
    try {
      const [info, dev, snd] = await Promise.all([this._ws("info"), this._ws("devices"), this._ws("senders/list")]);
      this.s.info = info; this.s.devices = dev.devices; this.s.senders = snd.senders;
      if (!this.s.sel && dev.devices.length) this.s.sel = (dev.devices.find((d) => !d.is_fam) || dev.devices[0]).address;
    } catch (e) { this.s.error = this._msg(e); }
    this.render();
  }

  _subscribe() {
    if (!this._hass) return;
    this._unsub = this._hass.connection.subscribeEvents((ev) => {
      const d = ev.data;
      if (d.state === "start") this.s.progress = { progress: 0, message: "Starte…", op: d.operation };
      else if (d.state === "done") this.s.progress = null;
      else if (d.state === "telegram") {
        if (this.s.dialog?.listen) {
          const l = this.s.dialog.listen; const i = l.found.findIndex((x) => x.sender === d.telegram.sender);
          if (i >= 0) l.found[i] = d.telegram; else l.found.push(d.telegram);
        }
        if (d.sender) {
          const i = this.s.senders.findIndex((x) => x.id === d.sender.id);
          if (i >= 0) this.s.senders[i] = d.sender; else this.s.senders.unshift(d.sender);
          this.s.flash[d.sender.id] = Date.now();
          clearTimeout(this._flashT); this._flashT = setTimeout(() => this._renderSoon(), 8200);
        }
      } else if (d.progress !== undefined || d.message) {
        this.s.progress = { ...(this.s.progress || {}), progress: d.progress ?? this.s.progress?.progress, message: d.message || this.s.progress?.message };
      }
      this._renderSoon();
    }, "eltako_bus_config_progress");
  }

  _renderSoon() { if (this._raf) return; this._raf = requestAnimationFrame(() => { this._raf = null; this.render(); }); }
  _ws(cmd, data = {}) { return this._hass.callWS({ type: `${D}/${cmd}`, ...data }); }
  _msg(e) { return e?.message || e?.error?.message || String(e); }
  _toast(text, kind = "ok") { this.s.toast = { text, kind }; clearTimeout(this._tt); this._tt = setTimeout(() => { this.s.toast = null; this.render(); }, 6000); }

  async _run(fn, okText) {
    if (this.s.busy) return;
    this.s.busy = true; this.s.error = null; this.render();
    try { const r = await fn(); if (okText) this._toast(typeof okText === "function" ? okText(r) : okText); return r; }
    catch (e) { this.s.error = this._msg(e); }
    finally { this.s.busy = false; this.s.progress = null; this.render(); }
  }

  get dev() { return this.s.devices.find((d) => d.address === this.s.sel); }
  get kf() { return this.s.info?.key_functions || {}; }
  pendingFor(a) { return this.s.pending[a] || {}; }
  rowValue(d, r) { const p = this.pendingFor(d.address)[r]; return p !== undefined ? p : d.memory[r]; }
  setPending(a, r, hex) {
    const d = this.s.devices.find((x) => x.address === a);
    const p = { ...(this.s.pending[a] || {}) };
    if (d && d.memory[r] === hex) delete p[r]; else p[r] = hex;
    this.s.pending[a] = p;
    if (!Object.keys(p).length) delete this.s.pending[a];
  }

  // ------------------------------------------------------------------ render
  render() {
    const s = this.s;
    const root = this.shadowRoot;
    const scrollY = root.querySelector("main")?.scrollTop;
    const act = root.activeElement; const keep = act && act.tagName === "INPUT" && act.dataset.a
      ? { a: act.dataset.a, v: act.dataset.v, val: act.value, pos: act.selectionStart } : null;
    root.innerHTML = `<style>${STYLE}</style>
      <div class="toolbar"><span id="menu"></span><h1>Bus-Konfigurator für Eltako</h1>
        <div class="tabs"><button data-a="view" data-v="devices" class="${s.view === "devices" ? "on" : ""}">Geräte</button>
        <button data-a="view" data-v="learn" class="${s.view === "learn" ? "on" : ""}">Einlernen</button>
        <button data-a="view" data-v="backups" class="${s.view === "backups" ? "on" : ""}">Sicherungen</button>
        <button data-a="view" data-v="info" class="${s.view === "info" ? "on" : ""}">Verbindung</button></div></div>
      <main>${this._status()}${s.view === "devices" ? this._devicesView() : s.view === "learn" ? this._learnView() : s.view === "backups" ? this._backupsView() : this._infoView()}</main>
      ${s.dialog ? this._dialog() : ""}
      ${s.toast ? `<div class="pendingbar" style="position:fixed;left:50%;transform:translateX(-50%);bottom:16px;border-color:${s.toast.kind === "ok" ? "var(--success-color,#43a047)" : "var(--error-color)"}">${esc(s.toast.text)}</div>` : ""}`;
    if (!this._menu) { this._menu = document.createElement("ha-menu-button"); }
    this._menu.hass = this._hass; this._menu.narrow = this._narrow;
    root.getElementById("menu").appendChild(this._menu);
    if (scrollY) root.querySelector("main").scrollTop = scrollY;
    if (keep) {
      const el = root.querySelector(`input[data-a="${keep.a}"]${keep.v !== undefined ? `[data-v="${keep.v}"]` : ""}`);
      if (el) { el.value = keep.val; el.focus(); try { el.setSelectionRange(keep.pos, keep.pos); } catch (_e) { /* number inputs */ } }
    }
  }

  _status() {
    const s = this.s; let h = "";
    if (s.monitoring || s.progress?.op === "listen") {
      return h + `<div class="card" style="border-color:var(--primary-color)"><div class="row"><b>Lauschen aktiv</b><span class="muted grow">${esc(s.progress?.message || "Warte auf Telegramme…")}</span>
        <button class="b" data-a="monitor-stop">Stoppen</button></div>
        <div class="note" style="margin-top:6px">Der Bus bleibt frei – Aktoren reagieren dabei ganz normal auf die Taster. Erkannte Sender erscheinen unter „Einlernen“.</div></div>`
        + (s.error ? `<div class="card" style="border-color:var(--error-color)"><span style="color:var(--error-color)">${esc(s.error)}</span></div>` : "");
    }
    if (s.progress || s.busy) {
      const pct = Math.round((s.progress?.progress || 0) * 100);
      h += `<div class="card"><div class="row"><b>Bus-Zugriff läuft</b><span class="muted grow">${esc(s.progress?.message || "Bitte warten…")}</span><span class="muted">${pct}%</span></div>
        <div class="progress"><div style="width:${pct}%"></div></div>
        <div class="note" style="margin-top:6px">Während des Zugriffs ist der Bus gesperrt – Aktoren reagieren kurz nicht auf Funktelegramme.</div></div>`;
    }
    if (s.error) h += `<div class="card" style="border-color:var(--error-color)"><div class="row"><span class="grow" style="color:var(--error-color)">${esc(s.error)}</span><button class="b sm" data-a="clear-error">Schließen</button></div></div>`;
    return h;
  }

  _devicesView() {
    const s = this.s; const st = s.info?.state || {};
    const list = s.devices.map((d) => {
      const last = d.address + Math.max(1, d.size) - 1;
      const adr = d.is_fam ? "FAM" : d.size > 1 ? `${d.address}–${last}` : d.address;
      const unread = d.memory.some((r) => r === null) && !d.is_fam;
      const pend = Object.keys(this.pendingFor(d.address)).length;
      return `<div class="dev ${d.address === s.sel ? "on" : ""}" data-a="sel" data-v="${d.address}">
        <span class="adr">${adr}</span>
        <div class="grow"><div class="n">${esc(d.type.name)}</div><div class="muted">${esc(d.type.description)} · V${esc(d.version)}</div></div>
        ${pend ? `<span class="badge w">${pend} geändert</span>` : unread ? `<span class="badge">nicht gelesen</span>` : ""}</div>`;
    }).join("");
    const left = `<div class="card" style="padding:12px">
      <div class="row" style="margin-bottom:8px"><button class="b p" data-a="scan" ${s.busy ? "disabled" : ""}>Bus scannen</button>
      <button class="b" data-a="scan-list" ${s.busy ? "disabled" : ""} title="Nur Geräteliste, ohne Speicher">Nur Liste</button></div>
      <div class="muted" style="margin-bottom:8px">${st.last_scan ? `Letzter Scan: ${fmtDate(st.last_scan)}` : "Noch kein Scan"}${s.info?.state?.base_id ? ` · Basis-ID ${esc(s.info.state.base_id)}` : ""}</div>
      ${list || `<div class="empty-state">Starte einen Bus-Scan, um die Geräte der Baureihe 14 einzulesen.</div>`}</div>`;
    return `<div class="layout">${left}<div>${this.dev ? this._detail(this.dev) : `<div class="card empty-state">Wähle links ein Gerät aus.</div>`}</div></div>`;
  }

  _detail(d) {
    const s = this.s; const t = d.type;
    const unread = d.memory.some((r) => r === null);
    const hasTable = t.groups.length > 0;
    if (!hasTable && s.sub === "table") s.sub = "raw";
    const tabs = [hasTable && ["table", "ID-Tabelle"], ["settings", "Einstellungen"], ["raw", "Rohspeicher"]].filter(Boolean);
    let body;
    if (unread) body = `<div class="empty-state">Der Speicher dieses Geräts wurde noch nicht gelesen.<br><br><button class="b p" data-a="read" ${s.busy ? "disabled" : ""}>Speicher auslesen</button></div>`;
    else if (s.sub === "table") body = this._tableView(d);
    else if (s.sub === "settings") body = this._rowsView(d, t.settings_rows[0], t.settings_rows[1], "Die Einstellungszeilen sind gerätespezifisch. Bekannte Bedeutungen stehen daneben – alles andere bitte nur mit Vorlage aus einer PCT14-Sicherung ändern.");
    else body = this._rowsView(d, 0, d.memory_size, "Kompletter Gerätespeicher, 8 Byte je Zeile.");
    const pend = this.pendingFor(d.address); const n = Object.keys(pend).length;
    return `<div class="card">
      <div class="row"><div class="grow"><div style="font-size:20px">${esc(t.name)} <span class="muted">Adresse ${d.address}${d.size > 1 ? `–${d.address + d.size - 1}` : ""}</span></div>
      <div class="muted">${esc(t.description)} · Firmware ${esc(d.version)} · Modell ${esc(spaced(d.model))} · ${d.memory_size} Zeilen${d.read_at ? ` · gelesen ${fmtDate(d.read_at)}` : ""}</div></div>
      ${!d.is_fam ? `<button class="b" data-a="identify" ${s.busy ? "disabled" : ""}>Blinken</button>` : ""}
      <button class="b" data-a="read" ${s.busy ? "disabled" : ""}>Neu auslesen</button></div>
      ${t.key === "UNKNOWN" ? `<div class="note" style="margin-top:8px">Dieser Gerätetyp ist noch nicht im Katalog – nur der Rohspeicher ist verfügbar.</div>` : ""}
      <div class="subtabs">${tabs.map(([k, l]) => `<button data-a="sub" data-v="${k}" class="${s.sub === k ? "on" : ""}">${l}</button>`).join("")}</div>
      ${body}
      ${n ? `<div class="pendingbar"><b>${n} ungespeicherte Änderung${n > 1 ? "en" : ""}</b><span class="grow"></span>
        <button class="b" data-a="discard">Verwerfen</button><button class="b p" data-a="confirm-write" ${s.busy ? "disabled" : ""}>Auf Gerät schreiben</button></div>` : ""}
    </div>`;
  }

  _senderHint(id) {
    const base = this.s.info?.state?.base_id;
    const v = parseInt(id.replace(/-/g, ""), 16);
    if (id.startsWith("00-00-00-")) return `Bus-Gerät ${parseInt(id.slice(9), 16)}`;
    if (id.startsWith("00-00-B0-")) return "Bus-Sender (z. B. FGW14-USB / Home Assistant)";
    if (base) {
      const b = parseInt(base.replace(/-/g, ""), 16);
      if (v >= b && v < b + 128) return `FAM14-Basis-ID + ${v - b}`;
    }
    if (v >= 0xff800000) {
      const gb = (v - (v % 128)) >>> 0;
      return `Gateway-Sender: Basis ${gb.toString(16).toUpperCase().match(/../g).join("-")} + ${v % 128}`;
    }
    return "";
  }

  _channels(d, ch) {
    const m = d.type.channel_mode;
    if (m === "value") return `Geschw. ${ch}`;
    if (m === "dali_group") return ch >= 16 ? "Broadcast" : `DALI-Gruppe ${ch}`;
    if (d.size <= 1) return ch ? "Kanal 1" : "–";
    const on = []; for (let i = 0; i < 8; i++) if (ch & (1 << i)) on.push(i + 1);
    return on.length ? `Kanal ${on.join(", ")}` : "keiner";
  }

  _tableView(d) {
    const s = this.s; const pend = this.pendingFor(d.address);
    let h = `<div class="row" style="justify-content:flex-end"><label class="muted"><input type="checkbox" data-a="show-empty" ${s.showEmpty ? "checked" : ""}> Leere Zeilen anzeigen</label></div>`;
    for (const g of d.type.groups) {
      const rows = [];
      for (let r = g.start; r < g.end; r++) {
        const hex = this.rowValue(d, r); const empty = isEmptyRow(hex);
        if (empty && !s.showEmpty && pend[r] === undefined) continue;
        const b = hexToBytes(hex);
        const id = idStr(b);
        const fn = b[5]; const fnName = this.kf[fn] || `Funktion ${fn}`;
        const keyL = this.s.info?.key_labels?.[b[4]] || `Taste ${b[4]}`;
        rows.push(`<tr class="${pend[r] !== undefined ? "pending" : ""} ${empty ? "empty" : ""}">
          <td class="mono">${r}</td>
          <td class="mono">${empty ? "leer" : `${id}<div class="note">${esc(this._senderHint(id))}</div>`}</td>
          <td style="white-space:nowrap">${empty ? "" : esc(keyL)}</td>
          <td>${empty ? "" : `${esc(fnName)} <span class="note">(${fn})</span>`}</td>
          <td style="white-space:nowrap">${empty ? "" : esc(this._channels(d, b[6]))}</td>
          <td class="mono">${empty ? "" : b[7]}</td>
          <td style="white-space:nowrap;text-align:right"><button class="b sm" data-a="edit" data-v="${r}">${empty ? "Belegen" : "Bearbeiten"}</button>
          ${!empty ? `<button class="b sm d" data-a="clear-row" data-v="${r}" title="Eintrag löschen">✕</button>` : ""}</td></tr>`);
      }
      const used = Array.from({ length: g.end - g.start }, (_, i) => this.rowValue(d, g.start + i)).filter((x) => !isEmptyRow(x)).length;
      h += `<div class="group"><div class="row"><h3 class="grow">${esc(g.label)}</h3><span class="muted">${used}/${g.end - g.start} belegt · Zeilen ${g.start}–${g.end - 1}</span>
        <button class="b sm" data-a="add" data-v="${g.number}">+ Eintrag</button></div>
        ${rows.length ? `<table><thead><tr><th>Zeile</th><th>Sender-ID</th><th>Taste</th><th>Funktion</th><th>Kanäle</th><th>Wert</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table>` : `<div class="muted" style="padding:6px 0">Keine Einträge.</div>`}</div>`;
    }
    return h;
  }

  _rowsView(d, from, to, hint) {
    const pend = this.pendingFor(d.address); const notes = d.type.row_notes || {};
    const groupStart = Object.fromEntries(d.type.groups.map((g) => [g.start, g.label]));
    let h = `<div class="note" style="margin-bottom:8px">${esc(hint)} Änderungen werden erst mit „Auf Gerät schreiben“ übertragen.</div><table><thead><tr><th style="width:50px">Zeile</th><th style="width:210px">Inhalt (hex)</th><th>Bedeutung</th></tr></thead><tbody>`;
    for (let r = from; r < to; r++) {
      const v = this.rowValue(d, r);
      const note = notes[r] || (groupStart[r] ? `Beginn: ${groupStart[r]}` : "");
      h += `<tr class="${pend[r] !== undefined ? "pending" : ""}"><td class="mono">${r}</td>
        <td><input class="hex ${pend[r] !== undefined ? "chg" : ""}" data-a="hex" data-v="${r}" value="${esc(spaced(v))}" spellcheck="false"></td>
        <td class="note">${esc(note)}</td></tr>`;
    }
    return h + "</tbody></table>";
  }

  // ------------------------------------------------------------ Lernmodus
  kindLabel(k) {
    return { rocker: "Wandtaster", window_handle: "Fenstergriff", contact: "Kontakt (1BS)", sensor: "Sensor (4BS)",
      bus_sender: "Bus-Sender / Home Assistant", bus_device: "Bus-Aktor (Rückmeldung)", unknown: "nur im Gerätespeicher", rps: "Funktaster (RPS)" }[k] || k;
  }
  sender(sid) { return this.s.senders.find((x) => x.id === sid); }
  // Telegrams that are not from a radio switch: status feedback of bus actuators.
  // The FAM14 transmits actuator feedback with its base ID + bus address; IDs 00-00-xx-xx are bus-internal.
  feedbackInfo(x) {
    if (x.kind === "bus_device") return `Rückmeldung Bus-Aktor ${parseInt(x.id.slice(9), 16)}`;
    const base = this.s.info?.state?.base_id;
    if (base) {
      const b = parseInt(base.replace(/-/g, ""), 16), v = parseInt(x.id.replace(/-/g, ""), 16);
      if (v > b && v < b + 128) return `Rückmeldung über FAM14 (Bus-Adresse ${v - b})`;
    }
    if (x.id.startsWith("00-00-") && !x.id.startsWith("00-00-B0-")) return "Bus-interner Sender";
    return null;
  }
  senderName(sid) { const x = this.sender(sid); return x?.name || sid; }
  devLabel(d) { return `${d.type.name} Adr. ${d.address}${d.size > 1 ? `–${d.address + d.size - 1}` : ""}`; }
  chName(d, bit) { return d.type.channel_mode === "bitmask" && d.size > 1 ? `Kanal ${bit + 1} (Adr. ${d.address + bit})` : "Gerät"; }
  keyShort(k) { return { 5: "links", 6: "rechts", 1: "LO", 2: "LU", 3: "RO", 4: "RU" }[k] || ""; }
  keyLabel(k) { return { 5: "Wippe links", 6: "Wippe rechts", 1: "Taste links oben", 2: "Taste links unten", 3: "Taste rechts oben", 4: "Taste rechts unten" }[k] || "Sender"; }
  typeInfo(t) { return this.s.info?.sender_types?.[t]; }
  typeLabel(x) { return this.typeInfo(x.type)?.label; }
  sourceLabel(src) { return { eep: "aus Lerntelegramm", memory: "aus Gerätespeicher", pattern: "aus Telegramm erkannt", manual: "von dir gewählt" }[src] || ""; }
  fnGroupFor(d, fn) {
    const nr = d.type.group_by_function?.[fn];
    const groups = d.type.groups;
    return groups.find((g) => g.number === nr) || groups[groups.length - 1];
  }
  freeRow(d, g, exclude = null) {
    for (let r = g.start; r < g.end; r++) if (r !== exclude && isEmptyRow(this.rowValue(d, r))) return r;
    return null;
  }

  entriesOf(d) {
    const out = [];
    for (const g of d.type.groups) for (let r = g.start; r < g.end; r++) {
      const pend = this.pendingFor(d.address)[r] !== undefined;
      let hex = this.rowValue(d, r); let removed = false;
      if (isEmptyRow(hex)) { if (!pend || isEmptyRow(d.memory[r])) continue; hex = d.memory[r]; removed = true; }
      const b = hexToBytes(hex); out.push({ row: r, id: idStr(b), key: b[4], fn: b[5], ch: b[6], val: b[7], group: g.number,
        pending: pend, removed });
    }
    return out;
  }
  usage(sid) {
    const res = [];
    for (const d of this.s.devices) if (!d.is_fam && !d.memory.some((r) => r === null))
      for (const e of this.entriesOf(d)) if (e.id === sid && !e.removed) res.push({ d, e });
    return res;
  }
  suggestFn(d, snd, key) {
    const sg = d.type.suggest || {};
    const fb = d.type.functions_by_sender || {};
    let t = snd?.type;
    if (!t && (snd?.id || "").startsWith("00-00-B0-")) t = "controller";
    if (!t && [1, 2, 3, 4, 5, 6].includes(key)) t = "rocker_switch";
    const list = fb[t];
    if (list?.length) {
      if ([1, 2, 3, 4].includes(key)) return list.find((f) => f !== 2 && f !== 3) ?? list[0];
      return list[0];
    }
    if (snd?.kind === "bus_sender" || (snd?.id || "").startsWith("00-00-B0-")) return sg.bus_sender ?? 51;
    if (snd?.eep && this.s.info?.eep_functions?.[snd.eep] !== undefined) return this.s.info.eep_functions[snd.eep];
    if (key === 5 || key === 6 || snd?.kind === "rocker") return sg.rocker ?? 2;
    return sg.rocker ?? 1;
  }

  _assign(addr, bit, sid, key) {
    const d = this.s.devices.find((x) => x.address === addr); if (!d) return;
    if (d.memory.some((r) => r === null)) { this.s.error = `${this.devLabel(d)}: Speicher zuerst auslesen.`; this.render(); return; }
    const snd = this.sender(sid);
    const useBit = d.type.channel_mode === "bitmask" && d.size > 1 && bit >= 0;
    // same sender + key already present? -> just add the channel to that row (like PCT14)
    const existing = this.entriesOf(d).find((e) => e.id === sid && e.key === key && !e.removed);
    if (existing) {
      const ch = useBit ? existing.ch | (1 << bit) : existing.ch;
      this._openEdit(existing.row, addr, { id: sid, key, fn: existing.fn, ch, val: existing.val }, true);
      return;
    }
    const fn = this.suggestFn(d, snd, key);
    const g = this.fnGroupFor(d, fn);
    const row = this.freeRow(d, g);
    if (row === null) { this.s.error = `${g.label} von ${this.devLabel(d)} ist voll.`; this.render(); return; }
    const ch = useBit ? 1 << bit : d.type.channel_mode === "dali_group" ? 16 : 1;
    this._openEdit(row, addr, { id: sid, key, fn, ch, val: 0 }, true);
  }

  _unassign(addr, row, bit) {
    const d = this.s.devices.find((x) => x.address === addr); const b = hexToBytes(this.rowValue(d, row));
    const bits = b[6].toString(2).split("").filter((x) => x === "1").length;
    if (d.type.channel_mode === "bitmask" && d.size > 1 && bit >= 0 && bits > 1) { b[6] &= ~(1 << bit); this.setPending(addr, row, bytesToHex(b)); }
    else this.setPending(addr, row, "0000000000000000");
    this.render();
  }

  _senderOptions(withKeys) {
    const list = this.s.senders.filter((x) => !x.hidden && !this.feedbackInfo(x));
    const opts = [];
    for (const x of list) {
      const tl = this.typeLabel(x);
      const nm = (x.name ? `${x.name} (${x.id})` : x.id) + (tl ? ` · ${tl}` : "");
      if (withKeys && (x.type === "rocker_switch" || x.keys?.length || x.buttons?.length)) {
        const rockers = x.keys?.length ? x.keys : [5, 6];
        const buttons = [...new Set([...rockers.flatMap((k) => (k === 5 ? [1, 2] : [3, 4])), ...(x.buttons || [])])].sort();
        for (const k of [...rockers, ...buttons]) opts.push([`${x.id}|${k}`, `${nm} – ${this.keyLabel(k)}`]);
      } else opts.push([`${x.id}|${withKeys ? 0 : ""}`, nm]);
    }
    return opts;
  }

  _learnView() {
    const s = this.s; const now = Date.now();
    const list = s.senders.filter((x) => !(s.hideBus && this.feedbackInfo(x) && !this.usage(x.id).length))
      .filter((x) => !s.typeFilter || (s.typeFilter === "__none" ? !x.type : x.type === s.typeFilter));
    const hiddenCount = s.senders.length - list.length;
    const cards = list.map((x) => {
      const hot = now - (s.flash[x.id] || 0) < 8000;
      const used = this.usage(x.id);
      const isRocker = x.type === "rocker_switch" || x.keys?.length || x.buttons?.length;
      const mode = (s.cardMode || {})[x.id] || "rocker";
      let keys;
      if (!isRocker) keys = [0];
      else if (mode === "buttons") {
        const rockers = x.keys?.length ? x.keys : [5, 6];
        keys = [...new Set([...rockers.flatMap((k) => (k === 5 ? [1, 2] : [3, 4])), ...(x.buttons || [])])].sort();
      } else keys = x.keys?.length ? x.keys : [5, 6];
      const typeSel = `<select data-a="sender-type" data-v="${esc(x.id)}" style="font:inherit;font-size:12px;padding:2px 4px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);max-width:100%">
        <option value="">Typ: ${esc(this.typeLabel(x) || "unbekannt")}${x.type_source ? ` (${esc(this.sourceLabel(x.type_source))})` : ""}</option>
        ${Object.entries(s.info?.sender_types || {}).filter(([k]) => k !== "unknown").map(([k, v]) => `<option value="${k}">→ ${esc(v.label)}${v.examples ? ` (${esc(v.examples)})` : ""}</option>`).join("")}
        ${x.type_source === "manual" ? `<option value="__auto">↺ wieder automatisch erkennen</option>` : ""}</select>`;
      const lp = x.last_press && hot ? ` · gerade: Wippe ${this.keyShort(x.last_press.key)} ${x.last_press.direction}` : "";
      return `<div class="scard ${hot ? "hot" : ""}">
        <div class="row" style="flex-wrap:nowrap"><input class="name" data-a="sender-name" data-v="${esc(x.id)}" value="${esc(x.name || "")}" placeholder="Namen vergeben…">
          <button class="b sm d" data-a="sender-del" data-v="${esc(x.id)}" title="Aus der Liste entfernen">✕</button></div>
        <div class="muted"><span class="mono">${esc(x.id)}</span> · ${esc(this.feedbackInfo(x) || this.typeLabel(x) || this.kindLabel(x.kind))}${x.eep ? ` · ${esc(x.eep)}` : ""}${(x.presses ?? x.count) ? ` · ${x.presses ?? x.count}× ${x.kind === "rocker" ? "gedrückt" : "empfangen"}` : x.from_memory ? " · noch nicht gehört" : ""}${lp}</div>
        <div style="margin-top:4px">${typeSel}</div>
        <div>${keys.map((k) => `<span class="chip" draggable="true" data-drag="${esc(x.id)}|${k}" title="${esc(this.keyLabel(k))}">⠿ ${k ? (k >= 5 ? `Wippe ${this.keyShort(k)}` : this.keyLabel(k).replace("Taste ", "")) : "Sender"}</span>`).join("")}
        ${isRocker ? `<button class="b sm" style="margin-left:4px" data-a="card-mode" data-v="${esc(x.id)}">${mode === "buttons" ? "als Wippen" : "als Einzeltasten"}</button>` : ""}</div>
        ${used.length ? `<div class="note" style="margin-top:4px">Eingelernt: ${used.map(({ d, e }) => `${esc(d.type.name)} Adr. ${d.address}${d.type.channel_mode === "bitmask" && d.size > 1 ? ` K${[...Array(d.size).keys()].filter((i) => e.ch & (1 << i)).map((i) => i + 1).join("+")}` : ""}${this.keyShort(e.key) ? ` (${this.keyShort(e.key)})` : ""}`).join(", ")}</div>` : ""}
      </div>`;
    }).join("");
    const devs = s.devices.filter((d) => !d.is_fam && d.type.groups.length);
    const opts = this._senderOptions(true);
    const tiles = devs.map((d) => {
      const unread = d.memory.some((r) => r === null);
      const chans = d.type.channel_mode === "bitmask" && d.size > 1 ? [...Array(Math.min(8, d.size)).keys()] : [-1];
      const entries = unread ? [] : this.entriesOf(d);
      const tile = (bit) => {
        const mine = entries.filter((e) => bit < 0 || (e.ch & (1 << bit)));
        return `<div class="tile" data-drop="${d.address}|${bit}"><div class="t">${esc(this.chName(d, bit))}</div>
          ${mine.map((e) => `<div class="entry ${e.pending ? "pending" : ""} ${e.removed ? "removed" : ""}" title="Zeile ${e.row}: Funktion ${e.fn} – ${esc(this.kf[e.fn] || "")}">
            <div><div class="nm">${esc(this.senderName(e.id))}${this.keyShort(e.key) ? ` <span class="muted" style="font-weight:400">· ${esc(this.keyLabel(e.key))}</span>` : ""}</div>
            <div class="muted">${esc(this.kf[e.fn] || `Funktion ${e.fn}`)}</div></div>
            ${e.pending ? `<button class="x" style="color:var(--secondary-text-color)" data-a="revert" data-v="${d.address}|${e.row}" title="Änderung zurücknehmen">↺</button>`
              : `<button class="x" data-a="unassign" data-v="${d.address}|${e.row}|${bit}" title="Zuordnung entfernen">✕</button>`}</div>`).join("")}
          <select data-a="assign" data-v="${d.address}|${bit}"><option value="">+ Sender zuordnen…</option>${opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select>
        </div>`;
      };
      const n = Object.keys(this.pendingFor(d.address)).length;
      return `<div class="card" style="padding:12px"><div class="row"><b class="grow">${esc(this.devLabel(d))}</b><span class="muted">${esc(d.type.description)}</span>${n ? `<span class="badge w">${n} geändert</span>` : ""}</div>
        ${unread ? `<div class="muted" style="margin-top:6px">Speicher noch nicht gelesen – zuerst unter „Geräte“ „Bus scannen“.</div>` : `<div class="tiles">${chans.map(tile).join("")}</div>`}</div>`;
    }).join("");
    const pendDevs = Object.keys(s.pending).length;
    const pendRows = Object.values(s.pending).reduce((a, p) => a + Object.keys(p).length, 0);
    return `<div class="card"><div class="row">
        <div class="grow"><b>Sender erkennen</b><div class="muted">Lauschen starten, dann nacheinander die Taster betätigen. Erkannte Sender bleiben gespeichert und können benannt werden.</div></div>
        <select data-a="monitor-secs" style="font:inherit;padding:6px;border-radius:8px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)">
          ${[[60, "1 Minute"], [120, "2 Minuten"], [300, "5 Minuten"], [900, "15 Minuten"]].map(([v, l]) => `<option value="${v}" ${s.monitorSecs === v ? "selected" : ""}>${l}</option>`).join("")}</select>
        ${s.monitoring ? `<button class="b" data-a="monitor-stop">Stoppen</button>` : `<button class="b p" data-a="monitor-start" ${s.busy ? "disabled" : ""}>Lauschen starten</button>`}</div>
        <div class="row" style="margin-top:8px;gap:16px">
          <label class="muted"><input type="checkbox" data-a="hide-bus" ${s.hideBus ? "checked" : ""}> Rückmeldungen der Aktoren ausblenden${s.hideBus && hiddenCount ? ` (${hiddenCount} ausgeblendet)` : ""}</label>
          <span class="grow"></span><button class="b sm" data-a="senders-clear">Unbenannte entfernen</button></div></div>
      <div class="learn"><div>
        <div class="row" style="margin:0 0 6px"><span class="muted grow">${list.length} Sender · Chips auf einen Kanal ziehen</span>
          <select data-a="type-filter" style="font:inherit;font-size:12.5px;padding:3px 6px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color)">
            <option value="">Alle Typen</option>${Object.entries(s.info?.sender_types || {}).filter(([k]) => k !== "unknown").map(([k, v]) => `<option value="${k}" ${s.typeFilter === k ? "selected" : ""}>${esc(v.label)}</option>`).join("")}
            <option value="__none" ${s.typeFilter === "__none" ? "selected" : ""}>Ohne Typ</option></select></div>
        ${cards || `<div class="card empty-state">Noch keine Sender. Starte „Lauschen“ und drücke deine Taster.</div>`}</div>
        <div>${tiles || `<div class="card empty-state">Keine Aktoren mit ID-Tabelle bekannt. Zuerst unter „Geräte“ den Bus scannen.</div>`}
        ${pendDevs ? `<div class="pendingbar"><b>${pendRows} Änderung${pendRows > 1 ? "en" : ""} an ${pendDevs} Gerät${pendDevs > 1 ? "en" : ""}</b><span class="grow"></span>
          <button class="b" data-a="discard-all">Alle verwerfen</button><button class="b p" data-a="confirm-all" ${s.busy ? "disabled" : ""}>Auf Geräte schreiben</button></div>` : ""}</div></div>`;
  }

  _confirmAllDialog() {
    const parts = Object.entries(this.s.pending).map(([a, p]) => {
      const d = this.s.devices.find((x) => x.address === +a);
      const rows = Object.keys(p).map(Number).sort((x, y) => x - y).map((r) => {
        const nb = hexToBytes(p[r]); const desc = isEmptyRow(p[r]) ? "Eintrag löschen" : `${esc(this.senderName(idStr(nb)))} · ${esc(this.kf[nb[5]] || `Fkt. ${nb[5]}`)}`;
        return `<tr><td class="mono">${r}</td><td>${desc}</td><td class="mono">${spaced(p[r])}</td></tr>`;
      }).join("");
      return `<h3 style="font-size:15px;margin:12px 0 4px">${esc(this.devLabel(d))}</h3><table><tbody>${rows}</tbody></table>`;
    }).join("");
    return `<div class="overlay"><div class="dialog"><h2>Änderungen auf die Geräte schreiben?</h2>
      <p class="muted">Pro Gerät wird der Bus kurz gesperrt, der Speicher gesichert, geschrieben und jede Zeile zurückgelesen.</p>${parts}
      <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="b" data-a="close">Abbrechen</button><button class="b p" data-a="write-all">Jetzt schreiben</button></div></div></div>`;
  }

  _backupsView() {
    const s = this.s;
    const rows = s.backups.map((b) => `<tr><td>${esc(b.name)}<div class="note mono">${esc(b.id)}</div></td>
      <td>${fmtDate(b.created)}</td><td><span class="badge ${b.kind === "auto" ? "" : "ok"}">${b.kind === "auto" ? "automatisch" : b.kind === "import" ? "importiert" : "manuell"}</span></td>
      <td>${b.devices}</td>
      <td style="text-align:right;white-space:nowrap"><button class="b sm" data-a="bk-download" data-v="${esc(b.id)}">Herunterladen</button>
      <button class="b sm" data-a="bk-restore" data-v="${esc(b.id)}" ${s.busy ? "disabled" : ""}>Wiederherstellen…</button>
      <button class="b sm d" data-a="bk-delete" data-v="${esc(b.id)}">Löschen</button></td></tr>`).join("");
    return `<div class="card"><div class="row"><div class="grow"><b>Sicherungen</b><div class="muted">Kompletter Speicher aller Busgeräte. Vor jedem Schreibvorgang wird zusätzlich automatisch der Speicher des betroffenen Geräts gesichert. Ablage: <span class="mono">config/eltako_bus_config/backups</span></div></div>
      <input class="hex" style="width:220px;font-family:inherit" placeholder="Name der Sicherung" data-a="bk-name">
      <button class="b p" data-a="bk-create" ${s.busy ? "disabled" : ""}>Neue Sicherung</button>
      <button class="b" data-a="bk-import">Importieren…</button><input type="file" accept=".json,application/json" id="bk-file" style="display:none" data-a="bk-file"></div></div>
      <div class="card">${rows ? `<table><thead><tr><th>Name</th><th>Erstellt</th><th>Art</th><th>Geräte</th><th></th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="empty-state">Noch keine Sicherungen. Lege vor der ersten Änderung eine an.</div>`}</div>`;
  }

  _infoView() {
    const i = this.s.info; const st = i?.state || {};
    const gw = { fam14: "FAM14 (Mini-USB)", fgw14usb: "FGW14-USB (experimentell)", rs485: "RS485-Adapter" }[i?.gateway] || i?.gateway;
    const p = this.s.probe;
    return `<div class="card"><b>Verbindung</b><div class="kv" style="margin-top:10px">
      <span class="muted">Schnittstelle</span><span class="mono">${esc(i?.port)}</span>
      <span class="muted">Gateway</span><span>${esc(gw)}</span>
      <span class="muted">Basis-ID (FAM14)</span><span class="mono">${esc(st.base_id || "–")}</span>
      <span class="muted">Bussperre bestätigt</span><span>${st.fam_ack == null ? "–" : st.fam_ack ? "ja (FAM14 antwortet)" : "nein"}</span>
      <span class="muted">Echo auf der Leitung</span><span>${st.echo == null ? "–" : st.echo ? "ja" : "nein"}</span></div>
      <div class="row" style="margin-top:14px"><button class="b p" data-a="probe" ${this.s.busy ? "disabled" : ""}>Verbindung testen</button>
      <span class="muted">Prüft Bussperre, FAM14 und ob Geräte auf Speicheranfragen antworten.</span></div>
      ${p ? `<div class="kv" style="margin-top:12px">
        <span class="muted">FAM14 bestätigt Sperre</span><span>${p.fam_lock_ack ? "✔" : "✘"}</span>
        <span class="muted">FAM14 gefunden</span><span>${p.fam_found ? "✔" : "✘"}</span>
        <span class="muted">Geräte antworten</span><span>${p.devices_answering.length ? `✔ (Adresse ${p.devices_answering.join(", ")})` : "✘ (Adressen 1–16 geprüft)"}</span>
        <span class="muted">Speicher lesbar</span><span>${p.memory_read_ok ? `✔ <span class="mono">${esc(p.sample_row)}</span>` : "✘"}</span>
        <span class="muted">Telegramme empfangen</span><span>${p.frames_received}</span></div>
        <div class="note" style="margin-top:8px">${p.memory_read_ok ? "Speicherzugriff funktioniert – alle Funktionen sind nutzbar." : "Speicherzugriff funktioniert über dieses Gateway nicht. Verbinde Home Assistant mit der Mini-USB-Buchse des FAM14 und wähle in der Integration „FAM14“."}</div>` : ""}</div>
      <div class="card"><b>Hinweise</b><ul class="muted" style="line-height:1.6">
      <li>Vor dem Schreiben sichert die Integration den Speicher des Geräts automatisch und liest jede geschriebene Zeile zur Kontrolle zurück.</li>
      <li>PCT14 und diese Integration dürfen nicht gleichzeitig auf den FAM14 zugreifen.</li>
      <li>Die Gerätesteuerung (Licht, Rollläden …) übernimmt weiterhin die Eltako-Integration. Neue Sender-IDs aus Home Assistant trägst du hier mit der Funktion „Schaltzustand/Dimmwert/… vom Controller (GFVS)“ ein.</li></ul></div>`;
  }

  // ---------------------------------------------------------------- dialogs
  _dialog() {
    const g = this.s.dialog;
    if (g.type === "edit") return this._editDialog(g);
    if (g.type === "confirm-write") return this._confirmDialog(g);
    if (g.type === "restore") return this._restoreDialog(g);
    if (g.type === "confirm-all") return this._confirmAllDialog();
    if (g.type === "confirm") return `<div class="overlay"><div class="dialog"><h2>${esc(g.title)}</h2><p>${esc(g.text)}</p>
      <div class="row" style="justify-content:flex-end"><button class="b" data-a="close">Abbrechen</button><button class="b p ${g.danger ? "d" : ""}" data-a="dlg-ok">${esc(g.ok)}</button></div></div></div>`;
    return "";
  }

  _editDialog(g) {
    const d = this.s.devices.find((x) => x.address === g.address) || this.dev; const e = g.e; const kf = this.kf;
    const sidNorm = cleanHex(e.id).length === 8 ? idStr(hexToBytes(cleanHex(e.id))) : "";
    const sndType = this.sender(sidNorm)?.type || ([1, 2, 3, 4, 5, 6].includes(e.key) ? "rocker_switch" : null);
    const fitting = (d.type.functions_by_sender || {})[sndType] || [];
    const opt = (k, sel) => `<option value="${k}" ${sel ? "selected" : ""}>${k} – ${esc(kf[k] ?? "unbekannt")}</option>`;
    const fnOpts = (fitting.length ? `<optgroup label="Passend für ${esc(this.typeInfo(sndType)?.label || "")}">${fitting.map((k) => opt(k, k === e.fn)).join("")}</optgroup>` : "")
      + `<optgroup label="Alle Funktionen">${Object.keys(kf).map(Number).map((k) => opt(k, k === e.fn && !fitting.includes(k))).join("")}</optgroup>`
      + (kf[e.fn] === undefined ? `<option value="${e.fn}" selected>${e.fn} – unbekannt</option>` : "");
    const keyOpts = Object.entries(this.s.info?.key_labels || {}).map(([k, v]) => `<option value="${k}" ${+k === e.key ? "selected" : ""}>${esc(v)}</option>`).join("")
      + (this.s.info?.key_labels?.[e.key] === undefined ? `<option value="${e.key}" selected>Taste ${e.key}</option>` : "");
    let ch;
    if (d.type.channel_mode === "bitmask" && d.size > 1) {
      ch = `<div class="chk">${Array.from({ length: Math.min(8, d.size) }, (_, i) => `<label><input type="checkbox" data-f="chbit" data-v="${i}" ${e.ch & (1 << i) ? "checked" : ""}> Kanal ${i + 1}</label>`).join("")}</div>`;
    } else if (d.type.channel_mode === "dali_group") {
      ch = `<select data-f="ch">${Array.from({ length: 17 }, (_, i) => `<option value="${i}" ${i === e.ch ? "selected" : ""}>${i === 16 ? "Broadcast (alle)" : `DALI-Gruppe ${i}`}</option>`).join("")}</select>`;
    } else {
      ch = `<input type="number" min="0" max="255" data-f="ch" value="${e.ch}">`;
    }
    const chLabel = d.type.channel_mode === "value" ? "Dimmgeschwindigkeit (Kanal-Byte)" : d.type.channel_mode === "dali_group" ? "DALI-Gruppe" : "Kanäle";
    const l = g.listen;
    const listen = l ? `<div class="card" style="margin:0 0 12px;padding:10px"><div class="row"><b class="grow">${l.running ? "Lausche auf Telegramme… jetzt den Taster/Sensor betätigen" : "Empfangene Sender"}</b>${l.running ? "" : `<button class="b sm" data-a="listen">Erneut</button>`}</div>
      ${l.found.length ? `<table><tbody>${l.found.map((f) => `<tr><td class="mono">${esc(f.sender)}</td><td>${esc(f.kind)}${f.teach_in ? " · Lerntelegramm" : ""}${f.bus_device ? " · Bus-Aktor" : ""}</td><td class="muted">${f.count}×</td><td><button class="b sm" data-a="use-sender" data-v="${esc(f.sender)}">Übernehmen</button></td></tr>`).join("")}</tbody></table>` : `<div class="muted">Noch nichts empfangen.</div>`}</div>` : "";
    return `<div class="overlay"><div class="dialog"><h2>${g.fromLearn ? "Zuordnen" : `Zeile ${g.row}`} – ${esc(d.type.name)} Adresse ${d.address}</h2>${g.fromLearn ? `<div class="note" style="margin:-6px 0 10px">Zeile ${g.row} · Funktion ist ein Vorschlag – bitte prüfen.</div>` : ""}
      ${listen}
      ${this.s.senders.length ? `<div class="field"><label>Bekannter Sender</label><select data-f="known"><option value="">– auswählen –</option>${this._senderOptions(true).map(([v, l]) => `<option value="${esc(v)}" ${v.startsWith(cleanHex(e.id).length === 8 ? idStr(hexToBytes(cleanHex(e.id))) + "|" + e.key : "#") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>` : ""}
      <div class="field"><label>Sender-ID</label><div class="row"><input class="grow mono" data-f="id" value="${esc(e.id)}" placeholder="FE-D4-E9-47">
        <button class="b" data-a="listen" ${l?.running ? "disabled" : ""}>Sender erfassen</button></div><div class="err" id="err-id"></div></div>
      <div class="field"><label>Taste</label><select data-f="key">${keyOpts}</select></div>
      <div class="field"><label>Funktion</label><select data-f="fn">${fnOpts}</select>
        ${sndType && !fitting.length && sndType !== "unknown" ? `<div class="note" style="color:var(--warning-color,#e65100)">Für „${esc(this.typeInfo(sndType)?.label || sndType)}“ ist am ${esc(d.type.name)} keine passende Funktion bekannt – bitte prüfen, ob das Gerät diesen Sendertyp überhaupt unterstützt.</div>` : ""}</div>
      <div class="field"><label>${chLabel}</label>${ch}</div>
      <div class="field"><label>Wert (8. Byte, z. B. Prozent oder Zeit)</label><input type="number" min="0" max="255" data-f="val" value="${e.val}"></div>
      <div class="note mono" id="preview">${spaced(this._encode(e))}</div>
      <div class="row" style="justify-content:flex-end;margin-top:12px"><button class="b" data-a="close">Abbrechen</button><button class="b p" data-a="edit-ok">Übernehmen</button></div>
      <div class="note" style="margin-top:8px">„Übernehmen“ merkt die Änderung nur vor – geschrieben wird erst mit „Auf Gerät schreiben“.</div></div></div>`;
  }

  _encode(e) {
    const id = cleanHex(e.id).padEnd(8, "0").slice(0, 8);
    const b = [...(hexToBytes(id) || [0, 0, 0, 0]), e.key & 255, e.fn & 255, e.ch & 255, e.val & 255];
    return bytesToHex(b);
  }

  _confirmDialog() {
    const d = this.dev; const p = this.pendingFor(d.address);
    const rows = Object.keys(p).map(Number).sort((a, b) => a - b).map((r) => `<tr><td class="mono">${r}</td><td class="mono">${spaced(d.memory[r])}</td><td class="mono"><b>${spaced(p[r])}</b></td></tr>`).join("");
    return `<div class="overlay"><div class="dialog"><h2>Auf ${esc(d.type.name)} (Adresse ${d.address}) schreiben?</h2>
      <p class="muted">Der Bus wird kurz gesperrt. Vorher wird der Gerätespeicher automatisch gesichert, danach wird jede Zeile zur Kontrolle zurückgelesen.</p>
      <table><thead><tr><th>Zeile</th><th>Bisher</th><th>Neu</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="b" data-a="close">Abbrechen</button><button class="b p" data-a="write">Jetzt schreiben</button></div></div></div>`;
  }

  _restoreDialog(g) {
    const status = { ok: ["Änderungen", "w"], identical: ["identisch", "ok"], missing: ["Gerät fehlt", "e"], type_mismatch: ["anderer Gerätetyp", "e"], not_read: ["nicht gelesen", "e"] };
    const rows = (g.diff || []).map((x) => {
      const [label, cls] = status[x.status] || [x.status, ""];
      return `<tr><td><input type="checkbox" data-f="rs" data-v="${x.address}" ${x.status === "ok" ? "" : "disabled"} ${g.sel.includes(x.address) ? "checked" : ""}></td>
      <td class="mono">${x.address}</td><td>${esc(x.type)}${x.current_type ? ` → jetzt ${esc(x.current_type)}` : ""}</td><td><span class="badge ${cls}">${label}</span></td><td>${x.rows.length || ""}</td></tr>`;
    }).join("");
    return `<div class="overlay"><div class="dialog"><h2>Sicherung wiederherstellen</h2>
      <p class="muted">Verglichen mit dem zuletzt gelesenen Speicher. Vor dem Schreiben wird der Bus noch einmal komplett gelesen; es werden nur abweichende Zeilen geschrieben.</p>
      ${g.diff ? `<table><thead><tr><th></th><th>Adr.</th><th>Gerät</th><th>Status</th><th>Zeilen</th></tr></thead><tbody>${rows}</tbody></table>` : `<div class="muted">Vergleiche…</div>`}
      <div class="row" style="justify-content:flex-end;margin-top:14px"><button class="b" data-a="close">Abbrechen</button>
      <button class="b p" data-a="restore" ${g.sel.length ? "" : "disabled"}>${g.sel.length} Gerät${g.sel.length === 1 ? "" : "e"} wiederherstellen</button></div></div></div>`;
  }

  // ----------------------------------------------------------------- events
  _onInput(ev) {
    const t = ev.target; const g = this.s.dialog;
    if (g?.type === "edit" && t.dataset.f) {
      this._readEditField(t);
      const pv = this.shadowRoot.getElementById("preview"); if (pv) pv.textContent = spaced(this._encode(g.e));
    }
  }

  _readEditField(t) {
    const e = this.s.dialog.e; const f = t.dataset.f;
    if (f === "id") e.id = t.value;
    else if (f === "chbit") { const bit = 1 << +t.dataset.v; e.ch = t.checked ? e.ch | bit : e.ch & ~bit; }
    else if (["key", "fn", "ch", "val"].includes(f)) e[f] = Math.max(0, Math.min(255, parseInt(t.value || "0", 10) || 0));
  }

  _onChange(ev) {
    const t = ev.target; const a = t.dataset.a; const g = this.s.dialog;
    if (g?.type === "edit" && t.dataset.f === "known") {
      if (!t.value) return; const [sid, k] = t.value.split("|"); g.e.id = sid; if (k !== "" && k !== undefined) g.e.key = +k;
      const d = this.s.devices.find((x) => x.address === g.address); if (d && !g.e.idTouched) g.e.fn = this.suggestFn(d, this.sender(sid), g.e.key);
      this.render(); return;
    }
    if (g?.type === "edit" && t.dataset.f) { this._readEditField(t); const pv = this.shadowRoot.getElementById("preview"); if (pv) pv.textContent = spaced(this._encode(g.e)); return; }
    if (g?.type === "restore" && t.dataset.f === "rs") {
      const v = +t.dataset.v; g.sel = t.checked ? [...g.sel, v] : g.sel.filter((x) => x !== v); this.render(); return;
    }
    if (a === "show-empty") { this.s.showEmpty = t.checked; this.render(); }
    else if (a === "hide-bus") { this.s.hideBus = t.checked; this.render(); }
    else if (a === "monitor-lock") { this.s.monitorLock = t.checked; this.render(); }
    else if (a === "monitor-secs") { this.s.monitorSecs = +t.value; }
    else if (a === "type-filter") { this.s.typeFilter = t.value; this.render(); }
    else if (a === "sender-type") {
      if (!t.value) return;
      const sid = t.dataset.v; const val = t.value === "__auto" ? "" : t.value;
      this._ws("senders/update", { sender_id: sid, sender_type: val }).then(async () => { await this._loadSenders(); })
        .catch((e) => { this.s.error = this._msg(e); this.render(); });
    }
    else if (a === "assign") { if (!t.value) return; const [sid, k] = t.value.split("|"); const [addr, bit] = t.dataset.v.split("|").map(Number); this._assign(addr, bit, sid, +k || 0); }
    else if (a === "sender-name") {
      const sid = t.dataset.v; const name = t.value.trim();
      this._ws("senders/update", { sender_id: sid, name }).then((x) => { const i = this.s.senders.findIndex((y) => y.id === sid); if (i >= 0) this.s.senders[i] = x; this._renderSoon(); })
        .catch((e) => { this.s.error = this._msg(e); this.render(); });
    }
    else if (a === "hex") {
      const h = cleanHex(t.value);
      if (!/^[0-9a-f]{16}$/.test(h)) { t.classList.add("bad"); return; }
      this.setPending(this.dev.address, +t.dataset.v, h); this.render();
    } else if (a === "bk-file") this._import(t.files[0]);
  }

  async _onClick(ev) {
    const el = ev.target.closest("[data-a]"); if (!el || el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "LABEL") return;
    const a = el.dataset.a; const v = el.dataset.v; const s = this.s;
    switch (a) {
      case "view": s.view = v; if (v === "backups") this._loadBackups(); if (v === "learn") this._loadSenders(); this.render(); break;
      case "monitor-start": {
        s.monitoring = true; s.error = null; this.render();
        try { await this._ws("listen", { seconds: s.monitorSecs, lock_bus: s.monitorLock }); }
        catch (e) { s.error = this._msg(e); }
        s.monitoring = false; s.progress = null; await this._loadSenders(); break;
      }
      case "monitor-stop": this._ws("listen/stop").catch(() => {}); break;
      case "sender-del": await this._ws("senders/delete", { sender_id: v }); await this._loadSenders(); break;
      case "senders-clear": { const r = await this._ws("senders/clear"); this._toast(`${r.removed} unbenannte Sender entfernt`); await this._loadSenders(); break; }
      case "unassign": { const [addr, row, bit] = v.split("|").map(Number); this._unassign(addr, row, bit); break; }
      case "discard-all": s.pending = {}; this.render(); break;
      case "card-mode": { s.cardMode = s.cardMode || {}; s.cardMode[v] = (s.cardMode[v] || "rocker") === "rocker" ? "buttons" : "rocker"; this.render(); break; }
      case "revert": { const [addr, row] = v.split("|").map(Number); const d = s.devices.find((x) => x.address === addr); this.setPending(addr, row, d.memory[row]); this.render(); break; }
      case "confirm-all": s.dialog = { type: "confirm-all" }; this.render(); break;
      case "write-all": {
        s.dialog = null; const todo = Object.entries(s.pending);
        await this._run(async () => {
          let rows = 0;
          for (const [addr, p] of todo) {
            const r = await this._ws("device/write", { address: +addr, rows: p });
            this._replaceDevice(r.device); delete s.pending[addr]; rows += r.written_rows.length; this.render();
          }
          return rows;
        }, (n) => `${n} Zeile(n) auf ${todo.length} Gerät(e) geschrieben und geprüft`);
        break;
      }
      case "sel": s.sel = +v; s.sub = "table"; this.render(); break;
      case "sub": s.sub = v; this.render(); break;
      case "clear-error": s.error = null; this.render(); break;
      case "close": if (s.dialog?.listen?.running) return; s.dialog = null; this.render(); break;
      case "scan": case "scan-list": {
        if (Object.keys(s.pending).length && !confirm("Ungespeicherte Änderungen gehen beim Scan verloren. Fortfahren?")) return;
        const r = await this._run(() => this._ws("scan", { read_memory: a === "scan" }), (x) => `${x.devices.filter((d) => !d.is_fam).length} Geräte gefunden`);
        if (r) { s.devices = r.devices; s.info.state = r.state; s.pending = {}; if (!s.devices.find((d) => d.address === s.sel)) s.sel = s.devices.find((d) => !d.is_fam)?.address ?? null; this.render(); }
        break;
      }
      case "read": {
        const r = await this._run(() => this._ws("device/read", { address: s.sel }), "Speicher gelesen");
        if (r) { this._replaceDevice(r); delete s.pending[r.address]; this.render(); }
        break;
      }
      case "identify": this._run(() => this._ws("device/identify", { address: s.sel }), "Gerät blinkt"); break;
      case "discard": delete s.pending[s.sel]; this.render(); break;
      case "confirm-write": s.dialog = { type: "confirm-write" }; this.render(); break;
      case "write": {
        const d = this.dev; const rows = this.pendingFor(d.address); s.dialog = null;
        const r = await this._run(() => this._ws("device/write", { address: d.address, rows }), (x) => `${x.written_rows.length} Zeile(n) geschrieben und geprüft · Sicherung ${x.backup_id}`);
        if (r) { this._replaceDevice(r.device); delete s.pending[d.address]; this.render(); }
        break;
      }
      case "edit": this._openEdit(+v); break;
      case "add": {
        const d = this.dev; const g = d.type.groups.find((x) => x.number === +v);
        let row = null; for (let r = g.start; r < g.end; r++) if (isEmptyRow(this.rowValue(d, r))) { row = r; break; }
        if (row === null) { s.error = `${g.label} ist voll.`; this.render(); return; }
        this._openEdit(row);
        break;
      }
      case "clear-row": this.setPending(s.sel, +v, "0000000000000000"); this.render(); break;
      case "edit-ok": {
        const g = s.dialog; const id = cleanHex(g.e.id);
        if (!/^[0-9a-f]{8}$/.test(id)) { this.shadowRoot.getElementById("err-id").textContent = "Die Sender-ID braucht 8 Hex-Zeichen, z. B. FE-D4-E9-47."; return; }
        const addr = g.address ?? s.sel; const dv = s.devices.find((x) => x.address === addr);
        let row = g.row;
        if (g.fromLearn && dv) {
          const want = this.fnGroupFor(dv, g.e.fn);
          if (row < want.start || row >= want.end) {
            const nr = this.freeRow(dv, want);
            if (nr === null) { s.error = `${want.label} von ${this.devLabel(dv)} ist voll.`; s.dialog = null; this.render(); return; }
            row = nr;
          }
        }
        this.setPending(addr, row, this._encode(g.e)); s.dialog = null; this.render();
        break;
      }
      case "listen": {
        const g = s.dialog; g.listen = { running: true, found: g.listen?.found || [] }; this.render();
        try { const r = await this._ws("listen", { seconds: 15, lock_bus: s.monitorLock }); g.listen.found = r.senders; await this._loadSenders(); }
        catch (e) { s.error = this._msg(e); }
        g.listen.running = false; this.render();
        break;
      }
      case "use-sender": s.dialog.e.id = v; s.dialog.listen = null; this.render(); break;
      case "probe": { const r = await this._run(() => this._ws("probe")); if (r) { s.probe = r; const i = await this._ws("info"); s.info = i; this.render(); } break; }
      case "bk-create": {
        const name = this.shadowRoot.querySelector("[data-a=bk-name]")?.value || undefined;
        const r = await this._run(() => this._ws("backup/create", name ? { name } : {}), (x) => `Sicherung mit ${x.devices} Geräten erstellt`);
        if (r) { const dv = await this._ws("devices"); s.devices = dv.devices; s.info.state = dv.state; await this._loadBackups(); }
        break;
      }
      case "bk-import": this.shadowRoot.getElementById("bk-file").click(); break;
      case "bk-download": {
        try {
          const data = await this._ws("backup/get", { backup_id: v });
          const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
          const link = document.createElement("a"); link.href = url; link.download = `eltako-${v}.json`; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 2000);
        } catch (e) { s.error = this._msg(e); this.render(); }
        break;
      }
      case "bk-delete": s.dialog = { type: "confirm", title: "Sicherung löschen?", text: `„${v}“ wird endgültig gelöscht.`, ok: "Löschen", danger: true,
        run: async () => { await this._ws("backup/delete", { backup_id: v }); await this._loadBackups(); } }; this.render(); break;
      case "dlg-ok": { const g = s.dialog; s.dialog = null; this.render(); try { await g.run(); } catch (e) { s.error = this._msg(e); } this.render(); break; }
      case "bk-restore": {
        s.dialog = { type: "restore", id: v, diff: null, sel: [] }; this.render();
        try { const r = await this._ws("backup/diff", { backup_id: v }); s.dialog.diff = r.devices; s.dialog.sel = r.devices.filter((x) => x.status === "ok").map((x) => x.address); }
        catch (e) { s.error = this._msg(e); s.dialog = null; }
        this.render(); break;
      }
      case "restore": {
        const g = s.dialog; s.dialog = null;
        const r = await this._run(() => this._ws("backup/restore", { backup_id: g.id, addresses: g.sel }),
          (x) => `${x.results.filter((y) => y.status === "restored").length} Gerät(e) wiederhergestellt`);
        if (r) { const dv = await this._ws("devices"); s.devices = dv.devices; await this._loadBackups(); }
        break;
      }
    }
  }

  _openEdit(row, address = this.s.sel, preset = null, fromLearn = false) {
    const d = this.s.devices.find((x) => x.address === address); const b = hexToBytes(this.rowValue(d, row)); const empty = isEmptyRow(bytesToHex(b));
    const def = d.type.channel_mode === "bitmask" ? 1 : d.type.channel_mode === "dali_group" ? 16 : 1;
    const e = preset || (empty ? { id: "", key: 0, fn: d.type.suggest?.rocker ?? 2, ch: def, val: 0 } : { id: idStr(b), key: b[4], fn: b[5], ch: b[6], val: b[7] });
    this.s.dialog = { type: "edit", row, address, fromLearn, e };
    this.render();
  }

  async _loadSenders() {
    try { this.s.senders = (await this._ws("senders/list")).senders; } catch (e) { this.s.error = this._msg(e); }
    this.render();
  }

  _replaceDevice(dev) {
    const i = this.s.devices.findIndex((d) => d.address === dev.address);
    if (i >= 0) this.s.devices[i] = dev; else this.s.devices.push(dev);
  }

  async _loadBackups() {
    try { this.s.backups = (await this._ws("backup/list")).backups; } catch (e) { this.s.error = this._msg(e); }
    this.render();
  }

  async _import(file) {
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      await this._ws("backup/import", { data, name: `Import ${file.name}` });
      this._toast("Sicherung importiert"); await this._loadBackups();
    } catch (e) { this.s.error = `Import fehlgeschlagen: ${this._msg(e)}`; this.render(); }
  }
}

customElements.define("eltako-bus-config-panel", EltakoPctPanel);
