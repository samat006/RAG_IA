(function () {
  const script     = document.currentScript || document.querySelector('script[src*="widget.js"]');
  const API_KEY    = script ? script.getAttribute("data-key")      || "" : "";
  const ACCENT     = script ? script.getAttribute("data-color")    || "#2B7083" : "#2B7083";
  const BTN_COLOR  = script ? script.getAttribute("data-btn-color")|| "#C8302A" : "#C8302A";
  const HOST       = script ? script.src.replace(/\/widget\.js.*$/, "") : window.location.origin;
  const TITLE      = script ? script.getAttribute("data-title")    || "Robbie" : "Robbie";
  const SESSION_ID = crypto.randomUUID();
  let   abortCtrl  = null;

  /* ── CSS injecté ─────────────────────────────────────────────── */
  const style = document.createElement("style");
  style.textContent = `
    /* FAB */
    #arb-fab {
      position: fixed; bottom: 24px; right: 24px; z-index: 99999;
      width: 58px; height: 58px; border-radius: 50%;
      background: ${BTN_COLOR}; border: none; cursor: pointer;
      box-shadow: 0 4px 18px rgba(0,0,0,0.28);
      display: flex; align-items: center; justify-content: center;
      transition: transform .2s, box-shadow .2s;
    }
    #arb-fab:hover { transform: scale(1.08); box-shadow: 0 6px 22px rgba(0,0,0,0.35); }
    #arb-fab .arb-ia {
      position: absolute; top: -2px; right: -2px;
      background: ${BTN_COLOR}; border: 2px solid white; color: white;
      font-size: 8px; font-weight: 800; border-radius: 50%;
      width: 19px; height: 19px;
      display: flex; align-items: center; justify-content: center;
      letter-spacing: -0.5px;
    }

    /* Panel */
    #arb-panel {
      position: fixed; bottom: 92px; right: 24px; z-index: 99998;
      width: 300px; height: 430px;
      background: white; border-radius: 16px;
      box-shadow: 0 8px 36px rgba(0,0,0,0.18);
      display: none; flex-direction: column; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      transition: width .28s cubic-bezier(.4,0,.2,1), height .28s cubic-bezier(.4,0,.2,1), border-radius .28s;
    }
    #arb-panel.open     { display: flex; }
    #arb-panel.expanded {
      bottom: 0; right: 0;
      width: 100vw; height: 100vh;
      border-radius: 0;
    }
    #arb-panel.expanded #arb-chat {
      padding: 24px max(24px, calc(50% - 380px));
    }
    #arb-panel.expanded #arb-footer {
      padding-left:  max(16px, calc(50% - 396px));
      padding-right: max(16px, calc(50% - 396px));
    }
    @media (max-width: 500px) {
      #arb-panel.open {
        bottom: 0; right: 0; left: 0;
        width: 100%; height: 88vh;
        border-radius: 20px 20px 0 0;
      }
    }

    /* Header */
    #arb-header {
      background: ${ACCENT}; color: white;
      height: 52px; padding: 0 14px;
      display: flex; align-items: center; gap: 6px; flex-shrink: 0;
    }
    .arb-hleft { display: flex; align-items: center; gap: 6px; flex: 1; }
    .arb-hbtn {
      background: none; border: none; color: rgba(255,255,255,.85);
      cursor: pointer; padding: 5px; border-radius: 7px;
      display: flex; align-items: center; gap: 5px;
      font-size: .82rem; font-weight: 500; transition: color .15s, background .15s;
      white-space: nowrap;
    }
    .arb-hbtn:hover { color: white; background: rgba(255,255,255,.12); }
    .arb-newlabel { display: none; }
    #arb-panel.expanded .arb-newlabel { display: inline; }
    .arb-title { flex: 1; text-align: center; font-size: 1rem; font-weight: 600; }
    .arb-hactions { display: flex; align-items: center; gap: 2px; }
    .arb-hibtn {
      background: none; border: none; color: rgba(255,255,255,.85);
      cursor: pointer; padding: 6px; border-radius: 7px;
      display: flex; align-items: center; transition: color .15s, background .15s;
    }
    .arb-hibtn:hover { color: white; background: rgba(255,255,255,.12); }
    #arb-panel.expanded #arb-expand svg { width: 22px; height: 22px; }

    /* Messages */
    #arb-chat {
      flex: 1; overflow-y: auto; padding: 18px 14px;
      display: flex; flex-direction: column; gap: 10px;
      background: white; scroll-behavior: smooth;
    }
    #arb-chat::-webkit-scrollbar { width: 3px; }
    #arb-chat::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 2px; }

    .arb-bubble {
      max-width: 83%; padding: 10px 14px; border-radius: 18px;
      font-size: .875rem; line-height: 1.52; word-wrap: break-word;
    }
    .arb-bubble.bot  { background: #EAEAEA; color: #1a1a1a; align-self: flex-start; border-bottom-left-radius: 5px; }
    .arb-bubble.user { background: ${ACCENT}; color: white;  align-self: flex-end;   border-bottom-right-radius: 5px; }
    .arb-bubble.warn { background: #fff8e1; color: #7a5c00; border-left: 3px solid #f0b429; align-self: flex-start; }

    .arb-typing {
      align-self: flex-start; background: #EAEAEA;
      border-radius: 18px; border-bottom-left-radius: 5px;
      padding: 10px 16px; display: flex; gap: 4px; align-items: center;
    }
    .arb-typing span {
      width: 7px; height: 7px; background: #9ca3af; border-radius: 50%;
      animation: arb-dot 1.3s infinite;
    }
    .arb-typing span:nth-child(2) { animation-delay: .18s; }
    .arb-typing span:nth-child(3) { animation-delay: .36s; }
    @keyframes arb-dot {
      0%,80%,100% { transform: translateY(0); opacity: .5; }
      40%          { transform: translateY(-5px); opacity: 1; }
    }

    .arb-sources { display: flex; flex-wrap: wrap; gap: 5px; align-self: flex-start; max-width: 90%; }
    .arb-chip {
      background: #e5f3f7; color: ${ACCENT};
      border: 1px solid #b3d8e3; border-radius: 20px;
      padding: 3px 10px; font-size: .73rem; text-decoration: none; transition: background .15s;
    }
    .arb-chip:hover { background: #c5e4ec; }

    /* Footer */
    #arb-footer { background: #f3f4f6; border-top: 1px solid #e9eaec; padding: 10px 12px 2px; flex-shrink: 0; }
    .arb-irow { display: flex; align-items: center; gap: 8px; }
    .arb-ipill {
      flex: 1; display: flex; align-items: center;
      background: white; border: 1.5px solid #e5e7eb; border-radius: 26px;
      padding: 0 12px; gap: 6px; transition: border-color .2s;
    }
    .arb-ipill:focus-within { border-color: ${ACCENT}; }
    #arb-input {
      flex: 1; border: none; outline: none;
      font-size: .875rem; padding: 10px 0; background: transparent; color: #1a1a1a; min-width: 0;
    }
    #arb-input::placeholder { color: #b0b5be; }
    .arb-mic {
      background: none; border: none; cursor: pointer; color: #b0b5be;
      display: flex; align-items: center; padding: 2px; flex-shrink: 0; transition: color .15s;
    }
    .arb-mic:hover { color: #6b7280; }
    #arb-send {
      background: ${BTN_COLOR}; border: none; cursor: pointer;
      border-radius: 50%; width: 40px; height: 40px; flex-shrink: 0;
      display: flex; align-items: center; justify-content: center;
      transition: background .15s, border-radius .2s, width .2s, padding .2s;
    }
    #arb-send:hover { filter: brightness(0.88); }
    #arb-send:disabled { background: #d1d5db; cursor: not-allowed; filter: none; }
    .arb-slabel { display: none; color: white; font-size: .875rem; font-weight: 600; white-space: nowrap; }
    @media (min-width: 501px) {
      #arb-panel.expanded #arb-send { border-radius: 24px; width: auto; padding: 0 18px; gap: 6px; }
      #arb-panel.expanded #arb-send.stopping { border-radius: 50%; width: 40px; padding: 0; }
      #arb-panel.expanded #arb-send.stopping .arb-slabel { display: none; }
      #arb-panel.expanded #arb-send:not(.stopping) .arb-slabel { display: inline; }
    }
    .arb-brand { text-align: center; font-size: .7rem; color: #b0b5be; padding: 5px 0 6px; letter-spacing: .02em; }
  `;
  document.head.appendChild(style);

  /* ── SVG helpers ──────────────────────────────────────────────── */
  const SVG_ROBOT = `<svg width="32" height="32" viewBox="0 0 32 32" fill="none">
    <rect x="5" y="11" width="22" height="16" rx="4" fill="white" opacity=".93"/>
    <circle cx="11.5" cy="18.5" r="2.2" fill="${BTN_COLOR}"/>
    <circle cx="20.5" cy="18.5" r="2.2" fill="${BTN_COLOR}"/>
    <rect x="10.5" y="22.5" width="11" height="2.2" rx="1.1" fill="${BTN_COLOR}"/>
    <line x1="16" y1="5" x2="16" y2="11" stroke="white" stroke-width="1.8" stroke-linecap="round"/>
    <circle cx="16" cy="4" r="1.8" fill="white"/>
    <rect x="2.5" y="15" width="2.5" height="5" rx="1.25" fill="white" opacity=".65"/>
    <rect x="27" y="15" width="2.5" height="5" rx="1.25" fill="white" opacity=".65"/>
  </svg>`;
  const SVG_EDIT  = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
  const SVG_CLOSE = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
  const SVG_EXP   = `<line x1="7" y1="17" x2="3" y2="21"/><polyline points="3 17 3 21 7 21"/><line x1="17" y1="7" x2="21" y2="3"/><polyline points="21 7 21 3 17 3"/>`;
  const SVG_COMP  = `<line x1="20" y1="4" x2="13" y2="11"/><polyline points="18 11 13 11 13 6"/><line x1="4" y1="20" x2="11" y2="13"/><polyline points="6 13 11 13 11 18"/>`;
  const SVG_MIC   = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>`;
  const SVG_SEND  = `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>`;
  const SVG_STOP  = `<svg width="14" height="14" viewBox="0 0 14 14" fill="white"><rect x="2" y="2" width="10" height="10" rx="1.5"/></svg>`;

  /* ── HTML injecté ─────────────────────────────────────────────── */
  document.body.insertAdjacentHTML("beforeend", `
    <button id="arb-fab" title="Ouvrir ${TITLE}">
      ${SVG_ROBOT}
      <span class="arb-ia">IA</span>
    </button>

    <div id="arb-panel">
      <div id="arb-header">
        <div class="arb-hleft">
          <button class="arb-hbtn" id="arb-new">
            ${SVG_EDIT}
            <span class="arb-newlabel">Nouvelle question</span>
          </button>
        </div>
        <span class="arb-title">${TITLE}</span>
        <div class="arb-hactions">
          <button class="arb-hibtn" id="arb-expand">
            <svg id="arb-expico" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${SVG_EXP}</svg>
          </button>
          <button class="arb-hibtn" id="arb-close">${SVG_CLOSE}</button>
        </div>
      </div>

      <div id="arb-chat">
        <div class="arb-bubble bot">Bonjour, Je suis votre assistant touristique. Posez-moi une question sur les hébergements, activités ou le patrimoine</div>
      </div>

      <div id="arb-footer">
        <div class="arb-irow">
          <div class="arb-ipill">
            <input id="arb-input" type="text" placeholder="Posez votre question..." autocomplete="off"/>
            <button class="arb-mic" id="arb-mic">${SVG_MIC}</button>
          </div>
          <button id="arb-send">
            <span class="arb-slabel">Envoyer</span>
            ${SVG_SEND}
          </button>
        </div>
        <div class="arb-brand">By Arobase</div>
      </div>
    </div>
  `);

  /* ── Références DOM ───────────────────────────────────────────── */
  const fab     = document.getElementById("arb-fab");
  const panel   = document.getElementById("arb-panel");
  const chat    = document.getElementById("arb-chat");
  const inputEl = document.getElementById("arb-input");
  const sendBtn = document.getElementById("arb-send");
  const expIco  = document.getElementById("arb-expico");
  let expanded  = false;

  /* ── Contrôles ────────────────────────────────────────────────── */
  fab.onclick = () => {
    const isOpen = panel.classList.contains("open");
    panel.classList.toggle("open", !isOpen);
    if (!isOpen) inputEl.focus();
  };
  document.getElementById("arb-close").onclick = () => {
    panel.classList.remove("open");
    if (expanded) { panel.classList.remove("expanded"); expanded = false; fab.style.display = "flex"; expIco.innerHTML = SVG_EXP; }
  };
  document.getElementById("arb-expand").onclick = () => {
    expanded = !expanded;
    panel.classList.toggle("expanded", expanded);
    expIco.innerHTML = expanded ? SVG_COMP : SVG_EXP;
    fab.style.display = expanded ? "none" : "flex";
  };
  document.getElementById("arb-new").onclick = () => {
    chat.innerHTML = `<div class="arb-bubble bot">Bonjour, Je suis votre assistant touristique. Posez-moi une question sur les hébergements, activités ou le patrimoine</div>`;
    inputEl.value = ""; inputEl.focus();
  };
  document.getElementById("arb-mic").onclick = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    const r = new SR(); r.lang = "fr-FR"; r.interimResults = false;
    r.onresult = e => { inputEl.value = e.results[0][0].transcript; };
    r.start();
  };
  inputEl.addEventListener("keydown", e => { if (e.key === "Enter") sendQuery(); });
  sendBtn.onclick = sendQuery;

  /* ── Helpers ──────────────────────────────────────────────────── */
  function addBubble(cls) {
    const d = document.createElement("div");
    d.className = "arb-bubble " + cls;
    chat.appendChild(d);
    chat.scrollTop = chat.scrollHeight;
    return d;
  }
  function addTyping() {
    const d = document.createElement("div");
    d.className = "arb-typing";
    d.innerHTML = "<span></span><span></span><span></span>";
    chat.appendChild(d);
    chat.scrollTop = chat.scrollHeight;
    return d;
  }
  function addSources(sources) {
    if (!sources || !sources.length) return;
    const row = document.createElement("div");
    row.className = "arb-sources";
    sources.forEach(s => {
      const a = document.createElement("a");
      a.className = "arb-chip";
      a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = "📄 " + s.label + (s.dist != null ? " · " + s.dist : "");
      row.appendChild(a);
    });
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
  }

  /* ── Bouton stop / send ───────────────────────────────────────── */
  function setStopMode(on) {
    if (on) {
      sendBtn.classList.add("stopping");
      sendBtn.innerHTML = `<span class="arb-slabel">Arrêter</span>${SVG_STOP}`;
      sendBtn.title = "Arrêter la génération";
    } else {
      sendBtn.classList.remove("stopping");
      sendBtn.innerHTML = `<span class="arb-slabel">Envoyer</span>${SVG_SEND}`;
      sendBtn.title = "";
    }
    sendBtn.disabled = false;
  }

  /* ── Envoi ────────────────────────────────────────────────────── */
  async function sendQuery() {
    // Si une génération est en cours → l'interrompre
    if (abortCtrl) { abortCtrl.abort(); return; }

    const q = inputEl.value.trim();
    if (!q) return;
    addBubble("user").textContent = q;
    inputEl.value = "";
    setStopMode(true);
    const typing = addTyping();

    abortCtrl = new AbortController();
    try {
      const res = await fetch(`${HOST}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, key: API_KEY, session_id: SESSION_ID }),
        signal: abortCtrl.signal
      });

      typing.remove();
      const bot = addBubble("bot");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "", fullText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n"); buf = lines.pop();
        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const data = JSON.parse(line.slice(5).trim());
          if (data.token) { fullText += data.token; bot.textContent = fullText; chat.scrollTop = chat.scrollHeight; }
          else if (data.error) { bot.className = "arb-bubble warn"; bot.textContent = "Je n'ai pas trouvé d'information correspondant à votre question."; }
          else if (data.done) { addSources(data.sources || []); }
        }
      }
    } catch (err) {
      typing.remove();
      if (err.name !== "AbortError") {
        addBubble("warn").textContent = "❌ Erreur de connexion.";
      }
      // Si AbortError : on garde le texte déjà streamé, pas d'erreur affichée
    }
    abortCtrl = null;
    setStopMode(false);
    inputEl.focus();
  }
})();
