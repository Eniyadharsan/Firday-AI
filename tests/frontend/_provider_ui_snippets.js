/**
 * Ported UI logic for the multi-provider "Active Model Badge" + Model Manager.
 *
 * ⚠ SYNC NOTE: These functions are copied VERBATIM (behaviour-for-behaviour) from
 * the inline <script> in `public/index.html`. They are duplicated here only so the
 * pure logic and DOM-manipulating helpers can be unit / property tested outside a
 * live browser. If you change the originals in index.html, update these too.
 *
 * Sources in public/index.html:
 *   - abbreviateModelName(name)          (Property 7 — model name abbreviation)
 *   - providerStatusColor(status)        (Property 8 — status → color mapping)
 *   - setModelBadge(...)                 (Req 8.x / 9.3 — badge render + failover)
 *   - showPrimaryRestorePrompt(info)     (Req 9.6 — restore notification)
 *   - renderProviders(providers)         (Req 7.1/7.2/7.3 — provider list + key masking)
 */

// ---- Pure: model name abbreviation (mirrors index.html) -------------------
// Property 7: abbreviate to <=12 chars while preserving the model family identifier.
export function abbreviateModelName(name) {
  if (name == null) return '—';
  let s = String(name).trim();
  if (!s) return '—';
  // Drop org/route prefixes like "openai/gpt-4o" or "meta-llama/llama-3"
  if (s.indexOf('/') >= 0) s = s.split('/').pop();
  const lower = s.toLowerCase();
  // Known families → clean labels (each label is <=12 chars, family preserved)
  const families = [
    [/gpt-?4o/, 'GPT-4o'], [/gpt-?4\.?1/, 'GPT-4.1'], [/gpt-?4/, 'GPT-4'], [/gpt-?3\.?5/, 'GPT-3.5'],
    [/\bo3\b/, 'o3'], [/\bo1\b/, 'o1'],
    [/claude.*opus/, 'Claude-Opus'], [/claude.*sonnet/, 'Claude-Son'], [/claude.*haiku/, 'Claude-Hku'], [/claude/, 'Claude'],
    [/gemini.*flash/, 'Gemini-Fl'], [/gemini.*ultra/, 'Gemini-Ul'], [/gemini.*pro/, 'Gemini-Pro'], [/gemini/, 'Gemini'],
    [/deepseek.*r1/, 'DeepSeek-R1'], [/deepseek/, 'DeepSeek'],
    [/grok/, 'Grok'], [/llama/, 'Llama'], [/mixtral|mistral/, 'Mistral'], [/qwen/, 'Qwen'], [/cerebras/, 'Cerebras']
  ];
  for (let i = 0; i < families.length; i++) { if (families[i][0].test(lower)) return families[i][1]; }
  // Fallback: keep the leading family token, hard-cap at 12 chars
  return s.length <= 12 ? s : s.slice(0, 12);
}

// ---- Pure: provider status → color name (mirrors index.html) --------------
// Property 8 (client mirror): map provider status → color name.
export function providerStatusColor(status) {
  const map = { operational: 'green', degraded: 'yellow', unavailable: 'red', not_configured: 'gray' };
  return map[String(status || '').toLowerCase()] || 'gray';
}

// ---- DOM: active model badge render + failover marker (mirrors index.html) -
export function setModelBadge(doc, model, color, status, provider, failover) {
  const badge = doc.getElementById('modelBadge'); if (!badge) return;
  const dot = doc.getElementById('modelBadgeDot'), nameEl = doc.getElementById('modelBadgeName');
  badge.style.display = '';
  if (nameEl) nameEl.textContent = abbreviateModelName(model || provider || '');
  if (dot) dot.className = 'model-badge-dot ' + (color || 'gray');
  // Req 9.3: when the system is running on a backup provider, mark the badge
  // with the amber failover indicator and note the fallen-over primary.
  if (failover && failover.in_failover) {
    badge.classList.add('failover');
    const primary = failover.primary ? abbreviateModelName(failover.primary) : 'primary';
    badge.title = (provider ? provider + ' (backup)' : 'backup') + ' — failover active · primary ' + primary + ' unavailable · click to manage models';
  } else {
    badge.classList.remove('failover');
    badge.title = (provider ? provider + ' — ' : '') + (status || 'unknown') + ' · click to manage models';
  }
}

// ---- DOM: primary-restore prompt toast (mirrors index.html) ---------------
// Req 9.6: persistent prompt letting the user switch back to the recovered primary.
export function showPrimaryRestorePrompt(doc, info, onSwitch) {
  const provider = info && info.provider;
  if (!provider) return;
  doc.querySelectorAll('.fri-toast.action.restore').forEach(function (el) { el.remove(); });
  const t = doc.createElement('div');
  t.className = 'fri-toast action warn restore';
  const msg = doc.createElement('div');
  msg.className = 'fri-toast-msg';
  msg.textContent = (info.message || ('Primary provider "' + provider + '" is available again.'));
  const btns = doc.createElement('div');
  btns.className = 'fri-toast-btns';
  const dismiss = doc.createElement('button');
  dismiss.className = 'fri-toast-btn ghost'; dismiss.textContent = 'Keep backup';
  dismiss.onclick = function () { t.remove(); };
  const switchBtn = doc.createElement('button');
  switchBtn.className = 'fri-toast-btn'; switchBtn.textContent = 'Switch back';
  switchBtn.onclick = function () { switchBtn.disabled = true; if (onSwitch) onSwitch(provider, t); };
  btns.appendChild(dismiss); btns.appendChild(switchBtn);
  t.appendChild(msg); t.appendChild(btns);
  doc.body.appendChild(t);
  return t;
}

// ---- DOM: provider list render + write-only key masking (mirrors index.html)
// The full renderProviders in index.html closes over module state and helpers;
// here we pass them in explicitly so the render output can be asserted.
function _mmFmtLatency(ms) {
  if (ms == null || isNaN(ms)) return '—';
  if (ms < 1000) return Math.round(ms) + ' ms';
  return (ms / 1000).toFixed(2) + ' s';
}
function _mmFmtContext(n) {
  if (n == null || isNaN(n) || n <= 0) return '—';
  if (n >= 1000) return Math.round(n / 1000) + 'K ctx';
  return n + ' ctx';
}
function _mmEsc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

export function renderProviders(doc, providers, activeProvider, activeModel) {
  const listEl = doc.getElementById('mmList'); if (!listEl) return;
  if (!providers.length) { listEl.innerHTML = '<div class="mm-label">No providers registered.</div>'; return; }
  let html = '';
  providers.forEach(function (p) {
    const status = p.status || (p.is_configured ? 'operational' : 'not_configured');
    const color = p.status_color || providerStatusColor(status);   // Req 7.1: configuration/status indicator
    const isActive = p.is_active || p.name === activeProvider;
    const latency = p.is_configured ? _mmFmtLatency(p.latency_ms) : 'not configured'; // Req 7.5
    const models = p.models || [];
    html += '<div class="mm-provider' + (isActive ? ' active' : '') + '">';
    html += '<div class="mm-prov-head">';
    html += '<span class="mm-dot ' + color + '"></span>';
    html += '<span class="mm-prov-name">' + _mmEsc(p.name) + '</span>';
    html += '<span class="mm-prov-meta">' + _mmEsc(latency) + '</span>';
    if (isActive) html += '<span class="mm-badge-active">active</span>';
    html += '</div>';
    html += '<div class="mm-prov-body">';
    if (models.length) {
      html += '<div class="mm-label">MODELS</div>';
      models.forEach(function (m) {
        const mid = m.id || m.name;
        const sel = isActive && (mid === activeModel || m.name === activeModel);
        html += '<div class="mm-model' + (sel ? ' selected' : '') + '" data-provider="' + _mmEsc(p.name) + '" data-model="' + _mmEsc(mid) + '">';
        html += '<span class="nm">' + _mmEsc(m.name || mid) + '</span>';
        html += '<span class="cw">' + _mmEsc(_mmFmtContext(m.context_window)) + '</span>';
        html += '</div>';
      });
    }
    // Req 7.3: secure, write-only API key input (masked, never pre-filled with stored keys)
    if (p.is_configured) {
      html += '<div class="mm-label">API KEY <span style="color:#00ff88">✓ CONFIGURED</span> · <span class="mm-key-replace" data-replace="' + _mmEsc(p.name) + '" style="color:rgba(0,229,255,.7);cursor:pointer;text-decoration:underline">Replace</span></div>';
      html += '<div class="mm-key" data-keywrap="' + _mmEsc(p.name) + '" style="display:none">';
      html += '<input type="password" autocomplete="off" spellcheck="false" placeholder="Enter new key to replace…" data-key-input="' + _mmEsc(p.name) + '"/>';
      html += '<button data-validate="' + _mmEsc(p.name) + '">Save</button>';
      html += '</div>';
    } else {
      html += '<div class="mm-label">API KEY <span style="color:rgba(255,180,60,.9)">NOT SET</span></div>';
      html += '<div class="mm-key" data-keywrap="' + _mmEsc(p.name) + '">';
      html += '<input type="password" autocomplete="off" spellcheck="false" placeholder="Enter API key…" data-key-input="' + _mmEsc(p.name) + '"/>';
      html += '<button data-validate="' + _mmEsc(p.name) + '">Save</button>';
      html += '</div>';
    }
    html += '<div class="mm-keymsg" data-keymsg="' + _mmEsc(p.name) + '"></div>';
    html += '</div></div>';
  });
  listEl.innerHTML = html;
}
