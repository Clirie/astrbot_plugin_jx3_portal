const bridge = window.AstrBotPluginView || window.AstrBotPluginPage || null;

const TAB_META = {
  overview: ["概览", "JX3API 与 JX3BOX 运行状态", "JX3 PORTAL"],
  config: ["接口配置", "Token、推栏 Ticket 与数据源参数", "CONFIGURATION"],
  commands: ["指令管理", "开关、冷却与管理员权限", "COMMANDS"],
  aliases: ["区服别名", "把群内简称解析成正式区服名", "SERVER ALIASES"],
  styles: ["名片模板", "名片生图的风格模板与提示词", "CARD STYLES"],
  events: ["事件推送", "JX3API WebSocket 事件通道与目标会话", "EVENT PUSH"],
  paid: ["付费授权", "群聊白名单、到期时间与激活码", "BILLING"],
  logs: ["缓存与日志", "缓存分区、请求记录与错误排查", "OBSERVABILITY"],
  debug: ["接口调试", "选择接口、填写参数并查看响应", "API CONSOLE"],
  system: ["系统信息", "运行环境、统计与配置导出", "SYSTEM"],
};

const state = {
  data: null,
  settings: null,
  commands: [],
  logs: [],
  endpoints: [],
  selectedEndpoint: null,
  activeTab: "overview",
  configDirty: false,
  commandDirty: false,
  health: {
    connect: { status: "idle", message: "尚未检测", elapsed: null },
    token: { status: "idle", message: "尚未检测", elapsed: null },
    ticket: { status: "idle", message: "尚未检测", elapsed: null },
    jx3box: { status: "idle", message: "尚未检测", elapsed: null },
  },
  lastDebugText: "",
  lastExportText: "",
  endpointsLoaded: false,
  tokenTimer: null,
  tokenLoading: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : "0";
}

function formatPercent(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "0%";
}

function formatDuration(ms) {
  const number = Number(ms || 0);
  if (!Number.isFinite(number) || number <= 0) return "—";
  if (number < 1000) return `${Math.round(number)} ms`;
  return `${(number / 1000).toFixed(1)} s`;
}

function formatUptime(seconds) {
  let total = Math.max(0, Number(seconds || 0));
  const days = Math.floor(total / 86400);
  total %= 86400;
  const hours = Math.floor(total / 3600);
  total %= 3600;
  const minutes = Math.floor(total / 60);
  if (days) return `${days}天${hours}时`;
  if (hours) return `${hours}时${minutes}分`;
  return `${minutes}分`;
}

function formatClock(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

function statusClass(status) {
  return status === "ok" ? "is-ok" : status === "bad" ? "is-bad" : status === "warn" ? "is-warn" : "";
}

async function apiGet(path, params = {}) {
  if (!bridge) throw new Error("未检测到 AstrBot 插件桥接，请从 WebUI 插件详情页打开。");
  const result = await bridge.apiGet(path, params);
  if (result && typeof result === "object" && result.status === "error") {
    throw new Error(result.message || "请求失败");
  }
  return result;
}

async function apiPost(path, body = {}) {
  if (!bridge) throw new Error("未检测到 AstrBot 插件桥接，请从 WebUI 插件详情页打开。");
  const result = await bridge.apiPost(path, body);
  if (result && typeof result === "object" && result.status === "error") {
    throw new Error(result.message || "请求失败");
  }
  return result;
}

function toast(message, type = "info") {
  const stack = $("#toastStack");
  if (!stack) return;
  const node = document.createElement("div");
  node.className = `toast ${type === "ok" ? "ok" : type === "bad" ? "bad" : ""}`;
  node.innerHTML = `<span class="toast-icon">${type === "ok" ? "✓" : type === "bad" ? "!" : "i"}</span><span>${esc(message)}</span>`;
  stack.append(node);
  const timer = setTimeout(() => node.remove(), 4600);
  node.addEventListener("click", () => {
    clearTimeout(timer);
    node.remove();
  });
}

async function withBusy(button, task, label = "处理中…") {
  if (!button) return task();
  const previous = button.innerHTML;
  button.disabled = true;
  button.classList.add("is-loading");
  button.textContent = label;
  try {
    return await task();
  } finally {
    button.disabled = false;
    button.classList.remove("is-loading");
    button.innerHTML = previous;
  }
}

function confirmModal({ title, body, okText = "确定", danger = true }) {
  return new Promise((resolve) => {
    const modal = $("#modal");
    const ok = $("#modalOk");
    const cancel = $("#modalCancel");
    $("#modalTitle").textContent = title;
    $("#modalBody").textContent = body;
    ok.textContent = okText;
    ok.className = `btn ${danger ? "danger-solid" : "primary"}`;
    modal.hidden = false;
    ok.focus();

    const finish = (value) => {
      modal.hidden = true;
      ok.removeEventListener("click", onOk);
      cancel.removeEventListener("click", onCancel);
      modal.removeEventListener("click", onBackdrop);
      document.removeEventListener("keydown", onKey);
      resolve(value);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onBackdrop = (event) => {
      if (event.target === modal) finish(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") finish(false);
    };
    ok.addEventListener("click", onOk);
    cancel.addEventListener("click", onCancel);
    modal.addEventListener("click", onBackdrop);
    document.addEventListener("keydown", onKey);
  });
}

/* ------------------------------------------------------------------ boot */
async function init() {
  bindStaticEvents();
  if (!bridge) {
    showFatal("没有检测到 AstrBot 插件视图桥接。请从 AstrBot WebUI 的「插件 → 剑网3百宝箱」打开此页面。");
    return;
  }
  try {
    await Promise.race([
      bridge.ready(),
      new Promise((_, reject) => setTimeout(() => reject(new Error("等待 AstrBot 插件桥接超时")), 8000)),
    ]);
  } catch (error) {
    showFatal(error.message || String(error));
    return;
  }
  await loadBootstrap();
  const requestedTab = new URLSearchParams(window.location.search).get("tab");
  if (requestedTab && TAB_META[requestedTab]) switchTab(requestedTab);
}

function showFatal(message) {
  $("#loading").hidden = true;
  $("#content").hidden = true;
  $("#fatal").hidden = false;
  $("#fatalText").textContent = message;
  setConnection(false, "离线");
}

function setConnection(ok, text) {
  const pill = $("#connPill");
  if (pill) {
    pill.classList.toggle("is-bad", !ok);
    pill.innerHTML = `<span class="dot"></span>${esc(text)}`;
  }
  const side = $("#sideStatus");
  if (side) {
    side.classList.toggle("is-bad", !ok);
    side.innerHTML = `<span class="dot"></span><span>${esc(text)}</span>`;
  }
}

async function loadBootstrap(silent = false) {
  if (!silent) {
    $("#loading").hidden = false;
    $("#content").hidden = true;
    $("#fatal").hidden = true;
  }
  try {
    const data = await apiGet("bootstrap");
    if (!data || !data.settings) throw new Error("后台返回的数据不完整");
    state.data = data;
    state.settings = data.settings;
    state.commands = (data.commands || []).map((item) => ({ ...item }));
    state.logs = data.logs || [];
    state.configDirty = false;
    state.commandDirty = false;
    renderAll();
    $("#loading").hidden = true;
    $("#fatal").hidden = true;
    $("#content").hidden = false;
    setConnection(true, "在线");
    scheduleTokenRefresh();
    refreshTokenStats(false);
  } catch (error) {
    if (!state.data) {
      showFatal(error.message || String(error));
    } else {
      toast(`刷新失败：${error.message || error}`, "bad");
    }
  }
}

function renderAll() {
  if (!state.data) return;
  renderChrome();
  renderOverview();
  renderConfig();
  renderCommands();
  renderAliases();
  renderEvents();
  renderPaid();
  renderCache();
  renderLogs();
  renderSystem();
  renderServerOptions();
  if (state.activeTab === "debug") ensureEndpoints();
}

/* --------------------------------------------------------------- chrome */
function renderChrome() {
  const meta = state.data?.meta || {};
  const settings = state.settings || {};
  const version = meta.version || "1.0.0";
  $("#sideVersion").textContent = `v${version} · ${meta.astrbot_version && meta.astrbot_version !== "—" ? `AstrBot ${meta.astrbot_version}` : "AstrBot"}`;
  $("#pageTitle").textContent = TAB_META[state.activeTab]?.[0] || "概览";
  $("#pageSubtitle").textContent = TAB_META[state.activeTab]?.[1] || "";
  $("#pageKicker").textContent = TAB_META[state.activeTab]?.[2] || "JX3 PORTAL";

  const token = Boolean(settings.jx3api?.token_configured);
  const ticket = Boolean(settings.jx3api?.ticket_configured);
  const summary = [token ? "Token 已配置" : "Token 未配置", ticket ? "Ticket 已配置" : "Ticket 未配置"];
  setConnection(true, summary.join(" · "));
}

function renderServerOptions() {
  const list = $("#serverOptions");
  if (!list) return;
  const servers = state.data?.servers || [];
  list.innerHTML = servers
    .map((item) => `<option value="${esc(item.server)}">${esc(item.server)} · ${esc(item.zone || "")}</option>`)
    .join("");
}

/* -------------------------------------------------------------- overview */
function renderOverview() {
  const data = state.data;
  if (!data) return;
  const settings = state.settings || {};
  const runtime = data.stats?.runtime || {};
  const requests = runtime.requests || {};
  const cache = data.stats?.cache || {};

  const tokenConfigured = Boolean(settings.jx3api?.token_configured);
  const ticketConfigured = Boolean(settings.jx3api?.ticket_configured);

  $("#statRequests").textContent = formatNumber(requests.total);
  $("#statRequestsSub").textContent = `成功 ${formatNumber(requests.ok)} · 失败 ${formatNumber(requests.failed)}`;
  $("#statSuccess").textContent = requests.total ? formatPercent(requests.success_rate) : "—";
  $("#statSuccessSub").textContent = requests.total ? `平均 ${formatDuration(requests.avg_ms)}` : "暂无请求";
  $("#statCache").textContent = cache.hits || cache.misses ? formatPercent(cache.hit_rate) : "—";
  $("#statCacheSub").textContent = `${formatNumber(cache.entries)} 条缓存`;
  $("#statUptime").textContent = formatUptime(runtime.uptime_seconds);
  $("#statUptimeSub").textContent = `启动于 ${formatClock(runtime.started_at)}`;

  renderHealth();
  renderRecentLogs();
  renderOnboarding(tokenConfigured, ticketConfigured);
}

function healthRows() {
  const settings = state.settings || {};
  return [
    {
      key: "connect",
      icon: "◈",
      name: "JX3API 连接",
      detail: "免费接口 /active/calendar",
      configured: true,
    },
    {
      key: "token",
      icon: "钥",
      name: "JX3API Token",
      detail: settings.jx3api?.token_configured ? `已配置 ${settings.jx3api.token_masked}` : "未配置，会员接口不可用",
      configured: Boolean(settings.jx3api?.token_configured),
    },
    {
      key: "ticket",
      icon: "票",
      name: "推栏 Ticket",
      detail: settings.jx3api?.ticket_configured ? `已配置 ${settings.jx3api.ticket_masked}` : "未配置，名剑/名片/门派/资历不可用",
      configured: Boolean(settings.jx3api?.ticket_configured),
    },
    {
      key: "jx3box",
      icon: "盒",
      name: "JX3BOX 魔盒",
      detail: "配装 / 一键宏 / 交易行",
      configured: true,
    },
  ];
}

async function refreshTokenStats(force = true) {
  if (state.tokenLoading || (!force && document.hidden)) return;
  state.tokenLoading = true;
  const button = $("#refreshTokenBtn");
  if (button) button.disabled = true;
  try {
    const result = await apiPost("token/stats", { force: Boolean(force) });
    if (!result?.ok) {
      $("#tokenLevel").textContent = "—";
      $("#tokenUsed").textContent = "—";
      $("#tokenRemaining").textContent = "—";
      $("#tokenValid").textContent = "不可用";
      $("#tokenValid").className = "is-bad";
      $("#tokenUpdated").textContent = result?.message || "读取失败";
      return;
    }
    const stats = result.stats || {};
    const raw = stats.raw || {};
    const level = stats.level ?? raw.level ?? "—";
    const used = stats.used ?? raw.used ?? "—";
    const remaining = stats.remaining ?? raw.remaining ?? "—";
    const valid = stats.valid ?? raw.valid;
    $("#tokenLevel").textContent = level === "—" ? "—" : `LV.${level}`;
    $("#tokenUsed").textContent = used === "—" ? "—" : formatNumber(used);
    $("#tokenRemaining").textContent = remaining === "—" ? "—" : formatNumber(remaining);
    const node = $("#tokenValid");
    if (valid === true) {
      node.textContent = "有效";
      node.className = "is-ok";
    } else if (valid === false) {
      node.textContent = "无效";
      node.className = "is-bad";
    } else {
      node.textContent = "未知";
      node.className = "";
    }
    $("#tokenUpdated").textContent = `最后刷新 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
  } catch (error) {
    $("#tokenValid").textContent = "读取失败";
    $("#tokenValid").className = "is-bad";
    $("#tokenUpdated").textContent = error.message || String(error);
  } finally {
    if (button) button.disabled = false;
    state.tokenLoading = false;
  }
}

function scheduleTokenRefresh() {
  if (state.tokenTimer) {
    clearInterval(state.tokenTimer);
    state.tokenTimer = null;
  }
  if ($("#tokenAutoRefresh")?.checked) {
    state.tokenTimer = setInterval(() => refreshTokenStats(false), 60_000);
  }
}

function renderHealth() {
  const node = $("#healthList");
  if (!node) return;
  node.innerHTML = healthRows()
    .map((row) => {
      const health = state.health[row.key] || { status: "idle", message: "尚未检测" };
      const stateText =
        health.status === "running"
          ? "检测中…"
          : health.status === "ok"
            ? "正常"
            : health.status === "bad"
              ? "异常"
              : health.status === "warn"
                ? "待配置"
                : "未检测";
      const stateClass =
        health.status === "ok" ? "is-ok" : health.status === "bad" ? "is-bad" : health.status === "warn" ? "is-warn" : "";
      return `
        <div class="health-row" data-health-key="${esc(row.key)}">
          <div class="health-icon">${esc(row.icon)}</div>
          <div class="health-body">
            <div class="health-name">${esc(row.name)}</div>
            <div class="health-detail">${esc(health.message || row.detail)}</div>
          </div>
          <div class="health-state ${stateClass}">${stateText}</div>
          <button class="btn tiny ghost" type="button" data-test="${esc(row.key)}" ${health.status === "running" ? "disabled" : ""}>检测</button>
        </div>`;
    })
    .join("");
}

function renderRecentLogs() {
  const node = $("#recentLogs");
  if (!node) return;
  const logs = (state.data?.logs || []).slice(0, 8);
  if (!logs.length) {
    node.innerHTML = `<div class="empty">暂无请求记录</div>`;
    return;
  }
  node.innerHTML = logs
    .map((log) => {
      const dot = log.level === "error" ? "error" : log.level === "warn" ? "warn" : "ok";
      return `
        <div class="activity-row">
          <span class="dot-mark ${dot}"></span>
          <span class="activity-time">${esc(formatClock(log.time))}</span>
          <span class="activity-text" title="${esc(log.message)}">${esc(log.message)}</span>
          <span class="tag">${esc(log.source)}</span>
        </div>`;
    })
    .join("");
}

function renderOnboarding(tokenConfigured, ticketConfigured) {
  $("#onboarding").hidden = tokenConfigured && ticketConfigured && Boolean(state.settings?.admin?.default_server);
  const steps = [
    {
      done: tokenConfigured,
      title: "填写 JX3API Token",
      desc: tokenConfigured ? "已配置，可以调用会员接口。" : "LV.1 / LV.2 接口需要，免费接口可跳过。",
    },
    {
      done: ticketConfigured,
      title: "填写推栏 Ticket",
      desc: ticketConfigured ? "已配置，名剑 / 名片 / 门派 / 资历可用。" : "需要推栏数据时再填，会过期。",
    },
    {
      done: Boolean(state.settings?.admin?.default_server),
      title: "设置默认区服",
      desc: state.settings?.admin?.default_server
        ? `当前默认：${state.settings.admin.default_server}`
        : "填写后可省略指令里的区服参数。",
    },
  ];
  $("#onboardingSteps").innerHTML = steps
    .map(
      (step, index) => `
      <div class="step ${step.done ? "done" : ""}">
        <div class="step-index">${step.done ? "✓" : index + 1}</div>
        <div>
          <div class="step-title">${esc(step.title)}</div>
          <div class="step-desc">${esc(step.desc)}</div>
        </div>
      </div>`,
    )
    .join("");
}

/* ---------------------------------------------------------------- config */
function getSetting(path) {
  return path.split(".").reduce((value, key) => (value && typeof value === "object" ? value[key] : undefined), state.settings);
}

function secretInfo(path) {
  const settings = state.settings || {};
  if (path === "jx3api.token") {
    return { ...settings.jx3api, maskedKey: "token_masked", configuredKey: "token_configured", lengthKey: "token_length", placeholder: "粘贴 JX3API Token" };
  }
  if (path === "jx3api.ticket") {
    return { ...settings.jx3api, maskedKey: "ticket_masked", configuredKey: "ticket_configured", lengthKey: "ticket_length", placeholder: "粘贴 ticket=... 后的值，或整段 Cookie" };
  }
  if (path === "online.token") {
    return { ...settings.online, maskedKey: "token_masked", configuredKey: "token_configured", lengthKey: "token_length", placeholder: "第三方在线服务的 token" };
  }
  if (path === "event_push.token") {
    const group = settings.event_push || {};
    return {
      ...group,
      maskedKey: "token_masked",
      configuredKey: "token_configured",
      lengthKey: null,
      placeholder: group.token_fallback
        ? `留空复用 JX3API Token（${group.effective_token_masked || "未配置"}）`
        : "留空自动复用 JX3API Token",
    };
  }
  if (path === "doubao.api_key") {
    return { ...settings.doubao, maskedKey: "key_masked", configuredKey: "key_configured", lengthKey: "key_length", placeholder: "火山方舟 API Key" };
  }
  return null;
}

function renderConfig() {
  const settings = state.settings;
  if (!settings) return;
  $$("[data-setting]").forEach((input) => {
    const path = input.dataset.setting;
    const field = path.split(".").pop();
    const secret = secretInfo(path);
    if (secret) {
      input.value = "";
      const configured = Boolean(secret[secret.configuredKey]);
      input.placeholder = configured
        ? `已配置 ${secret[secret.maskedKey] || "****"}，留空表示不修改`
        : secret.placeholder;
      return;
    }
    const value = getSetting(path);
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (value !== undefined && value !== null) {
      input.value = Array.isArray(value) ? value.join("\n") : value;
    }
  });

  const token = settings.jx3api || {};
  $("#tokenHint").textContent = token.token_configured
    ? `已配置（${token.token_masked}，${token.token_length} 位）。留空保存不会修改。`
    : "未配置。LV.0 免费接口仍可使用。";
  $("#ticketState").textContent = token.ticket_configured ? "已配置" : "未配置";
  $("#ticketState").classList.toggle("is-ok", Boolean(token.ticket_configured));
  $("#ticketHint").textContent = token.ticket_configured
    ? `已配置（${token.ticket_masked}，${token.ticket_length} 位）。Ticket 过期后重新抓包即可。`
    : "Ticket 与 JX3API Token 不同，名剑 / 名片 / 门派 / 资历等接口需要它。";

  const online = settings.online || {};
  $("#onlineTokenState").textContent = online.token_configured ? "已配置" : "未配置";
  $("#onlineTokenState").classList.toggle("is-ok", Boolean(online.token_configured));
  $("#onlineTokenHint").textContent = online.token_configured
    ? `已配置（${online.token_masked}）。这是第三方服务令牌，不是 JX3API Token。`
    : "该令牌与 JX3API Token 不同，由第三方在线服务提供。";

  const event = settings.event_push || {};
  $("#eventTokenState").textContent = event.token_configured
    ? "已配置独立令牌"
    : event.token_fallback
      ? "复用 JX3API Token"
      : "未配置";
  $("#eventTokenState").classList.toggle("is-ok", Boolean(event.token_configured || event.token_fallback));
  $("#eventTokenHint").textContent = event.token_configured
    ? `已配置（${event.token_masked}）。留空保存不会修改。`
    : event.token_fallback
      ? `当前复用 JX3API Token（${event.effective_token_masked}）；也可以填写独立事件令牌覆盖。`
      : "未配置；留空时将使用 JX3API Token。";

  const doubao = settings.doubao || {};
  $("#doubaoKeyHint").textContent = doubao.key_configured
    ? `已配置（${doubao.key_masked}，${doubao.key_length} 位）。留空保存不会修改。`
    : "未配置。填写后才能使用「生图」「图生图」。";

  state.configDirty = false;
  setConfigDirty(false);
}

function setConfigDirty(dirty) {
  state.configDirty = dirty;
  const node = $("#configDirty");
  if (!node) return;
  node.textContent = dirty ? "有未保存的修改" : "所有修改需点击保存";
  node.classList.toggle("is-dirty", dirty);
}

function collectSettings() {
  const payload = {};
  const secretFields = new Set(["token", "ticket", "api_key"]);
  $$("[data-setting]").forEach((input) => {
    const [group, field] = input.dataset.setting.split(".");
    if (!group || !field) return;
    if (!payload[group]) payload[group] = {};
    if (secretFields.has(field)) {
      const value = input.value.trim();
      if (value) payload[group][field] = value;
      return;
    }
    if (input.type === "checkbox") {
      payload[group][field] = Boolean(input.checked);
      return;
    }
    if (input.type === "number") {
      payload[group][field] = Number(input.value);
    } else {
      payload[group][field] = input.value;
    }
  });
  const actionBoxes = $$("[data-event-action]");
  if (actionBoxes.length) {
    payload.event_push = payload.event_push || {};
    payload.event_push.actions = actionBoxes
      .filter((box) => box.checked)
      .map((box) => Number(box.dataset.eventAction))
      .filter((value) => Number.isFinite(value));
  }
  return payload;
}

async function saveConfig(button, options = {}) {
  await withBusy(button, async () => {
    try {
      const result = await apiPost("settings/save", collectSettings());
      if (result?.settings) {
        state.settings = result.settings;
        state.data.settings = result.settings;
      }
      state.configDirty = false;
      renderConfig();
      renderOverview();
      renderChrome();
      renderEvents();
      renderPaid();
      if (options.reloadEvents || state.activeTab === "events") {
        try {
          const reload = await apiPost("events/reload", {});
          if (reload?.status) {
            state.data.events = reload;
            renderEvents();
          }
        } catch (error) {
          toast(`事件通道重连失败：${error.message || error}`, "bad");
        }
      }
      toast(result?.message || "配置已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

async function clearSecret(field) {
  const labels = {
    jx3api_token: "JX3API Token",
    jx3api_ticket: "推栏 Ticket",
    online_api_token: "在线查询令牌",
    event_push_token: "事件推送独立令牌",
    doubao_api_key: "豆包 API Key",
  };
  const label = labels[field] || field;
  const ok = await confirmModal({
    title: `清除 ${label}`,
    body: `确定清除已保存的 ${label} 吗？清除后相关接口会立即失效。`,
    okText: "清除",
  });
  if (!ok) return;
  try {
    const result = await apiPost("settings/secret/clear", { field });
    if (result?.settings) {
      state.settings = result.settings;
      state.data.settings = result.settings;
    }
    renderConfig();
    renderOverview();
    renderChrome();
    toast(result?.message || "已清除", "ok");
  } catch (error) {
    toast(`清除失败：${error.message || error}`, "bad");
  }
}

async function runTest(target, button) {
  // Tests use the persisted config. Save the current form first so a freshly
  // pasted token/ticket is actually what gets tested.
  if (state.configDirty) {
    try {
      const saved = await apiPost("settings/save", collectSettings());
      if (saved?.settings) {
        state.settings = saved.settings;
        state.data.settings = saved.settings;
      }
      state.configDirty = false;
      renderConfig();
    } catch (error) {
      toast(`保存配置失败，无法测试：${error.message || error}`, "bad");
      return;
    }
  }
  const keys = target === "all" ? ["connect", "token", "ticket", "jx3box"] : [target];
  for (const key of keys) {
    state.health[key] = { status: "running", message: "正在检测…", elapsed: null };
  }
  renderHealth();
  try {
    const payload = { target };
    if (target === "online") {
      payload.server = ($("#onlineTestServer")?.value || "").trim();
      payload.name = ($("#onlineTestName")?.value || "").trim();
    }
    const result = await apiPost("test", payload);
    if (target === "all" && Array.isArray(result?.checks)) {
      for (const check of result.checks) {
        state.health[check.target] = {
          status: check.ok ? "ok" : "bad",
          message: check.message || (check.ok ? "正常" : "检测失败"),
          elapsed: check.elapsed_ms,
        };
      }
      toast(result.ok ? "全部连接正常" : "部分连接异常，请查看详情", result.ok ? "ok" : "bad");
    } else {
      const key = target === "jx3box" ? "jx3box" : target;
      state.health[key] = {
        status: result.ok ? "ok" : "bad",
        message: result.message || (result.ok ? "正常" : "检测失败"),
        elapsed: result.elapsed_ms,
      };
      let detail = "";
      if (result.upstream) {
        detail = typeof result.upstream === "object"
          ? `（上游 ${result.upstream.code || ""} ${result.upstream.message || ""}）`
          : `（上游 ${String(result.upstream).slice(0, 120)}）`;
      }
      toast(
        (result.ok ? result.message || "检测通过" : result.message || "检测失败") + detail,
        result.ok ? "ok" : "bad",
      );
    }
  } catch (error) {
    for (const key of keys) {
      state.health[key] = { status: "bad", message: error.message || String(error), elapsed: null };
    }
    toast(`检测失败：${error.message || error}`, "bad");
  }
  renderHealth();
  $("#heroNote").textContent = `检测完成 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
}

/* -------------------------------------------------------------- commands */
function renderCommands() {
  const node = $("#commandRows");
  if (!node) return;
  const categories = [...new Set(state.commands.map((item) => item.category))];
  const select = $("#commandCategory");
  const current = select.value || "all";
  select.innerHTML =
    `<option value="all">全部分类</option>` +
    categories.map((category) => `<option value="${esc(category)}">${esc(category)}</option>`).join("");
  select.value = categories.includes(current) ? current : "all";

  const search = ($("#commandSearch").value || "").trim().toLowerCase();
  const category = select.value;
  const filtered = state.commands.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (!search) return true;
    return `${item.name} ${item.key} ${item.aliases.join(" ")} ${item.description}`
      .toLowerCase()
      .includes(search);
  });

  $("#commandCount").textContent = `${filtered.length} / ${state.commands.length} 个指令`;
  if (!filtered.length) {
    node.innerHTML = `<tr><td colspan="5"><div class="empty">没有匹配的指令</div></td></tr>`;
    return;
  }
  node.innerHTML = filtered
    .map(
      (item) => `
      <tr data-key="${esc(item.key)}">
        <td>
          <label class="switch" title="${item.enabled ? "已启用" : "已关闭"}">
            <input type="checkbox" data-command-enabled ${item.enabled ? "checked" : ""} />
            <span></span>
          </label>
        </td>
        <td>
          <div class="command-name">
            <strong>${esc(item.name)}</strong>
            ${item.paid ? '<span class="tag green">付费</span>' : ""}
            ${item.admin_only ? '<span class="tag cyan">管理员</span>' : ""}
            ${item.available === false ? '<span class="tag">未配置</span>' : ""}
            <span class="tag violet">${esc(item.category)}</span>
          </div>
          <div class="command-aliases">${esc(item.aliases.length ? item.aliases.join(" · ") : item.key)}</div>
        </td>
        <td>
          <div class="primary-cell">${esc(item.description)}</div>
          <div class="command-aliases">${esc(item.usage)}</div>
        </td>
        <td>
          <select class="permission-select" data-command-permission>
            <option value="all" ${item.permission === "all" ? "selected" : ""}>所有人</option>
            <option value="admin" ${item.permission === "admin" ? "selected" : ""}>管理员</option>
          </select>
        </td>
        <td>
          <input class="cooldown-input" type="number" min="0" max="3600" step="1" value="${Number(item.cooldown) || 0}" data-command-cooldown />
        </td>
      </tr>`,
    )
    .join("");
}

function markCommandDirty() {
  state.commandDirty = true;
  const node = $("#commandDirty");
  if (node) {
    node.textContent = "有未保存的修改";
    node.classList.add("is-dirty");
  }
}

function updateCommandFromRow(row) {
  const key = row.dataset.key;
  const item = state.commands.find((command) => command.key === key);
  if (!item) return;
  const enabled = row.querySelector("[data-command-enabled]");
  const permission = row.querySelector("[data-command-permission]");
  const cooldown = row.querySelector("[data-command-cooldown]");
  if (enabled) item.enabled = enabled.checked;
  if (permission) item.permission = permission.value;
  if (cooldown) item.cooldown = Math.max(0, Math.min(3600, Number(cooldown.value) || 0));
}

async function saveCommands(button) {
  await withBusy(button, async () => {
    try {
      const payload = {
        disabled: state.commands.filter((item) => !item.enabled).map((item) => item.key),
        cooldowns: Object.fromEntries(state.commands.map((item) => [item.key, Number(item.cooldown) || 0])),
        permissions: Object.fromEntries(state.commands.map((item) => [item.key, item.permission])),
      };
      const result = await apiPost("commands/save", payload);
      if (Array.isArray(result?.commands)) {
        state.commands = result.commands.map((item) => ({ ...item }));
        state.data.commands = result.commands;
      }
      state.commandDirty = false;
      const node = $("#commandDirty");
      if (node) {
        node.textContent = "修改后需保存";
        node.classList.remove("is-dirty");
      }
      renderCommands();
      toast(result?.message || "指令配置已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

/* --------------------------------------------------------------- aliases */
function renderAliases() {
  const data = state.data?.aliases;
  if (!data) return;
  const rows = data.rows || [];
  $("#aliasRows").innerHTML = rows
    .map(
      (row) => `
      <tr>
        <td class="primary-cell">${esc(row.server)}</td>
        <td>${esc(row.zone || "—")}</td>
        <td>
          <input class="alias-input" type="text" data-alias-server="${esc(row.server)}" value="${esc((row.aliases || []).join(", "))}" placeholder="例如：双梦, 电五" />
        </td>
      </tr>`,
    )
    .join("");
  const select = $("#aliasServer");
  if (select) {
    const current = select.value;
    select.innerHTML = rows
      .map((row) => `<option value="${esc(row.server)}">${esc(row.server)}${row.zone ? ` · ${esc(row.zone)}` : ""}</option>`)
      .join("");
    if (rows.some((row) => row.server === current)) select.value = current;
  }
  $("#aliasDirty").textContent = "修改后点击保存";
  $("#aliasDirty").classList.remove("is-dirty");
  const defaultInput = $("#aliasDefaultServer");
  if (defaultInput) defaultInput.value = state.settings?.admin?.default_server || "";
}

function collectAliases() {
  return $$("[data-alias-server]").map((input) => ({
    server: input.dataset.aliasServer,
    aliases: input.value
      .split(/[,，;；]/)
      .map((item) => item.trim())
      .filter(Boolean),
  }));
}

async function saveAliases(button) {
  await withBusy(button, async () => {
    try {
      const result = await apiPost("aliases/save", { rows: collectAliases() });
      if (result?.rows) {
        state.data.aliases = result;
        renderAliases();
      }
      const defaultServer = (
        $('[data-setting="admin.default_server"]')?.value ||
        $("#aliasDefaultServer")?.value ||
        ""
      ).trim();
      const savedSettings = await apiPost("settings/save", {
        admin: { default_server: defaultServer },
      });
      if (savedSettings?.settings) {
        state.settings = savedSettings.settings;
        state.data.settings = savedSettings.settings;
      }
      toast(result?.message || "区服别名已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

async function loadAliases() {
  try {
    const data = await apiGet("aliases/summary", {});
    if (data?.rows) {
      state.data.aliases = data;
      renderAliases();
    }
  } catch (error) {
    toast(`读取区服别名失败：${error.message || error}`, "bad");
  }
}

/* --------------------------------------------------------------- events */
async function loadEventsSummary() {
  try {
    const data = await apiGet("events/summary", {});
    if (data?.status) {
      state.data.events = data;
      if (data.settings) state.settings.event_push = data.settings;
      renderEvents();
    }
  } catch (error) {
    toast(`读取事件状态失败：${error.message || error}`, "bad");
  }
}

function renderEvents() {
  const node = $("#eventActionGrid");
  if (!node) return;
  const events = state.data?.events || {};
  const status = events.status || {};
  const selected = new Set(state.settings?.event_push?.actions || []);

  const statusText = !status.enabled
    ? "后台未开启事件推送"
    : status.connected
      ? `已连接 · 已接收 ${formatNumber(status.received)} 条事件`
      : status.last_error
        ? `未连接：${status.last_error}`
        : "已启用，等待连接…";
  $("#eventStatStatus").textContent = status.connected ? "已连接" : status.enabled ? "等待中" : "已关闭";
  $("#eventStatStatusSub").textContent = statusText;
  $("#eventStatusText").textContent = statusText;
  $("#eventStatActions").textContent = formatNumber(selected.size);
  $("#eventStatSessions").textContent = formatNumber((state.settings?.event_push?.sessions || []).length);
  $("#eventDirty").textContent = "修改后点击保存并重连";
  $("#eventDirty").classList.remove("is-dirty");

  const catalog = events.catalog || { free: [], paid: [] };
  const row = (item, isFree) => {
    const action = Number(item.action);
    return `
      <tr>
        <td>
          <label class="switch" title="${selected.has(action) ? "已订阅" : "未订阅"}">
            <input type="checkbox" data-event-action="${action}" ${selected.has(action) ? "checked" : ""} />
            <span></span>
          </label>
        </td>
        <td><code>${action}</code></td>
        <td class="primary-cell">${esc(item.name)}</td>
        <td>
          <span class="tag violet">${esc(item.interface || "—")}</span>
          <div class="command-aliases">${esc(item.endpoint || "")}</div>
        </td>
        <td>${isFree ? '<span class="tag green">免费</span>' : '<span class="tag cyan">令牌</span>'}</td>
      </tr>`;
  };
  const freeRows = (catalog.free || []).map((item) => row(item, true)).join("");
  const paidRows = (catalog.paid || []).map((item) => row(item, false)).join("");
  node.innerHTML =
    `<tr class="event-group-row"><td colspan="5">免费事件（2001~2006，不消耗令牌事件权限）</td></tr>` +
    (freeRows || `<tr><td colspan="5"><div class="empty">暂无</div></td></tr>`) +
    `<tr class="event-group-row"><td colspan="5">令牌事件（需要有效 JX3API Token；付费闸门开启时只推送给授权群）</td></tr>` +
    (paidRows || `<tr><td colspan="5"><div class="empty">暂无</div></td></tr>`);
  renderEventSession();
}

function renderEventSession() {
  const events = state.data?.events || {};
  const statuses = events.session_status || {};
  const sessions = Object.keys(statuses);
  const select = $("#eventSessionSelect");
  if (!select) return;
  const current = select.value;
  select.innerHTML = sessions.length
    ? sessions.map((session) => `<option value="${esc(session)}">${esc(session)}</option>`).join("")
    : `<option value="">暂无会话</option>`;
  if (sessions.includes(current)) select.value = current;
  const session = select.value;
  const rows = statuses[session] || [];
  $("#eventSessionRows").innerHTML = rows.length
    ? rows
        .map(
          (item) => `
          <tr>
            <td>
              <label class="switch"><input type="checkbox" data-session-action="${item.action}" ${item.enabled ? "checked" : ""} /><span></span></label>
            </td>
            <td><code>${item.action}</code></td>
            <td class="primary-cell">${esc(item.name)}</td>
            <td>${item.free ? '<span class="tag green">免费</span>' : '<span class="tag cyan">令牌</span>'}</td>
          </tr>`,
        )
        .join("")
    : `<tr><td colspan="4"><div class="empty">暂无会话，先在群里发送「推送 开启」或在上方添加目标会话</div></td></tr>`;
}

async function saveEventSession(button) {
  const session = $("#eventSessionSelect")?.value;
  if (!session) {
    toast("请先选择会话", "bad");
    return;
  }
  const actions = $$("[data-session-action]")
    .filter((node) => node.checked)
    .map((node) => Number(node.dataset.sessionAction));
  await withBusy(button, async () => {
    try {
      const result = await apiPost("events/session/save", {
        session_id: session,
        actions,
      });
      if (result?.status) {
        state.data.events = result;
        renderEvents();
      }
      toast(result?.message || "会话订阅已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

/* ----------------------------------------------------------------- paid */
function renderPaid() {
  const paid = state.data?.paid;
  if (!paid) return;
  const stats = paid.stats || {};
  $("#paidGroupCount").textContent = formatNumber(stats.groups);
  $("#paidGroupSub").textContent = `有效 ${formatNumber(stats.active_groups)} · 过期 ${formatNumber(stats.expired_groups)}`;
  $("#paidActiveCount").textContent = formatNumber(stats.active_groups);
  $("#paidUnusedCodes").textContent = formatNumber(stats.unused_codes);

  const groupRows = paid.groups || [];
  $("#paidGroupRows").innerHTML = groupRows.length
    ? groupRows
        .map((item) => {
          const stateText = item.valid ? "有效" : item.reason === "expired" ? "已过期" : "已停用";
          const stateCls = item.valid ? "green" : item.reason === "expired" ? "" : "violet";
          const remaining = item.valid ? `剩余 ${Math.ceil((item.remaining_seconds || 0) / 86400)} 天` : "";
          return `
            <tr>
              <td class="primary-cell">${esc(item.session_id)}</td>
              <td>${esc(item.note || "—")}</td>
              <td>${esc(item.expires ? formatDateTime(item.expires) : "—")}<div class="command-aliases">${esc(remaining)}</div></td>
              <td><span class="tag ${stateCls}">${stateText}</span></td>
              <td>
                <div class="head-actions">
                  <button class="btn tiny ghost" type="button" data-paid-action="extend" data-session="${esc(item.session_id)}">+30 天</button>
                  <button class="btn tiny ghost" type="button" data-paid-action="toggle" data-session="${esc(item.session_id)}" data-active="${item.active ? "0" : "1"}">${item.active ? "停用" : "启用"}</button>
                  <button class="btn tiny danger" type="button" data-paid-action="delete" data-session="${esc(item.session_id)}">删除</button>
                </div>
              </td>
            </tr>`;
        })
        .join("")
    : `<tr><td colspan="5"><div class="empty">还没有授权群聊</div></td></tr>`;

  const codes = paid.codes || [];
  $("#paidCodeRows").innerHTML = codes.length
    ? codes
        .map(
          (item) => `
          <tr>
            <td class="primary-cell">${esc(item.code)}</td>
            <td>${formatNumber(item.days)} 天</td>
            <td>${item.used ? '<span class="tag">已使用</span>' : '<span class="tag green">未使用</span>'}</td>
            <td>${esc(item.used_session || "—")}</td>
            <td>${esc(item.created_at ? formatDateTime(item.created_at) : "—")}</td>
            <td>
              <div class="head-actions">
                <button class="btn tiny ghost" type="button" data-paid-action="copy" data-code="${esc(item.code)}">复制</button>
                <button class="btn tiny danger" type="button" data-paid-action="delete-code" data-code="${esc(item.code)}">删除</button>
              </div>
            </td>
          </tr>`,
        )
        .join("")
    : `<tr><td colspan="6"><div class="empty">还没有激活码</div></td></tr>`;

  const expires = $("#paidGroupExpires");
  if (expires && !expires.value) {
    const date = new Date();
    date.setDate(date.getDate() + 30);
    const local = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
    expires.value = local;
  }
}

async function refreshPaid() {
  try {
    const data = await apiGet("paid/summary", {});
    if (data && data.groups) {
      state.data.paid = data;
      renderPaid();
    }
  } catch (error) {
    toast(`刷新授权失败：${error.message || error}`, "bad");
  }
}

async function savePaidGroup(button) {
  const sessionId = ($("#paidGroupSession").value || "").trim();
  if (!sessionId) {
    toast("请填写会话 ID", "bad");
    return;
  }
  await withBusy(button, async () => {
    try {
      const result = await apiPost("paid/groups/save", {
        session_id: sessionId,
        note: ($("#paidGroupNote").value || "").trim(),
        expires_at: $("#paidGroupExpires").value,
        active: $("#paidGroupActive").checked,
      });
      if (result?.groups) {
        state.data.paid = result;
        renderPaid();
      }
      toast(result?.message || "授权已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

async function generateCodes(button) {
  await withBusy(button, async () => {
    try {
      const result = await apiPost("paid/codes/generate", {
        days: Number($("#paidCodeDays").value) || 30,
        count: Number($("#paidCodeCount").value) || 1,
        note: ($("#paidCodeNote").value || "").trim(),
      });
      if (result?.groups) {
        state.data.paid = result;
        renderPaid();
      }
      toast(result?.message || "激活码已生成", "ok");
    } catch (error) {
      toast(`生成失败：${error.message || error}`, "bad");
    }
  }, "生成中…");
}

async function savePaidMode(button) {
  await withBusy(button, async () => {
    try {
      const result = await apiPost("settings/save", {
        paid: { enabled: Boolean($('[data-setting="paid.enabled"]').checked) },
      });
      if (result?.settings) {
        state.settings = result.settings;
        state.data.settings = result.settings;
      }
      renderConfig();
      renderPaid();
      toast(result?.message || "付费模式已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

/* ------------------------------------------------------------ cache/logs */
function renderCache() {
  const cache = state.data?.stats?.cache || {};
  $("#cacheEntries").textContent = formatNumber(cache.entries);
  $("#cacheLimit").textContent = `上限 ${formatNumber(cache.max_entries)}`;
  $("#cacheHitRate").textContent = cache.hits || cache.misses ? formatPercent(cache.hit_rate) : "—";
  $("#cacheHits").textContent = `命中 ${formatNumber(cache.hits)} / 未命中 ${formatNumber(cache.misses)}`;
  $("#logCount").textContent = formatNumber(state.data?.stats?.runtime?.log_count || state.logs.length);

  const rows = Object.entries(cache.namespaces || {});
  $("#cacheRows").innerHTML = rows.length
    ? rows
        .map(
          ([name, stat]) => `
          <tr>
            <td class="primary-cell">${esc(name)}</td>
            <td>${formatNumber(stat.entries)}</td>
            <td>${formatNumber(stat.hits)}</td>
            <td>${formatNumber(stat.misses)}</td>
            <td>${formatPercent(stat.hit_rate)}</td>
          </tr>`,
        )
        .join("")
    : `<tr><td colspan="5"><div class="empty">缓存为空</div></td></tr>`;
}

function renderLogs() {
  const node = $("#logRows");
  if (!node) return;
  $("#logResultCount").textContent = `${state.logs.length} 条`;
  if (!state.logs.length) {
    node.innerHTML = `<tr><td colspan="5"><div class="empty">没有日志</div></td></tr>`;
    return;
  }
  node.innerHTML = state.logs
    .map(
      (log) => `
      <tr>
        <td>${esc(formatDateTime(log.time))}</td>
        <td><span class="level-badge ${esc(log.level)}">${esc(log.level)}</span></td>
        <td><span class="source-pill">${esc(log.source)}</span></td>
        <td title="${esc(log.message)}">${esc(log.message)}</td>
        <td>${log.duration_ms != null ? esc(formatDuration(log.duration_ms)) : "—"}</td>
      </tr>`,
    )
    .join("");
}

async function loadLogs() {
  const params = {
    limit: 120,
    level: $("#logLevel")?.value || "all",
    q: $("#logSearch")?.value || "",
  };
  try {
    const result = await apiGet("logs", params);
    state.logs = result.logs || [];
    renderLogs();
    $("#logCount").textContent = formatNumber(state.data?.stats?.runtime?.log_count || state.logs.length);
  } catch (error) {
    toast(`读取日志失败：${error.message || error}`, "bad");
  }
}

async function clearCache(scope) {
  if (scope === "all") {
    const ok = await confirmModal({
      title: "清空全部缓存",
      body: "将清空 JX3API 与 JX3BOX 的所有本地缓存，下一次查询会重新请求上游。",
      okText: "清空",
    });
    if (!ok) return;
  }
  try {
    const result = await apiPost("cache/clear", { scope });
    if (result?.cache) state.data.stats.cache = result.cache;
    renderCache();
    toast(result?.message || "缓存已清理", "ok");
  } catch (error) {
    toast(`清理失败：${error.message || error}`, "bad");
  }
}

async function clearLogs() {
  const ok = await confirmModal({
    title: "清空日志",
    body: "确定清空当前内存中的所有请求日志吗？统计数字不会重置。",
    okText: "清空",
  });
  if (!ok) return;
  try {
    const result = await apiPost("logs/clear", {});
    state.logs = [];
    state.data.logs = [];
    renderLogs();
    renderRecentLogs();
    toast(result?.message || "日志已清空", "ok");
  } catch (error) {
    toast(`清空失败：${error.message || error}`, "bad");
  }
}

/* ---------------------------------------------------------------- debug */
async function ensureEndpoints() {
  if (state.endpointsLoaded && state.endpoints.length) {
    renderEndpointList();
    return;
  }
  try {
    const result = await apiGet("endpoints", {});
    state.endpoints = result.items || [];
    state.endpointsLoaded = true;
    $("#endpointTotal").textContent = `${result.total || state.endpoints.length} 个 JX3API 接口`;
    renderEndpointList();
  } catch (error) {
    $("#endpointList").innerHTML = `<div class="empty">接口目录加载失败：${esc(error.message || error)}</div>`;
  }
}

function endpointMatches(item, query) {
  if (!query) return true;
  const text = `${item.path} ${item.summary} ${item.category}`.toLowerCase();
  return text.includes(query);
}

function renderEndpointList() {
  const node = $("#endpointList");
  if (!node) return;
  const query = ($("#endpointSearch")?.value || "").trim().toLowerCase();
  const items = state.endpoints.filter((item) => endpointMatches(item, query)).slice(0, 120);
  if (!items.length) {
    node.innerHTML = `<div class="empty">没有匹配的接口</div>`;
    return;
  }
  node.innerHTML = items
    .map((item) => {
      const active = state.selectedEndpoint?.path === item.path ? "is-active" : "";
      return `
        <button class="endpoint-item ${active}" type="button" data-path="${esc(item.path)}">
          <span class="endpoint-item-body">
            <span class="endpoint-item-title">${esc(item.summary)}</span>
            <span class="endpoint-item-path">${esc(item.path)}</span>
          </span>
          <span class="endpoint-item-tags">
            <span class="mini-tag lv${Number(item.level) || 0}">L${Number(item.level) || 0}</span>
            ${item.ticket ? '<span class="mini-tag ticket">T</span>' : ""}
          </span>
        </button>`;
    })
    .join("");

  if (!state.selectedEndpoint && items.length) {
    selectEndpoint(items[0]);
  }
}

function selectEndpoint(item, { keepPath = false } = {}) {
  state.selectedEndpoint = item || null;
  if (!item) {
    $("#endpointMeta").innerHTML = "";
    $("#paramFields").innerHTML = "";
    return;
  }
  if (!keepPath) $("#debugPath").value = item.path;
  $$(".endpoint-item").forEach((node) => {
    node.classList.toggle("is-active", node.dataset.path === item.path);
  });

  $("#endpointMeta").innerHTML = `
    <span class="tag violet">${esc(item.category)}</span>
    <span class="tag ${item.level > 0 ? "cyan" : "green"}">LV.${Number(item.level) || 0}</span>
    ${item.ticket ? '<span class="tag cyan">需要推栏 Ticket</span>' : ""}
    <span>${esc(item.summary)}</span>
    <span class="tag">${item.params.length} 个参数</span>`;

  if (!item.params.length) {
    $("#paramFields").innerHTML = `<div class="empty" style="grid-column: 1 / -1">该接口没有参数</div>`;
    return;
  }
  $("#paramFields").innerHTML = item.params
    .map((param) => {
      const type = param.type === "integer" || param.type === "number" ? "number" : "text";
      return `
        <label class="field">
          <span class="field-label">${esc(param.name)} ${param.required ? '<span class="tag cyan">必填</span>' : ""}</span>
          <input type="${type}" data-param="${esc(param.name)}" placeholder="${esc(param.description || param.type)}" />
          <span class="field-hint">${esc(param.type)}${param.required ? " · 必填" : " · 可选"}</span>
        </label>`;
    })
    .join("");
}

async function sendDebug(button) {
  const path = ($("#debugPath").value || "").trim();
  if (!path) {
    toast("请先填写接口路径", "bad");
    return;
  }
  const params = {};
  $$("#paramFields [data-param]").forEach((input) => {
    const value = input.value.trim();
    if (value) params[input.dataset.param] = value;
  });
  await withBusy(button, async () => {
    $("#debugResponse").textContent = "请求中…";
    $("#debugStatus").textContent = "请求中";
    try {
      const result = await apiPost("debug/request", {
        path,
        auth: $("#debugAuth").value,
        params,
      });
      if (result?.ok) {
        const text = result.preview || JSON.stringify(result.data, null, 2);
        state.lastDebugText = text;
        $("#debugResponse").textContent = text;
        $("#debugStatus").textContent = `200 · ${formatDuration(result.elapsed_ms)}`;
      } else {
        const payload = {
          message: result?.message || "请求失败",
          upstream: result?.upstream || undefined,
        };
        const text = JSON.stringify(payload, null, 2);
        state.lastDebugText = text;
        $("#debugResponse").textContent = text;
        $("#debugStatus").textContent = `失败 · ${formatDuration(result?.elapsed_ms)}`;
      }
    } catch (error) {
      const text = JSON.stringify({ message: error.message || String(error) }, null, 2);
      state.lastDebugText = text;
      $("#debugResponse").textContent = text;
      $("#debugStatus").textContent = "请求失败";
    }
  }, "发送中…");
}

async function copyText(text, label = "已复制") {
  if (!text) {
    toast("没有可复制的内容", "bad");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    toast(label, "ok");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    toast(label, "ok");
  }
}

/* ---------------------------------------------------------------- system */
function renderSystem() {
  const meta = state.data?.meta || {};
  const stats = state.data?.stats?.runtime || {};
  const cache = state.data?.stats?.cache || {};
  const settings = state.settings || {};
  const info = [
    ["插件版本", `v${meta.version || "1.0.0"}`],
    ["AstrBot", meta.astrbot_version || "—"],
    ["Python", meta.python || "—"],
    ["平台", meta.platform || "—"],
    ["运行时长", formatUptime(stats.uptime_seconds)],
    ["启动时间", formatDateTime(stats.started_at)],
    ["数据目录", meta.data_dir || "—"],
    ["接口目录", `${meta.endpoint_count || 0} 个 / ${meta.endpoint_categories || 0} 类`],
    ["指令入口", `${meta.command_count || 0} 个`],
    ["心法 / 区服", `${meta.kungfu_count || 0} / ${meta.server_count || 0}`],
    ["默认区服", settings.admin?.default_server || "未设置"],
    ["JX3API", settings.jx3api?.base_url || "—"],
    ["事件推送", state.data.events?.status?.connected ? "已连接" : state.data.events?.status?.enabled ? "等待连接" : "未开启"],
    ["付费授权", state.data.paid?.enabled ? `已开启 · ${state.data.paid?.stats?.active_groups || 0} 个有效群` : "未开启"],
    ["豆包生图", settings.doubao?.enabled ? `已配置 · ${settings.doubao.model}` : "未配置"],
    ["在线查询", settings.online?.api_url || "未配置"],
  ];
  $("#systemInfo").innerHTML = info
    .map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`)
    .join("");

  const topCommands = (stats.commands || []).slice(0, 5);
  const rows = [
    ["请求总数", formatNumber(stats.requests?.total)],
    ["成功 / 失败", `${formatNumber(stats.requests?.ok)} / ${formatNumber(stats.requests?.failed)}`],
    ["平均耗时", formatDuration(stats.requests?.avg_ms)],
    ["缓存", `${formatNumber(cache.entries)} 条 · 命中率 ${formatPercent(cache.hit_rate)}`],
    ["Token", settings.jx3api?.token_configured ? `已配置 ${settings.jx3api.token_masked}` : "未配置"],
    ["推栏 Ticket", settings.jx3api?.ticket_configured ? `已配置 ${settings.jx3api.ticket_masked}` : "未配置"],
    ["热门指令", topCommands.length ? topCommands.map((item) => `${item.key} ×${item.count}`).join("、") : "暂无"],
  ];
  $("#systemStats").innerHTML = rows
    .map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`)
    .join("");
  const timings = Object.entries(stats.command_timings || {}).filter(([key]) => key.endsWith(":reply")).sort((a,b) => b[1].p95_ms-a[1].p95_ms).slice(0,8);
  $("#commandTimings").innerHTML = timings.length ? timings.map(([key,value]) => {
    const command = (state.commands || []).find(item => item.key === key.split(":")[0]);
    return `<tr><th scope="row">${esc(command?.name || key.split(":")[0])}</th><td>${formatDuration(value.median_ms)}</td><td>${formatDuration(value.p95_ms)}</td><td>${value.samples}</td></tr>`;
  }).join("") : '<tr><td colspan="4" class="empty-state">收到查询后显示耗时</td></tr>';
}

async function exportConfig() {
  try {
    const data = await apiGet("export", {});
    state.lastExportText = JSON.stringify(data, null, 2);
    $("#exportBox").textContent = state.lastExportText;
    toast("配置摘要已生成", "ok");
  } catch (error) {
    toast(`导出失败：${error.message || error}`, "bad");
  }
}

async function resetStats() {
  const ok = await confirmModal({
    title: "重置统计",
    body: "将清零请求次数、成功率、指令计数与运行时长；日志与缓存不受影响。",
    okText: "重置",
  });
  if (!ok) return;
  try {
    const result = await apiPost("stats/reset", {});
    if (result?.stats) state.data.stats = result.stats;
    renderOverview();
    renderSystem();
    renderCache();
    toast(result?.message || "统计已重置", "ok");
  } catch (error) {
    toast(`重置失败：${error.message || error}`, "bad");
  }
}

/* --------------------------------------------------------------- events */
function switchTab(tab) {
  if (!TAB_META[tab]) return;
  state.activeTab = tab;
  $$(".nav-item").forEach((node) => node.classList.toggle("is-active", node.dataset.tab === tab));
  $$(".page").forEach((node) => {
    node.hidden = node.dataset.page !== tab;
  });
  $("#pageTitle").textContent = TAB_META[tab][0];
  $("#pageSubtitle").textContent = TAB_META[tab][1];
  $("#pageKicker").textContent = TAB_META[tab][2];
  window.scrollTo({ top: 0, behavior: "smooth" });
  if (tab === "logs") loadLogs();
  if (tab === "debug") ensureEndpoints();
  if (tab === "aliases") loadAliases();
  if (tab === "styles") loadCardStyles();
  if (tab === "events") loadEventsSummary();
  if (tab === "paid") refreshPaid();
  if (tab === "system") renderSystem();
}

function bindStaticEvents() {
  $("#fatalRetry")?.addEventListener("click", () => loadBootstrap());
  $("#refreshBtn")?.addEventListener("click", async () => {
    if (state.configDirty || state.commandDirty) {
      const ok = await confirmModal({
        title: "刷新后台",
        body: "当前有未保存的修改，刷新会丢失这些修改。确定继续吗？",
        okText: "刷新",
      });
      if (!ok) return;
    }
    await loadBootstrap(true);
    if (state.activeTab === "logs") await loadLogs();
  });

  $$(".nav-item").forEach((node) => {
    node.addEventListener("click", () => switchTab(node.dataset.tab));
  });

  $("#openConfigBtn")?.addEventListener("click", () => switchTab("config"));
  $("#overviewLogsBtn")?.addEventListener("click", () => switchTab("logs"));
  $("#testAllBtn")?.addEventListener("click", (event) => runTest("all", event.currentTarget));
  $("#clearCacheBtn")?.addEventListener("click", () => clearCache("all"));
  $("#refreshHealth")?.addEventListener("click", (event) => runTest("all", event.currentTarget));
  $("#refreshTokenBtn")?.addEventListener("click", () => refreshTokenStats(true));
  $("#tokenAutoRefresh")?.addEventListener("change", scheduleTokenRefresh);

  document.addEventListener("input", (event) => {
    if (event.target?.dataset?.setting) setConfigDirty(true);
  });
  document.addEventListener("change", (event) => {
    if (event.target?.dataset?.setting) setConfigDirty(true);
  });
  $("#configForm")?.addEventListener("submit", (event) => event.preventDefault());
  $("#saveConfigBtn")?.addEventListener("click", (event) => saveConfig(event.currentTarget));
  $("#reloadConfigBtn")?.addEventListener("click", () => renderConfig());

  $$("[data-toggle-secret]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = $(`#${button.dataset.toggleSecret}`);
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "隐藏" : "显示";
    });
  });
  $$("[data-clear-secret]").forEach((button) => {
    button.addEventListener("click", () => clearSecret(button.dataset.clearSecret));
  });
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-test]");
    if (button) runTest(button.dataset.test, button);
  });

  $("#commandSearch")?.addEventListener("input", renderCommands);
  $("#commandCategory")?.addEventListener("change", renderCommands);
  $("#commandRows")?.addEventListener("change", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (!row) return;
    updateCommandFromRow(row);
    markCommandDirty();
  });
  $("#commandRows")?.addEventListener("input", (event) => {
    const row = event.target.closest("tr[data-key]");
    if (!row) return;
    updateCommandFromRow(row);
    markCommandDirty();
  });
  $("#saveCommandsBtn")?.addEventListener("click", (event) => saveCommands(event.currentTarget));
  $("#enableAllBtn")?.addEventListener("click", () => {
    state.commands.forEach((item) => { item.enabled = true; });
    renderCommands();
    markCommandDirty();
  });
  $("#disableAllBtn")?.addEventListener("click", () => {
    state.commands.forEach((item) => { item.enabled = false; });
    renderCommands();
    markCommandDirty();
  });
  $("#resetCommandsBtn")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "恢复默认指令配置",
      body: "将清除所有指令开关、冷却与权限修改，恢复插件默认值。",
      okText: "恢复默认",
    });
    if (!ok) return;
    try {
      const result = await apiPost("commands/save", { reset: true });
      if (Array.isArray(result?.commands)) {
        state.commands = result.commands.map((item) => ({ ...item }));
        state.data.commands = result.commands;
      }
      state.commandDirty = false;
      renderCommands();
      toast(result?.message || "已恢复默认", "ok");
    } catch (error) {
      toast(`恢复失败：${error.message || error}`, "bad");
    }
  });

  $("#saveAliasesBtn")?.addEventListener("click", (event) => saveAliases(event.currentTarget));
  $("#reloadAliasesBtn")?.addEventListener("click", loadAliases);
  $("#saveCardStylesBtn")?.addEventListener("click", (e) => saveCardStyles(e.currentTarget));
  $("#reloadCardStylesBtn")?.addEventListener("click", () => loadCardStyles());
  $("#addCardStyleBtn")?.addEventListener("click", (e) => addCardStyle(e.currentTarget));
  $("#resetCardStylesBtn")?.addEventListener("click", (e) => resetCardStyles(e.currentTarget));
  $("#aliasDefaultServer")?.addEventListener("input", (event) => {
    const canonical = $('[data-setting="admin.default_server"]');
    if (canonical) canonical.value = event.target.value;
  });
  $("#aliasRows")?.addEventListener("input", () => {
    $("#aliasDirty").textContent = "有未保存的别名修改";
    $("#aliasDirty").classList.add("is-dirty");
  });
  $("#addAliasBtn")?.addEventListener("click", () => {
    const server = $("#aliasServer").value;
    const alias = ($("#aliasValue").value || "").trim();
    if (!server || !alias) {
      toast("请选择区服并填写别名", "bad");
      return;
    }
    const input = $$("[data-alias-server]").find(
      (node) => node.dataset.aliasServer === server,
    );
    if (!input) return;
    const values = input.value.split(/[,，;；]/).map((item) => item.trim()).filter(Boolean);
    if (!values.includes(alias)) {
      values.push(alias);
      input.value = values.join(", ");
      $("#aliasDirty").textContent = "有未保存的别名修改";
      $("#aliasDirty").classList.add("is-dirty");
    }
    $("#aliasValue").value = "";
  });
  $("#resetAliasesBtn")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "恢复默认区服别名",
      body: "将丢弃所有自定义别名，恢复插件内置的区服别名表。",
      okText: "恢复默认",
    });
    if (!ok) return;
    try {
      const result = await apiPost("aliases/reset", {});
      if (result?.rows) {
        state.data.aliases = result;
        renderAliases();
      }
      toast(result?.message || "已恢复默认", "ok");
    } catch (error) {
      toast(`恢复失败：${error.message || error}`, "bad");
    }
  });

  $("#saveEventSessionBtn")?.addEventListener("click", (event) =>
    saveEventSession(event.currentTarget),
  );
  $("#eventSessionSelect")?.addEventListener("change", renderEventSession);
  $("#saveEventsBtn")?.addEventListener("click", (event) =>
    saveConfig(event.currentTarget, { reloadEvents: true }),
  );
  $("#reloadEventsBtn")?.addEventListener("click", async (event) => {
    await withBusy(event.currentTarget, async () => {
      try {
        const reload = await apiPost("events/reload", {});
        if (reload?.status) {
          state.data.events = reload;
          renderEvents();
        }
        toast(reload?.message || "事件通道已重连", "ok");
      } catch (error) {
        toast(`重连失败：${error.message || error}`, "bad");
      }
    }, "重连中…");
  });
  $("#eventActionGrid")?.addEventListener("change", () => {
    const boxes = $$("[data-event-action]");
    const checked = boxes.filter((box) => box.checked).length;
    $("#eventStatActions").textContent = formatNumber(checked);
    $("#eventDirty").textContent = "有未保存的事件选择";
    $("#eventDirty").classList.add("is-dirty");
  });
  $("#eventSelectFreeBtn")?.addEventListener("click", () => {
    $$("[data-event-action]").forEach((box) => {
      box.checked = Number(box.dataset.eventAction) >= 2000;
    });
    $("#eventActionGrid").dispatchEvent(new Event("change", { bubbles: true }));
  });
  $("#eventSelectAllBtn")?.addEventListener("click", () => {
    $$("[data-event-action]").forEach((box) => { box.checked = true; });
    $("#eventActionGrid").dispatchEvent(new Event("change", { bubbles: true }));
  });
  $("#eventSelectNoneBtn")?.addEventListener("click", () => {
    $$("[data-event-action]").forEach((box) => { box.checked = false; });
    $("#eventActionGrid").dispatchEvent(new Event("change", { bubbles: true }));
  });

  $("#savePaidModeBtn")?.addEventListener("click", (event) => savePaidMode(event.currentTarget));
  $("#savePaidGroupBtn")?.addEventListener("click", (event) => savePaidGroup(event.currentTarget));
  $("#generateCodesBtn")?.addEventListener("click", (event) => generateCodes(event.currentTarget));
  $("#refreshPaidBtn")?.addEventListener("click", refreshPaid);
  $("#paidGroupRows")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-paid-action]");
    if (!button) return;
    const action = button.dataset.paidAction;
    const sessionId = button.dataset.session;
    if (action === "delete") {
      const ok = await confirmModal({
        title: "移出白名单",
        body: `确定删除 ${sessionId} 的付费授权吗？`,
        okText: "删除",
      });
      if (!ok) return;
      try {
        const result = await apiPost("paid/groups/delete", { session_id: sessionId });
        if (result?.groups) state.data.paid = result;
        renderPaid();
        toast(result?.message || "已删除", "ok");
      } catch (error) {
        toast(`删除失败：${error.message || error}`, "bad");
      }
      return;
    }
    try {
      const payload = { session_id: sessionId };
      if (action === "extend") payload.extend_days = 30;
      if (action === "toggle") payload.active = button.dataset.active === "1";
      const result = await apiPost("paid/groups/save", payload);
      if (result?.groups) state.data.paid = result;
      renderPaid();
      toast(result?.message || "授权已更新", "ok");
    } catch (error) {
      toast(`更新失败：${error.message || error}`, "bad");
    }
  });
  $("#paidCodeRows")?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-paid-action]");
    if (!button) return;
    const code = button.dataset.code;
    if (button.dataset.paidAction === "copy") {
      copyText(code, "激活码已复制");
      return;
    }
    const ok = await confirmModal({
      title: "删除激活码",
      body: `确定删除 ${code} 吗？已使用的激活码不会影响已授权群。`,
      okText: "删除",
    });
    if (!ok) return;
    try {
      const result = await apiPost("paid/codes/delete", { code });
      if (result?.groups) state.data.paid = result;
      renderPaid();
      toast(result?.message || "已删除", "ok");
    } catch (error) {
      toast(`删除失败：${error.message || error}`, "bad");
    }
  });

  $("#refreshLogsBtn")?.addEventListener("click", loadLogs);
  $("#logLevel")?.addEventListener("change", loadLogs);
  $("#logSearch")?.addEventListener("input", () => {
    clearTimeout(window.__logTimer);
    window.__logTimer = setTimeout(loadLogs, 350);
  });
  $("#clearLogsBtn")?.addEventListener("click", clearLogs);
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-clear-cache]");
    if (button) clearCache(button.dataset.clearCache);
  });

  $("#endpointSearch")?.addEventListener("input", renderEndpointList);
  $("#endpointList")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-path]");
    if (!button) return;
    const item = state.endpoints.find((entry) => entry.path === button.dataset.path);
    if (item) selectEndpoint(item);
  });
  $("#debugPath")?.addEventListener("input", () => {
    const value = ($("#debugPath").value || "").trim();
    const item = state.endpoints.find((entry) => entry.path === value);
    if (item) selectEndpoint(item, { keepPath: true });
    else {
      state.selectedEndpoint = null;
      $("#endpointMeta").innerHTML = `<span class="tag">自定义路径</span><span>${esc(value || "未填写")}</span>`;
      $("#paramFields").innerHTML = "";
    }
  });
  $("#debugSendBtn")?.addEventListener("click", (event) => sendDebug(event.currentTarget));
  $("#copyResponseBtn")?.addEventListener("click", () => copyText(state.lastDebugText, "响应已复制"));

  $("#exportBtn")?.addEventListener("click", exportConfig);
  $("#copyExportBtn")?.addEventListener("click", () => copyText(state.lastExportText, "导出内容已复制"));
  $("#resetStatsBtn")?.addEventListener("click", resetStats);
}

init();

/* --------------------------------------------------------- card styles (名片模板) */
function renderCardStyles() {
  const data = state.data?.cardStyles;
  const dirty0 = $("#cardStyleDirty");
  if (!data) {
    if (dirty0) dirty0.textContent = "接口没有返回数据";
    return;
  }
  if (data.ok === false) {
    if (dirty0) dirty0.textContent = `接口报错：${data.message || "未知错误"}`;
    const b0 = $("#cardStyleRows");
    if (b0) b0.innerHTML = "";
    return;
  }
  const rows = data.rows || [];
  const body = $("#cardStyleRows");
  if (!body) return;
  body.innerHTML = rows.map((row, index) => {
    const key = esc(row.key || "");
    return `
      <tr data-card-key="${key}">
        <td><input class="alias-input" type="text" data-cs-field="label" value="${esc(row.label || "")}" /></td>
        <td><input class="alias-input card-style-num" type="number" min="1" data-cs-field="order" value="${esc(row.order ?? index + 1)}" /></td>
        <td><input class="card-style-check" type="checkbox" data-cs-field="enabled" ${row.enabled === false ? "" : "checked"} /></td>
        <td>
          <textarea class="alias-input" rows="3" data-cs-field="prompt">${esc(row.prompt || "")}</textarea>
          <textarea class="alias-input" rows="2" data-cs-field="negative" placeholder="负面词（可空）">${esc(row.negative || "")}</textarea>
        </td>
        <td>
          <input class="alias-input" type="text" data-cs-field="size" placeholder="1024x1536" value="${esc(row.size || "")}" />
          <input class="alias-input" type="text" data-cs-field="final_size" placeholder="压缩尺寸" value="${esc(row.final_size || "")}" />
        </td>
        <td><button class="btn tiny ghost" data-cs-del="${key}" type="button">删除</button></td>
      </tr>`;
  }).join("");
  body.querySelectorAll("[data-cs-del]").forEach((btn) => {
    btn.addEventListener("click", () => deleteCardStyle(btn.dataset.csDel));
  });
  const dirty = $("#cardStyleDirty");
  if (dirty) { dirty.textContent = `共 ${rows.length} 个模板`; dirty.classList.remove("is-dirty"); }
}

function collectCardStyles() {
  return $$("#cardStyleRows tr").map((tr) => {
    const get = (f) => tr.querySelector(`[data-cs-field="${f}"]`);
    return {
      key: tr.dataset.cardKey,
      label: get("label")?.value?.trim() || "",
      prompt: get("prompt")?.value || "",
      negative: get("negative")?.value || "",
      size: get("size")?.value?.trim() || "",
      final_size: get("final_size")?.value?.trim() || "",
      order: Number(get("order")?.value || 0) || 0,
      enabled: !!get("enabled")?.checked,
    };
  });
}

async function loadCardStyles() {
  try {
    const data = await apiGet("card-styles/summary", {});
    if (data?.rows) {
      state.data = state.data || {};
      state.data.cardStyles = data;
      renderCardStyles();
    }
  } catch (error) {
    toast(`读取名片模板失败：${error.message || error}`, "bad");
  }
}

async function saveCardStyles(button) {
  await withBusy(button, async () => {
    try {
      const result = await apiPost("card-styles/save", { rows: collectCardStyles() });
      if (result?.rows) { state.data.cardStyles = result; renderCardStyles(); }
      toast("名片模板已保存", "ok");
    } catch (error) {
      toast(`保存失败：${error.message || error}`, "bad");
    }
  }, "保存中…");
}

async function deleteCardStyle(key) {
  if (!key) return;
  // 后台 iframe 里 confirm() 会被拦，所以先标记再删 ✅
  const tr = document.querySelector(`tr[data-card-key="${key}"]`);
  if (tr && tr.dataset.confirmDel !== "1") {
    tr.dataset.confirmDel = "1";
    tr.style.opacity = "0.45";
    const btn = tr.querySelector("[data-cs-del]");
    if (btn) btn.textContent = "再点一次";
    toast("再点一次「删除」确认删除", "bad");
    setTimeout(() => {
      if (tr) { tr.dataset.confirmDel = ""; tr.style.opacity = ""; }
      const b = tr?.querySelector("[data-cs-del]");
      if (b) b.textContent = "删除";
    }, 4000);
    return;
  }
  try {
    const result = await apiPost("card-styles/delete", { key });
    if (result?.rows) { state.data.cardStyles = result; renderCardStyles(); }
    toast("已删除", "ok");
  } catch (error) {
    toast(`删除失败：${error.message || error}`, "bad");
  }
}

async function addCardStyle() {
  // 后台在 iframe 里，prompt() 会被拦，所以直接插一空行 ✅
  const body = $("#cardStyleRows");
  if (!body) return;
  const count = $$("#cardStyleRows tr").length;
  const key = `custom${Date.now()}`;
  const tr = document.createElement("tr");
  tr.dataset.cardKey = key;
  tr.innerHTML = `
    <td><input class="alias-input" type="text" data-cs-field="label" value="新模板${count + 1}" /></td>
    <td><input class="alias-input" type="number" data-cs-field="order" value="${count + 1}" /></td>
    <td><input type="checkbox" data-cs-field="enabled" checked /></td>
    <td>
      <textarea class="alias-input" rows="3" data-cs-field="prompt" placeholder="在这里填提示词"></textarea>
      <textarea class="alias-input" rows="2" data-cs-field="negative" placeholder="负面词（可空）"></textarea>
    </td>
    <td>
      <input class="alias-input" type="text" data-cs-field="size" placeholder="1024x1536" />
      <input class="alias-input" type="text" data-cs-field="final_size" placeholder="压缩尺寸" />
    </td>
    <td><button class="btn tiny ghost" data-cs-del="${key}" type="button">删除</button></td>`;
  body.appendChild(tr);
  tr.querySelector("[data-cs-del]")?.addEventListener("click", () => deleteCardStyle(key));
  const dirty = $("#cardStyleDirty");
  if (dirty) dirty.textContent = "已新增一行，填完点保存";
  toast("已新增一行，填提示词后点保存", "ok");
}

async function resetCardStyles() {
  try {
    const result = await apiPost("card-styles/reset", {});
    if (result?.rows) { state.data.cardStyles = result; renderCardStyles(); }
    toast("已恢复默认", "ok");
  } catch (error) {
    toast(`恢复失败：${error.message || error}`, "bad");
  }
}
