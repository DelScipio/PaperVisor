// PaperVisor pdf.js hook: autosave annotation edits back to server.
// This file is intentionally small and independent from pdf.js sources.

(function () {
  const AUTO_SAVE_DELAY_MS = 1500;

  let saveTimer = null;
  let isSaving = false;
  let saveQueued = false;

  let autosaveHooked = false;

  function getViewerTitle() {
    const params = new URLSearchParams(window.location.search);
    const raw = (params.get('pv_title') || '').trim();
    try {
      // URLSearchParams already decodes, but keep this safe if something double-encodes.
      return (raw ? decodeURIComponent(raw) : '').trim();
    } catch (_) {
      return raw;
    }
  }

  function setViewerTitle(title) {
    const t = (title || '').trim();
    if (t) {
      document.title = t;
    }
  }

  function ensureToastStyles() {
    if (document.getElementById('pvToastStyles')) return;
    const style = document.createElement('style');
    style.id = 'pvToastStyles';
    style.textContent = `
      #pvToastHost{position:fixed; top:calc(var(--toolbar-height, 32px) + 10px); right:12px; z-index:10000; pointer-events:none;}
      #pvToastHost .pvToast{pointer-events:none; display:inline-flex; align-items:center; gap:8px; padding:8px 10px; border-radius:2px;
        background-color:var(--doorhanger-bg-color, rgba(255,255,255,0.98));
        box-shadow:0 1px 5px var(--doorhanger-border-color, rgba(0,0,0,0.2)), 0 0 0 1px var(--doorhanger-border-color, rgba(0,0,0,0.2));
        color:var(--main-color, #111);
        font:message-box;
        opacity:0;
        transform:translateY(-4px);
        transition:opacity 140ms ease, transform 140ms ease;
      }
      #pvToastHost .pvToast.pvToast--show{opacity:1; transform:translateY(0);}
    `;
    document.head.appendChild(style);
  }

  function showToast(message, timeoutMs) {
    ensureToastStyles();

    let host = document.getElementById('pvToastHost');
    if (!host) {
      host = document.createElement('div');
      host.id = 'pvToastHost';
      document.body.appendChild(host);
    }

    host.textContent = '';
    const toast = document.createElement('div');
    toast.className = 'pvToast';
    toast.textContent = message;
    host.appendChild(toast);

    // Trigger CSS transition.
    window.requestAnimationFrame(() => toast.classList.add('pvToast--show'));

    const ms = typeof timeoutMs === 'number' ? timeoutMs : 1200;
    window.setTimeout(() => {
      toast.classList.remove('pvToast--show');
      window.setTimeout(() => {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
      }, 180);
    }, ms);
  }

  function getPaperId() {
    const params = new URLSearchParams(window.location.search);
    const direct = params.get('pv_paper_id');
    if (direct) {
      console.log('[PV Hook] Paper ID from pv_paper_id:', direct);
      return direct;
    }

    const fileParam = params.get('file') || '';
    console.log('[PV Hook] File param:', fileParam);
    const decoded = decodeURIComponent(fileParam);
    console.log('[PV Hook] Decoded file param:', decoded);
    const m = decoded.match(/\/api\/papers\/([^\/?#]+)\/file/);
    const paperId = m ? m[1] : null;
    console.log('[PV Hook] Extracted paper ID:', paperId);
    return paperId;
  }

  function lsGet(key) {
    try { return window.localStorage ? window.localStorage.getItem(key) : null; } catch (_) { return null; }
  }

  function lsSet(key, value) {
    try { if (window.localStorage) window.localStorage.setItem(key, value); } catch (_) {}
  }

  function pdfProgressKey(paperId) {
    const id = (paperId || '').trim();
    return id ? ('pv_pdf_page:' + id) : '';
  }

  function serverStateUrl(paperId) {
    const id = (paperId || '').trim();
    return id ? (`/api/v1/papers/${encodeURIComponent(id)}/reading_state`) : '';
  }

  async function fetchServerState(paperId) {
    const url = serverStateUrl(paperId);
    if (!url) return null;
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) return null;
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  let lastProgressPostAt = 0;
  async function postServerState(paperId, progress, location) {
    const url = serverStateUrl(paperId);
    if (!url) return;
    const now = Date.now();
    if (now - lastProgressPostAt < 900) return; // throttle
    lastProgressPostAt = now;
    try {
      await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ progress: progress, location: location })
      });
    } catch (_) {}
  }

  function goBackToLibrary() {
    try {
      window.history.back();
    } catch (e) {
      window.location.href = '/';
    }
  }

  function scheduleSave() {
    if (saveTimer) window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => void saveToServer({ showToast: false }), AUTO_SAVE_DELAY_MS);
  }

  async function saveToServer(options) {
    if (isSaving) {
      saveQueued = true;
      return;
    }

    const showUiToast = !!(options && options.showToast);

    const paperId = getPaperId();
    const app = window.PDFViewerApplication;
    if (!paperId || !app || !app.pdfDocument || typeof app.pdfDocument.saveDocument !== 'function') {
      return;
    }

    isSaving = true;
    if (showUiToast) showToast('Saving…', 700);

    try {
      const data = await app.pdfDocument.saveDocument();
      const blob = new Blob([data], { type: 'application/pdf' });
      const form = new FormData();
      form.append('file', blob, 'document.pdf');

      const res = await fetch(`/api/v1/papers/${encodeURIComponent(paperId)}/save_pdf`, {
        method: 'POST',
        body: form,
      });

      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new Error(text || `HTTP ${res.status}`);
      }

      // Popup feedback that does NOT affect toolbar layout.
      showToast('Saved', 900);
    } catch (e) {
      const msg = (e && e.message) ? e.message : String(e);
      console.error('Save to server failed:', e);
      // Always surface errors, even for autosave.
      showToast(`Save failed: ${msg.slice(0, 120)}`, 2500);
    } finally {
      isSaving = false;
      if (saveQueued) {
        saveQueued = false;
        scheduleSave();
      }
    }
  }

  function addCustomButtons() {
    const right = document.getElementById('toolbarViewerRight');
    const left = document.getElementById('toolbarViewerLeft');

    let saveBtn = null;
    
    // Add Close tab button on the left
    if (left && !document.getElementById('pvCloseBtn')) {
      const closeBtn = document.createElement('button');
      closeBtn.id = 'pvCloseBtn';
      closeBtn.className = 'toolbarButton';
      closeBtn.type = 'button';
      closeBtn.title = 'Close tab';
      closeBtn.setAttribute('aria-label', 'Close tab');
      // Keep icon-only (pdf.js toolbar buttons hide <span> text).
      closeBtn.appendChild(document.createElement('span')).textContent = 'Close';
      closeBtn.addEventListener('click', () => {
        window.close();
        // Fallback if the browser blocks window.close().
        setTimeout(() => goBackToLibrary(), 100);
      });
      left.prepend(closeBtn);
    }

    if (!right) return;

    // Add Save-to-server button on the right
    if (!document.getElementById('pvSaveToServerBtn')) {
      saveBtn = document.createElement('button');
      saveBtn.id = 'pvSaveToServerBtn';
      saveBtn.className = 'toolbarButton';
      saveBtn.type = 'button';
      saveBtn.title = 'Save to server';
      saveBtn.setAttribute('aria-label', 'Save to server');
      // Keep icon-only (pdf.js toolbar buttons hide <span> text).
      saveBtn.appendChild(document.createElement('span')).textContent = 'Save';
      // Avoid accidental calls before the PDF is fully loaded.
      saveBtn.disabled = true;
      saveBtn.addEventListener('click', () => void saveToServer({ showToast: true }));
      right.prepend(saveBtn);
    } else {
      saveBtn = document.getElementById('pvSaveToServerBtn');
    }

    return { saveBtn };
  }

  function hookAutosave(app) {
    if (autosaveHooked) return;
    autosaveHooked = true;

    // Preferred: hook into AnnotationStorage modified flag.
    const storage = app.pdfDocument && app.pdfDocument.annotationStorage;
    if (storage && Object.prototype.hasOwnProperty.call(storage, 'onSetModified')) {
      const prev = storage.onSetModified;
      storage.onSetModified = function (modified) {
        try {
          if (typeof prev === 'function') prev.call(this, modified);
        } catch (_) {
          // ignore
        }
        if (modified) scheduleSave();
      };
      return;
    }

    // Fallback: listen for common editor events.
    const bus = app.eventBus;
    if (bus && typeof bus.on === 'function') {
      const handler = () => scheduleSave();
      ['annotationeditorparamschanged', 'annotationeditorstateschanged'].forEach((ev) => {
        try { bus.on(ev, handler); } catch (_) { /* ignore */ }
      });
    }
  }

  async function init() {
    const app = window.PDFViewerApplication;
    if (!app || !app.initializedPromise) {
      window.setTimeout(init, 50);
      return;
    }

    await app.initializedPromise;

    // Set viewer title as early as possible without affecting pdf.js load flow.
    setViewerTitle(getViewerTitle());
    const { saveBtn } = addCustomButtons() || {};

    const bus = app.eventBus;
    const onDocumentLoaded = () => {
      if (saveBtn) saveBtn.disabled = false;
      hookAutosave(app);

      // Count this as an "open" (server-side).
      try {
        const paperId = getPaperId();
        if (paperId) {
          fetch(`/api/v1/papers/${encodeURIComponent(paperId)}/opened`, { method: 'POST' }).catch(() => {});
        }
      } catch (_) {}

      // Restore last page and keep saving page changes.
      try {
        const paperId = getPaperId();
        const key = pdfProgressKey(paperId);
        const applyPage = (p) => {
          if (Number.isFinite(p) && p > 0) {
            try { app.page = p; } catch (_) { /* ignore */ }
          }
        };

        // Prefer server state, fallback to localStorage.
        (async () => {
          const st = await fetchServerState(paperId);
          const loc = st && st.location ? String(st.location) : '';
          let serverPage = 0;
          if (loc && loc.toLowerCase().startsWith('page:')) {
            const n = parseInt(loc.split(':')[1] || '0', 10);
            if (Number.isFinite(n)) serverPage = n;
          }
          if (serverPage > 0) {
            applyPage(serverPage);
            return;
          }
          if (key) {
            const saved = parseInt(lsGet(key) || '0', 10);
            applyPage(saved);
          }
        })();

        if (bus && typeof bus.on === 'function' && paperId) {
          bus.on('pagechanging', (evt) => {
            try {
              const pageNumber = evt && evt.pageNumber;
              const k = pdfProgressKey(paperId);
              if (k && pageNumber) lsSet(k, String(pageNumber));

              const total = app && app.pagesCount ? Number(app.pagesCount) : 0;
              const p = (pageNumber && total) ? Math.max(0, Math.min(1, Number(pageNumber) / Number(total))) : null;
              postServerState(paperId, p, 'page:' + String(pageNumber));
            } catch (_) { /* ignore */ }
          });
        }
      } catch (_) {
        // ignore
      }
    };

    if (bus && typeof bus.on === 'function') {
      try { bus.on('documentloaded', onDocumentLoaded); } catch (_) { /* ignore */ }
    }

    // If the document is already available, enable immediately.
    if (app.pdfDocument) onDocumentLoaded();
  }

  void init();
})();
