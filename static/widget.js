(function () {
  console.log("[AroBot] widget.js chargé ✓");
  const script  = document.currentScript || document.querySelector('script[src*="widget.js"]');
  const API_KEY    = script ? script.getAttribute("data-key")   || "" : "";
  const COLOR      = script ? script.getAttribute("data-color") || "#f25723" : "#f25723";
  const HOST       = script ? script.src.replace(/\/widget\.js.*$/, "") : window.location.origin;
  const TITLE      = script ? script.getAttribute("data-title") || "Assistant" : "Assistant";
  const SESSION_ID = crypto.randomUUID();

  /* ── Styles injectés ─────────────────────────────────────────── */
  const css = `
    #arobot-btn {
      position: fixed; bottom: 24px; right: 24px; z-index: 99999;
      width: 56px; height: 56px; border-radius: 50%;
      background: ${COLOR}; color: #fff; border: none;
      font-size: 26px; cursor: pointer;
      box-shadow: 0 4px 16px rgba(0,0,0,0.25);
      transition: transform .2s;
    }
    #arobot-btn:hover { transform: scale(1.1); }

    #arobot-panel {
      position: fixed; bottom: 92px; right: 24px; z-index: 99998;
      width: 360px; height: 520px;
      background: #f5f6fa; border-radius: 16px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.18);
      display: none; flex-direction: column;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
    }
    #arobot-panel.open { display: flex; }

    #arobot-header {
      background: ${COLOR}; color: #fff;
      padding: 14px 16px; font-weight: 600; font-size: .95rem;
      display: flex; justify-content: space-between; align-items: center;
    }
    #arobot-close {
      background: none; border: none; color: #fff;
      font-size: 18px; cursor: pointer; line-height: 1;
    }

    #arobot-chat {
      flex: 1; overflow-y: auto; padding: 14px 12px;
      display: flex; flex-direction: column; gap: 10px;
    }

    .ar-bubble {
      max-width: 82%; padding: 9px 13px; border-radius: 14px;
      font-size: .88rem; line-height: 1.45; word-wrap: break-word;
    }
    .ar-bubble.user {
      background: ${COLOR}; color: #fff;
      align-self: flex-end; border-bottom-right-radius: 3px;
    }
    .ar-bubble.bot {
      background: #fff; color: #1a1a2e;
      align-self: flex-start; border-bottom-left-radius: 3px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }

    .ar-sources {
      display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;
    }
    .ar-chip {
      background: #eef2ff; color: ${COLOR};
      border: 1px solid #c7d2fe; border-radius: 20px;
      padding: 1px 8px; font-size: .72rem; text-decoration: none;
    }
    .ar-chip:hover { background: #c7d2fe; }

    .ar-typing { display: flex; gap: 4px; align-items: center; padding: 4px 0; }
    .ar-typing span {
      width: 7px; height: 7px; background: #aaa; border-radius: 50%;
      animation: ar-bounce 1.2s infinite;
    }
    .ar-typing span:nth-child(2) { animation-delay: .2s; }
    .ar-typing span:nth-child(3) { animation-delay: .4s; }
    @keyframes ar-bounce {
      0%,80%,100% { transform: translateY(0); }
      40%         { transform: translateY(-5px); }
    }

    #arobot-footer {
      background: #fff; border-top: 1px solid #e5e7eb; padding: 10px;
      display: flex; gap: 8px;
    }
    #arobot-input {
      flex: 1; padding: 8px 14px;
      border: 1.5px solid #d1d5db; border-radius: 20px;
      font-size: .88rem; outline: none;
    }
    #arobot-input:focus { border-color: ${COLOR}; }
    #arobot-send {
      background: ${COLOR}; color: #fff; border: none;
      border-radius: 20px; padding: 8px 16px;
      font-size: .85rem; cursor: pointer;
    }
    #arobot-send:disabled { background: #9ca3af; cursor: not-allowed; }
  `;

  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  /* ── HTML injecté ─────────────────────────────────────────────── */
  document.body.insertAdjacentHTML("beforeend", `
    <button id="arobot-btn" title="Chat">💬</button>
    <div id="arobot-panel">
      <div id="arobot-header">
        <span>🏛️ ${TITLE}</span>
        <button id="arobot-close">✕</button>
      </div>
      <div id="arobot-chat"></div>
      <div id="arobot-footer">
        <input id="arobot-input" type="text" placeholder="Votre question…" autocomplete="off"/>
        <button id="arobot-send">Envoyer</button>
      </div>
    </div>
  `);

  /* ── Références DOM ───────────────────────────────────────────── */
  const btn   = document.getElementById("arobot-btn");
  const panel = document.getElementById("arobot-panel");
  const close = document.getElementById("arobot-close");
  const chat  = document.getElementById("arobot-chat");
  const input = document.getElementById("arobot-input");
  const send  = document.getElementById("arobot-send");

  btn.onclick   = () => { panel.classList.toggle("open"); if (panel.classList.contains("open")) input.focus(); };
  close.onclick = () => panel.classList.remove("open");
  input.addEventListener("keydown", e => { if (e.key === "Enter") sendQuery(); });
  send.onclick  = sendQuery;

  /* ── Helpers ──────────────────────────────────────────────────── */
  function addBubble(cls) {
    const wrap   = document.createElement("div");
    const bubble = document.createElement("div");
    bubble.className = `ar-bubble ${cls}`;
    wrap.appendChild(bubble);
    chat.appendChild(wrap);
    chat.scrollTop = chat.scrollHeight;
    return { wrap, bubble };
  }

  function addTyping() {
    const { wrap } = addBubble("bot ar-typing");
    wrap.querySelector(".ar-bubble").innerHTML = "<span></span><span></span><span></span>";
    return wrap;
  }

  function addSources(wrap, sources) {
    if (!sources || !sources.length) return;
    const row = document.createElement("div");
    row.className = "ar-sources";
    sources.forEach(s => {
      const a = document.createElement("a");
      a.className = "ar-chip";
      a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      a.textContent = `📄 ${s.label}${s.dist != null ? " · " + s.dist : ""}`;
      row.appendChild(a);
    });
    wrap.appendChild(row);
  }

  /* ── Envoi ────────────────────────────────────────────────────── */
  async function sendQuery() {
    const q = input.value.trim();
    if (!q) return;

    const { bubble: ub } = addBubble("user");
    ub.textContent = q;
    input.value = "";
    send.disabled = true;

    const loader = addTyping();

    try {
      const res = await fetch(`${HOST}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, key: API_KEY, session_id: SESSION_ID })
      });

      loader.remove();
      const { wrap, bubble } = addBubble("bot");
      bubble.textContent = "";
      let fullText = "";

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const data = JSON.parse(line.slice(5).trim());

          if (data.token) {
            fullText += data.token;
            bubble.textContent = fullText;
            chat.scrollTop = chat.scrollHeight;
          } else if (data.error) {
            bubble.textContent = "Je n'ai pas trouvé d'information. Pourriez-vous reformuler ?";
          } else if (data.done) {
            addSources(wrap, data.sources || []);
          }
        }
      }
    } catch {
      loader.remove();
      const { bubble } = addBubble("bot");
      bubble.textContent = "❌ Erreur de connexion.";
    }

    send.disabled = false;
    input.focus();
  }
})();
