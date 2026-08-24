/**
 * Aternos 24/7 Keep-Alive Automation & Web Dashboard
 * Client-side Real-Time Controller & Stream Manager.
 * Architecture: WebSocket -> SSE Fallback -> Polling Fallback.
 */

(function () {
  'use strict';

  // State Management
  const state = {
    server: {
      status: 'offline',
      countdown_seconds: null,
      countdown_text: '--:--',
      plus_one_click_count: 0,
      last_plus_one_click: null,
      is_keepalive_active: true,
      session_valid: true,
      queue_position: null,
      players_current: 0,
      players_max: 20,
    },
    connection: {
      mode: 'disconnected', // 'ws' | 'sse' | 'polling' | 'disconnected'
      ws: null,
      sse: null,
      pollInterval: null,
      reconnectAttempts: 0,
      maxReconnectAttempts: 10,
    },
    logs: {
      buffer: [],
      maxBuffer: 1000,
      domLimit: 500,
      activeFilter: 'ALL',
      searchQuery: '',
      isPaused: false,
      autoScroll: true,
      unseenCount: 0,
    },
    uptimeSeconds: 0,
    screenshotInterval: null,
  };

  // DOM Elements Cache
  const el = {
    connDot: document.getElementById('conn-dot'),
    connText: document.getElementById('conn-text'),
    headerKeepaliveToggle: document.getElementById('header-keepalive-toggle'),
    statusBadge: document.getElementById('status-badge'),
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text'),
    serverIp: document.getElementById('server-ip'),
    playersCount: document.getElementById('players-count'),
    countdownTimer: document.getElementById('countdown-timer'),
    timerRing: document.getElementById('timer-ring'),
    timerCaption: document.getElementById('timer-status-caption'),
    countdownLabel: document.getElementById('countdown-label'),
    queueStatusText: document.getElementById('queue-status-text'),
    lastUpdatedText: document.getElementById('last-updated-text'),
    metricTotalClicks: document.getElementById('metric-total-clicks'),
    metricLastClick: document.getElementById('metric-last-click'),
    metricUptime: document.getElementById('metric-uptime'),
    metricSessionValid: document.getElementById('metric-session-valid'),
    metricSessionText: document.getElementById('metric-session-text'),
    btnStart: document.getElementById('btn-start'),
    btnStop: document.getElementById('btn-stop'),
    btnExtend: document.getElementById('btn-extend'),
    btnToggleKeepalive: document.getElementById('btn-toggle-keepalive'),
    btnReloadSession: document.getElementById('btn-reload-session'),
    btnRefreshScreenshot: document.getElementById('btn-refresh-screenshot'),
    btnManualSnap: document.getElementById('btn-manual-snap'),
    autoRefreshScreenshot: document.getElementById('auto-refresh-screenshot'),
    screenshotImg: document.getElementById('screenshot-img'),
    screenshotContainer: document.getElementById('screenshot-container'),
    screenshotModal: document.getElementById('screenshot-modal'),
    modalScreenshotImg: document.getElementById('modal-screenshot-img'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    logConsole: document.getElementById('log-console'),
    logSearchInput: document.getElementById('log-search-input'),
    logFilterGroup: document.getElementById('log-filter-group'),
    btnPauseLogs: document.getElementById('btn-pause-logs'),
    btnClearLogs: document.getElementById('btn-clear-logs'),
    btnExportLogs: document.getElementById('btn-export-logs'),
    btnJumpLatest: document.getElementById('btn-jump-latest'),
    unseenLogBadge: document.getElementById('unseen-log-badge'),
    toastContainer: document.getElementById('toast-container'),
  };

  const RING_CIRCUMFERENCE = 2 * Math.PI * 68; // 427.26 px

  // ========================================================================
  // 1. Toast Notification Utility
  // ========================================================================
  function showToast(message, type = 'info', duration = 3500) {
    if (!el.toastContainer) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconSvg = '';
    if (type === 'success') {
      iconSvg = '<svg class="w-5 h-5 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
    } else if (type === 'error') {
      iconSvg = '<svg class="w-5 h-5 text-rose-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';
    } else if (type === 'warning') {
      iconSvg = '<svg class="w-5 h-5 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>';
    } else {
      iconSvg = '<svg class="w-5 h-5 text-indigo-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
    }

    toast.innerHTML = `
      ${iconSvg}
      <div class="text-xs font-mono text-slate-100 flex-1 leading-snug">${escapeHtml(message)}</div>
    `;

    el.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ========================================================================
  // 2. Real-Time Transport: WebSocket -> SSE -> Polling
  // ========================================================================
  function initRealtimeConnection() {
    connectWebSocket();
  }

  function updateConnectionBadge(mode, label, dotColor) {
    state.connection.mode = mode;
    if (el.connText) el.connText.textContent = label;
    if (el.connDot) {
      el.connDot.className = `w-2 h-2 rounded-full ${dotColor}`;
    }
  }

  function connectWebSocket() {
    if (state.connection.ws) {
      try { state.connection.ws.close(); } catch (_) {}
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    updateConnectionBadge('ws', 'Connecting WS...', 'bg-amber-400 animate-pulse');

    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = function () {
        state.connection.reconnectAttempts = 0;
        updateConnectionBadge('ws', 'WebSocket Live', 'bg-emerald-400');
        showToast('Real-time WebSocket stream connected', 'success', 2500);

        // Fetch immediate status snapshot
        ws.send(JSON.stringify({ action: 'get_status' }));
      };

      ws.onmessage = function (event) {
        try {
          const data = JSON.parse(event.data);
          handleIncomingMessage(data);
        } catch (e) {
          console.debug('WS Parse error:', e);
        }
      };

      ws.onerror = function () {
        console.warn('WebSocket error, attempting SSE fallback...');
      };

      ws.onclose = function () {
        console.info('WebSocket closed, switching to SSE fallback...');
        state.connection.ws = null;
        connectSSE();
      };

      state.connection.ws = ws;
    } catch (e) {
      console.warn('WebSocket init failed, fallback to SSE:', e);
      connectSSE();
    }
  }

  function connectSSE() {
    if (state.connection.sse) {
      try { state.connection.sse.close(); } catch (_) {}
    }

    updateConnectionBadge('sse', 'SSE Stream', 'bg-cyan-400 animate-pulse');

    try {
      const sse = new EventSource('/api/events');

      sse.onopen = function () {
        updateConnectionBadge('sse', 'SSE Stream Live', 'bg-cyan-400');
        showToast('Connected via Server-Sent Events', 'info', 2500);
      };

      sse.onmessage = function (event) {
        try {
          const data = JSON.parse(event.data);
          handleIncomingMessage(data);
        } catch (e) {
          console.debug('SSE Message parse error:', e);
        }
      };

      sse.addEventListener('status_update', function (event) {
        try {
          const data = JSON.parse(event.data);
          updateServerState(data);
        } catch (e) {
          console.debug('SSE status error:', e);
        }
      });

      sse.onerror = function () {
        console.warn('SSE error, switching to HTTP polling...');
        sse.close();
        state.connection.sse = null;
        startPolling();
      };

      state.connection.sse = sse;
    } catch (e) {
      console.warn('SSE failed, starting polling:', e);
      startPolling();
    }
  }

  function startPolling() {
    if (state.connection.pollInterval) return;

    updateConnectionBadge('polling', 'HTTP Polling (3s)', 'bg-amber-400');
    showToast('Operating in HTTP polling fallback mode', 'warning', 3000);

    pollStatus();
    state.connection.pollInterval = setInterval(pollStatus, 3000);
  }

  async function pollStatus() {
    try {
      const res = await fetch('/api/status');
      if (res.ok) {
        const data = await res.json();
        updateServerState(data);
      }
      // Also poll logs periodically in polling mode
      const logsRes = await fetch('/api/logs?limit=20');
      if (logsRes.ok) {
        const logsData = await logsRes.json();
        if (Array.isArray(logsData)) {
          logsData.forEach(appendLogEntry);
        }
      }
    } catch (e) {
      updateConnectionBadge('disconnected', 'Disconnected', 'bg-rose-500');
    }
  }

  // ========================================================================
  // 3. Message Routing & State Processing
  // ========================================================================
  function handleIncomingMessage(msg) {
    if (!msg) return;

    // Check if it's a LogEvent
    if (msg.level && msg.message) {
      appendLogEntry(msg);
      return;
    }

    // Check if it's a ServerState update or wrapped payload
    if (msg.type === 'status' && msg.data) {
      updateServerState(msg.data);
    } else if (msg.status && msg.is_keepalive_active !== undefined) {
      updateServerState(msg);
    } else if (msg.type === 'action_result') {
      showToast(`Action ${msg.action}: ${msg.success ? 'Success' : 'Failed'}`, msg.success ? 'success' : 'error');
    }
  }

  function updateServerState(serverData) {
    if (!serverData) return;

    // Merge incoming data into client state
    Object.assign(state.server, serverData);

    renderServerStatus();
    renderCountdownRing();
    renderMetrics();
    renderControlButtons();
  }

  // ========================================================================
  // 4. UI Rendering Handlers
  // ========================================================================
  function renderServerStatus() {
    const rawStatus = (state.server.status || 'offline').toLowerCase();
    const statusUpper = rawStatus.toUpperCase();

    if (el.statusText) el.statusText.textContent = statusUpper;

    // Reset badge classes
    if (el.statusBadge) {
      el.statusBadge.className = 'px-3.5 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider flex items-center gap-2';

      if (rawStatus === 'online') {
        el.statusBadge.classList.add('badge-online');
        if (el.statusDot) el.statusDot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-ping';
      } else if (rawStatus === 'in_queue') {
        el.statusBadge.classList.add('badge-in-queue');
        if (el.statusDot) el.statusDot.className = 'w-2 h-2 rounded-full bg-amber-400 animate-spin';
      } else if (rawStatus === 'loading') {
        el.statusBadge.classList.add('badge-loading');
        if (el.statusDot) el.statusDot.className = 'w-2 h-2 rounded-full bg-cyan-400 animate-pulse';
      } else if (rawStatus === 'stopping') {
        el.statusBadge.classList.add('badge-stopping');
        if (el.statusDot) el.statusDot.className = 'w-2 h-2 rounded-full bg-orange-400';
      } else if (rawStatus === 'crashed') {
        el.statusBadge.classList.add('badge-crashed');
        if (el.statusDot) el.statusDot.className = 'w-2 h-2 rounded-full bg-rose-500 animate-pulse';
      } else {
        el.statusBadge.classList.add('badge-offline');
        if (el.statusDot) el.statusDot.className = 'w-2 h-2 rounded-full bg-slate-400';
      }
    }

    if (el.serverIp && state.server.server_ip) {
      el.serverIp.textContent = state.server.server_ip;
    }

    if (el.playersCount) {
      el.playersCount.textContent = `${state.server.players_current || 0} / ${state.server.players_max || 20} Players`;
    }

    if (el.queueStatusText) {
      if (rawStatus === 'in_queue') {
        el.queueStatusText.textContent = `Queue: Position #${state.server.queue_position || 1} (${state.server.queue_time || 'estimating...'})`;
      } else {
        el.queueStatusText.textContent = `Server: ${statusUpper}`;
      }
    }

    if (el.lastUpdatedText) {
      const now = new Date();
      el.lastUpdatedText.textContent = `Updated: ${now.toLocaleTimeString()}`;
    }
  }

  function renderCountdownRing() {
    const rawStatus = (state.server.status || 'offline').toLowerCase();
    const seconds = state.server.countdown_seconds;

    if (rawStatus !== 'online' || seconds === null || seconds === undefined) {
      if (el.countdownTimer) el.countdownTimer.textContent = '--:--';
      if (el.timerRing) {
        el.timerRing.style.strokeDashoffset = '0';
        el.timerRing.className = 'progress-ring__circle ring-calm';
      }
      if (el.timerCaption) el.timerCaption.textContent = 'Server ' + rawStatus.toUpperCase();
      if (el.countdownLabel) {
        el.countdownLabel.textContent = rawStatus === 'in_queue' ? 'Waiting in queue...' : 'Timer standby';
        el.countdownLabel.className = 'text-sm text-slate-400 font-medium mt-0.5';
      }
      return;
    }

    // Format digital countdown string mm:ss
    const mins = Math.floor(seconds / 60);
    const remSec = seconds % 60;
    const formatted = `${String(mins).padStart(2, '0')}:${String(remSec).padStart(2, '0')}`;

    if (el.countdownTimer) el.countdownTimer.textContent = formatted;
    if (el.timerCaption) el.timerCaption.textContent = 'Countdown Extension';

    // Calculate ring stroke-dashoffset (assuming 360s full cycle or dynamic max)
    const maxTimer = 360;
    const percentage = Math.min(100, Math.max(0, (seconds / maxTimer) * 100));
    const offset = RING_CIRCUMFERENCE - (percentage / 100) * RING_CIRCUMFERENCE;

    if (el.timerRing) {
      el.timerRing.style.strokeDashoffset = String(offset);

      // Dynamic threshold coloring
      if (seconds <= 30) {
        el.timerRing.className = 'progress-ring__circle ring-urgent';
        if (el.countdownLabel) {
          el.countdownLabel.textContent = 'EMERGENCY: Countdown Critical (<= 30s)';
          el.countdownLabel.className = 'text-sm text-rose-400 font-bold mt-0.5 animate-pulse';
        }
      } else if (seconds <= 180) {
        el.timerRing.className = 'progress-ring__circle ring-warning';
        if (el.countdownLabel) {
          el.countdownLabel.textContent = 'Keep-Alive Range (<= 3:00) - Trigger Ready';
          el.countdownLabel.className = 'text-sm text-amber-400 font-medium mt-0.5';
        }
      } else {
        el.timerRing.className = 'progress-ring__circle ring-calm';
        if (el.countdownLabel) {
          el.countdownLabel.textContent = 'Safe Zone (> 3:00) - Monitoring';
          el.countdownLabel.className = 'text-sm text-emerald-400 font-medium mt-0.5';
        }
      }
    }
  }

  function renderMetrics() {
    if (el.metricTotalClicks) {
      el.metricTotalClicks.textContent = String(state.server.plus_one_click_count || 0);
    }

    if (el.metricLastClick) {
      if (state.server.last_plus_one_click) {
        const d = new Date(state.server.last_plus_one_click);
        el.metricLastClick.textContent = d.toLocaleTimeString();
      } else {
        el.metricLastClick.textContent = 'None yet';
      }
    }

    if (el.metricSessionValid && el.metricSessionText) {
      if (state.server.session_valid) {
        el.metricSessionValid.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400';
        el.metricSessionText.textContent = 'Authenticated';
      } else {
        el.metricSessionValid.className = 'w-2.5 h-2.5 rounded-full bg-rose-500 animate-pulse';
        el.metricSessionText.textContent = 'Session Expired';
      }
    }

    if (el.headerKeepaliveToggle) {
      el.headerKeepaliveToggle.checked = Boolean(state.server.is_keepalive_active);
    }
  }

  function renderControlButtons() {
    const rawStatus = (state.server.status || 'offline').toLowerCase();

    // Start button: enabled only when offline or crashed
    if (el.btnStart) {
      el.btnStart.disabled = rawStatus === 'online' || rawStatus === 'loading' || rawStatus === 'in_queue';
    }

    // Stop button: enabled only when online, loading, or in_queue
    if (el.btnStop) {
      el.btnStop.disabled = rawStatus === 'offline' || rawStatus === 'stopping';
    }
  }

  // ========================================================================
  // 5. Terminal Log Console Management
  // ========================================================================
  function appendLogEntry(log) {
    if (!log || !log.message) return;

    // Avoid duplicate logs by ID if present
    if (log.id && state.logs.buffer.some((l) => l.id === log.id)) {
      return;
    }

    // Add to buffer
    state.logs.buffer.push(log);
    if (state.logs.buffer.length > state.logs.maxBuffer) {
      state.logs.buffer.shift();
    }

    if (state.logs.isPaused) {
      state.logs.unseenCount++;
      updateUnseenBadge();
      return;
    }

    // Check if log matches current active filter and search query
    if (matchesFilter(log)) {
      renderLogLine(log);
    }
  }

  function matchesFilter(log) {
    const filter = state.logs.activeFilter.toUpperCase();
    const level = (log.level || 'INFO').toUpperCase();

    if (filter !== 'ALL') {
      if (filter === 'PLUS_ONE' && level !== 'PLUS_ONE') return false;
      if (filter === 'INFO' && level !== 'INFO') return false;
      if (filter === 'SUCCESS' && level !== 'SUCCESS') return false;
      if (filter === 'WARN' && level !== 'WARN' && level !== 'WARNING') return false;
      if (filter === 'ERROR' && level !== 'ERROR') return false;
    }

    if (state.logs.searchQuery) {
      const q = state.logs.searchQuery.toLowerCase();
      const msg = (log.message || '').toLowerCase();
      if (!msg.includes(q)) return false;
    }

    return true;
  }

  function renderLogLine(log) {
    if (!el.logConsole) return;

    // Clear initial placeholder if needed
    if (el.logConsole.children.length === 1 && el.logConsole.children[0].classList.contains('italic')) {
      el.logConsole.innerHTML = '';
    }

    const line = document.createElement('div');
    line.className = 'log-line';

    const timeStr = log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    const lvl = (log.level || 'INFO').toUpperCase();
    const tagClass = `log-tag-${lvl.toLowerCase().replace('warning', 'warn')}`;

    line.innerHTML = `
      <span class="log-timestamp">[${timeStr}]</span>
      <span class="log-tag ${tagClass}">[${lvl}]</span>
      <span class="log-msg">${escapeHtml(log.message)}</span>
    `;

    el.logConsole.appendChild(line);

    // Limit DOM child nodes to prevent memory growth
    while (el.logConsole.children.length > state.logs.domLimit) {
      el.logConsole.removeChild(el.logConsole.firstChild);
    }

    // Auto-scroll handling
    if (state.logs.autoScroll) {
      el.logConsole.scrollTop = el.logConsole.scrollHeight;
    } else {
      state.logs.unseenCount++;
      updateUnseenBadge();
    }
  }

  function reRenderAllLogs() {
    if (!el.logConsole) return;
    el.logConsole.innerHTML = '';

    const matching = state.logs.buffer.filter(matchesFilter);
    matching.slice(-state.logs.domLimit).forEach((log) => renderLogLine(log));

    if (matching.length === 0) {
      el.logConsole.innerHTML = '<div class="text-xs text-slate-500 italic px-2 py-1">No logs match the current filter.</div>';
    } else {
      el.logConsole.scrollTop = el.logConsole.scrollHeight;
    }
  }

  function updateUnseenBadge() {
    if (!el.btnJumpLatest || !el.unseenLogBadge) return;
    if (state.logs.unseenCount > 0) {
      el.btnJumpLatest.classList.remove('hidden');
      el.unseenLogBadge.textContent = String(state.logs.unseenCount);
    } else {
      el.btnJumpLatest.classList.add('hidden');
    }
  }

  // ========================================================================
  // 6. Action Handlers (REST & WebSocket Dispatch)
  // ========================================================================
  async function dispatchAction(url, payload = null, loadingBtn = null, successMsg = null) {
    if (loadingBtn) {
      loadingBtn.disabled = true;
      loadingBtn.classList.add('opacity-75');
    }

    try {
      const options = {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      };
      if (payload) {
        options.body = JSON.stringify(payload);
      }

      const res = await fetch(url, options);
      const data = await res.json();

      if (data.success) {
        showToast(successMsg || data.message || 'Action executed successfully', 'success');
      } else {
        showToast(data.message || 'Action failed', 'error');
      }
      return data;
    } catch (e) {
      showToast(`Network error: ${e.message}`, 'error');
      return { success: false, error: e.message };
    } finally {
      if (loadingBtn) {
        loadingBtn.disabled = false;
        loadingBtn.classList.remove('opacity-75');
      }
    }
  }

  function refreshScreenshot() {
    if (!el.screenshotImg) return;
    const cacheBuster = `?t=${Date.now()}`;
    el.screenshotImg.src = `/api/screenshot${cacheBuster}`;
    if (el.modalScreenshotImg) {
      el.modalScreenshotImg.src = `/api/screenshot${cacheBuster}`;
    }
    const tsEl = document.getElementById('screenshot-timestamp');
    if (tsEl) tsEl.textContent = new Date().toLocaleTimeString();
  }

  // ========================================================================
  // 7. Event Listeners Setup
  // ========================================================================
  function bindEventListeners() {
    // Start Button
    if (el.btnStart) {
      el.btnStart.addEventListener('click', async () => {
        await dispatchAction('/api/action/start', null, el.btnStart, 'Server startup initiated');
      });
    }

    // Stop Button (with confirmation)
    if (el.btnStop) {
      el.btnStop.addEventListener('click', async () => {
        if (confirm('Are you sure you want to stop the Minecraft server?')) {
          await dispatchAction('/api/action/stop', null, el.btnStop, 'Server shutdown initiated');
        }
      });
    }

    // Extend +1 Button
    if (el.btnExtend) {
      el.btnExtend.addEventListener('click', async () => {
        const startTs = performance.now();
        const res = await dispatchAction('/api/action/extend', null, el.btnExtend);
        const duration = Math.round(performance.now() - startTs);
        if (res && res.success) {
          showToast(`+1 Clicked successfully (${duration}ms latency)`, 'success');
        }
      });
    }

    // Toggle Keep-Alive (Both Buttons)
    const handleToggle = async (en) => {
      await dispatchAction('/api/action/toggle-keepalive', { enabled: en }, null);
    };

    if (el.btnToggleKeepalive) {
      el.btnToggleKeepalive.addEventListener('click', () => {
        handleToggle(!state.server.is_keepalive_active);
      });
    }

    if (el.headerKeepaliveToggle) {
      el.headerKeepaliveToggle.addEventListener('change', (e) => {
        handleToggle(e.target.checked);
      });
    }

    // Reload Session
    if (el.btnReloadSession) {
      el.btnReloadSession.addEventListener('click', async () => {
        await dispatchAction('/api/action/reload-session', null, el.btnReloadSession, 'Session cookies reloaded');
      });
    }

    // Launch Visible Browser Button
    const btnLaunchVisible = document.getElementById('btn-launch-visible');
    if (btnLaunchVisible) {
      btnLaunchVisible.addEventListener('click', async () => {
        showToast('جاري فتح نافذة المتصفح المرئي على شاشتك...', 'info', 4000);
        await dispatchAction('/api/action/launch-visible-browser', null, btnLaunchVisible, 'Visible browser launched');
      });
    }

    // Screenshot Controls
    if (el.btnRefreshScreenshot) {
      el.btnRefreshScreenshot.addEventListener('click', refreshScreenshot);
    }
    if (el.btnManualSnap) {
      el.btnManualSnap.addEventListener('click', refreshScreenshot);
    }

    if (el.autoRefreshScreenshot) {
      el.autoRefreshScreenshot.addEventListener('change', (e) => {
        if (e.target.checked) {
          state.screenshotInterval = setInterval(refreshScreenshot, 10000);
          showToast('Auto-refresh screenshot enabled (10s)', 'info');
        } else {
          clearInterval(state.screenshotInterval);
          state.screenshotInterval = null;
        }
      });
    }

    // Modal Zoom
    if (el.screenshotContainer) {
      el.screenshotContainer.addEventListener('click', () => {
        if (el.screenshotModal) el.screenshotModal.classList.remove('hidden');
      });
    }
    if (el.btnCloseModal) {
      el.btnCloseModal.addEventListener('click', () => {
        if (el.screenshotModal) el.screenshotModal.classList.add('hidden');
      });
    }
    if (el.screenshotModal) {
      el.screenshotModal.addEventListener('click', (e) => {
        if (e.target === el.screenshotModal) {
          el.screenshotModal.classList.add('hidden');
        }
      });
    }

    // Log Console Filters
    if (el.logFilterGroup) {
      el.logFilterGroup.addEventListener('click', (e) => {
        const btn = e.target.closest('.log-filter-btn');
        if (!btn) return;

        el.logFilterGroup.querySelectorAll('.log-filter-btn').forEach((b) => {
          b.className = 'log-filter-btn px-2 py-0.5 rounded text-[11px] text-slate-400 hover:text-white';
        });
        btn.className = 'log-filter-btn px-2 py-0.5 rounded text-[11px] font-bold bg-indigo-600 text-white';

        state.logs.activeFilter = btn.dataset.level || 'ALL';
        reRenderAllLogs();
      });
    }

    // Log Search Input
    if (el.logSearchInput) {
      el.logSearchInput.addEventListener('input', (e) => {
        state.logs.searchQuery = e.target.value.trim();
        reRenderAllLogs();
      });
    }

    // Log Pause / Resume
    if (el.btnPauseLogs) {
      el.btnPauseLogs.addEventListener('click', () => {
        state.logs.isPaused = !state.logs.isPaused;
        if (state.logs.isPaused) {
          el.btnPauseLogs.classList.add('bg-amber-600', 'text-white');
          el.btnPauseLogs.classList.remove('bg-slate-800');
          showToast('Live log feed PAUSED', 'warning');
        } else {
          el.btnPauseLogs.classList.remove('bg-amber-600', 'text-white');
          el.btnPauseLogs.classList.add('bg-slate-800');
          state.logs.unseenCount = 0;
          updateUnseenBadge();
          reRenderAllLogs();
          showToast('Live log feed RESUMED', 'info');
        }
      });
    }

    // Log Clear
    if (el.btnClearLogs) {
      el.btnClearLogs.addEventListener('click', async () => {
        state.logs.buffer = [];
        state.logs.unseenCount = 0;
        updateUnseenBadge();
        if (el.logConsole) el.logConsole.innerHTML = '<div class="text-xs text-slate-500 italic px-2 py-1">Log buffer cleared.</div>';
        try {
          await fetch('/api/logs', { method: 'DELETE' });
        } catch (_) {}
        showToast('Console buffer cleared', 'info');
      });
    }

    // Log Export
    if (el.btnExportLogs) {
      el.btnExportLogs.addEventListener('click', () => {
        if (state.logs.buffer.length === 0) {
          showToast('No logs to export', 'warning');
          return;
        }
        const textContent = state.logs.buffer
          .map((l) => `[${l.timestamp || new Date().toISOString()}] [${l.level || 'INFO'}] ${l.message}`)
          .join('\n');

        const blob = new Blob([textContent], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `aternos-logs-${new Date().toISOString().slice(0, 10)}.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('Logs exported successfully', 'success');
      });
    }

    // Log Scroll & Jump to Latest
    if (el.logConsole) {
      el.logConsole.addEventListener('scroll', () => {
        const isNearBottom = el.logConsole.scrollHeight - el.logConsole.scrollTop - el.logConsole.clientHeight < 40;
        state.logs.autoScroll = isNearBottom;
        if (isNearBottom) {
          state.logs.unseenCount = 0;
          updateUnseenBadge();
        }
      });
    }

    if (el.btnJumpLatest) {
      el.btnJumpLatest.addEventListener('click', () => {
        if (el.logConsole) {
          el.logConsole.scrollTop = el.logConsole.scrollHeight;
          state.logs.autoScroll = true;
          state.logs.unseenCount = 0;
          updateUnseenBadge();
        }
      });
    }
  }

  // ========================================================================
  // 8. Uptime Counter Ticker
  // ========================================================================
  function startUptimeTicker() {
    setInterval(() => {
      state.uptimeSeconds++;
      const hrs = Math.floor(state.uptimeSeconds / 3600);
      const mins = Math.floor((state.uptimeSeconds % 3600) / 60);
      const secs = state.uptimeSeconds % 60;
      if (el.metricUptime) {
        el.metricUptime.textContent = `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
      }
    }, 1000);
  }

  // ========================================================================
  // 9. Application Bootstrap
  // ========================================================================
  async function bootstrap() {
    bindEventListeners();
    startUptimeTicker();

    // Initial fetch of logs history
    try {
      const res = await fetch('/api/logs?limit=100');
      if (res.ok) {
        const logs = await res.json();
        if (Array.isArray(logs)) {
          logs.forEach((l) => state.logs.buffer.push(l));
          reRenderAllLogs();
        }
      }
    } catch (_) {}

    // Initialize real-time streams
    initRealtimeConnection();
  }

  // ========================================================================
  // 10. Interactive Viewport Control Mode
  // ========================================================================
  (function setupViewportControlMode() {
    const btnControl = document.getElementById('btn-control-mode');
    const banner     = document.getElementById('control-mode-banner');
    const container  = document.getElementById('screenshot-container');
    const img        = document.getElementById('screenshot-img');
    const ripple     = document.getElementById('click-ripple');
    const hoverOverlay = document.getElementById('viewport-hover-overlay');

    if (!btnControl || !container || !img) return;

    let controlActive = false;

    function setControlMode(active) {
      controlActive = active;
      if (active) {
        btnControl.textContent = '⛔ إيقاف التحكم المباشر';
        btnControl.classList.remove('bg-slate-800', 'border-slate-700', 'text-slate-300');
        btnControl.classList.add('bg-sky-700', 'border-sky-500', 'text-white');
        banner.classList.remove('hidden');
        container.classList.add('cursor-crosshair', 'border-sky-500');
        container.classList.remove('border-slate-700');
        if (hoverOverlay) hoverOverlay.classList.add('hidden');
      } else {
        btnControl.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5"/></svg> تفعيل التحكم المباشر بالمتصفح`;
        btnControl.classList.add('bg-slate-800', 'border-slate-700', 'text-slate-300');
        btnControl.classList.remove('bg-sky-700', 'border-sky-500', 'text-white');
        banner.classList.add('hidden');
        container.classList.remove('cursor-crosshair', 'border-sky-500');
        container.classList.add('border-slate-700');
        if (hoverOverlay) hoverOverlay.classList.remove('hidden');
      }
    }

    btnControl.addEventListener('click', () => setControlMode(!controlActive));

    container.addEventListener('click', async (e) => {
      if (!controlActive) {
        // First click activates control mode
        setControlMode(true);
        return;
      }

      const rect = img.getBoundingClientRect();
      const x_pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const y_pct = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

      // Show ripple at click position
      if (ripple) {
        ripple.style.left = (e.clientX - rect.left - 12) + 'px';
        ripple.style.top  = (e.clientY - rect.top - 12) + 'px';
        ripple.classList.remove('hidden');
        setTimeout(() => ripple.classList.add('hidden'), 900);
      }

      try {
        const res = await fetch('/api/viewport/click', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x_pct, y_pct }),
        });
        const data = await res.json();
        if (data.success) {
          // Refresh screenshot immediately after click
          setTimeout(() => {
            if (img) img.src = '/api/screenshot?t=' + Date.now();
          }, 1000);
        } else {
          console.warn('[Viewport Click]', data.message);
        }
      } catch (err) {
        console.error('[Viewport Click] fetch error:', err);
      }
    });
  })();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();
