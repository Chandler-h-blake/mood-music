import {
  CONNECTOR_CAPABILITIES,
  CONNECTOR_TYPES,
  PROTOCOL_VERSION,
} from "./connector-contract.js";

const API_ORIGIN = "http://127.0.0.1:8000";
const STATUS_KEY = "moodmusicConnectorStatus";
const INSTALLATION_KEY = "moodmusicInstallationId";

function now() {
  return new Date().toISOString();
}

async function installationId() {
  const stored = await chrome.storage.local.get(INSTALLATION_KEY);
  if (stored[INSTALLATION_KEY]) return stored[INSTALLATION_KEY];
  const id = crypto.randomUUID();
  await chrome.storage.local.set({ [INSTALLATION_KEY]: id });
  return id;
}

async function saveStatus(patch) {
  const previous = (await chrome.storage.local.get(STATUS_KEY))[STATUS_KEY] ?? {};
  const next = { ...previous, ...patch, updatedAt: now() };
  await chrome.storage.local.set({ [STATUS_KEY]: next });
  return next;
}

async function negotiate(capabilities = CONNECTOR_CAPABILITIES) {
  const descriptorResponse = await fetch(`${API_ORIGIN}/api/v1/connectors/protocol`);
  if (!descriptorResponse.ok) throw new Error(`协议读取失败：HTTP ${descriptorResponse.status}`);
  const descriptor = await descriptorResponse.json();
  if (descriptor.protocolVersion !== PROTOCOL_VERSION) {
    throw new Error(`协议不兼容：扩展 ${PROTOCOL_VERSION} / API ${descriptor.protocolVersion}`);
  }
  if (!descriptor.connectorTypes.includes("web") || !CONNECTOR_TYPES.includes("web")) {
    throw new Error("API 不支持 web 连接器");
  }

  const requestId = crypto.randomUUID();
  const response = await fetch(`${API_ORIGIN}/api/v1/connectors/negotiate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      protocolVersion: PROTOCOL_VERSION,
      type: "connector.hello",
      requestId,
      sentAt: now(),
      payload: {
        installationId: await installationId(),
        connectorType: "web",
        connectorVersion: chrome.runtime.getManifest().version,
        targetAppVersion: "qqmusic-web:runtime-probe",
        adapterVersion: "qqmusic-web-probe-v1",
        capabilities,
      },
    }),
  });
  if (!response.ok) throw new Error(`能力协商失败：HTTP ${response.status}`);
  const welcome = await response.json();
  if (welcome.requestId !== requestId || welcome.type !== "connector.welcome") {
    throw new Error("能力协商响应与请求不匹配");
  }
  return saveStatus({
    api: "ready",
    negotiatedCapabilities: welcome.payload.negotiatedCapabilities,
    protocolVersion: welcome.protocolVersion,
    lastError: null,
  });
}

async function probeActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url?.startsWith("https://y.qq.com/")) {
    throw new Error("请先打开并选中 QQ 音乐网页版标签页");
  }
  const probe = await chrome.tabs.sendMessage(tab.id, { type: "moodmusic.probe" });
  if (!probe?.ok) throw new Error(probe?.message ?? "QQ 音乐页面探测失败");
  await negotiate(probe.capabilities);
  return saveStatus({
    target: probe.status,
    pageKind: probe.pageKind,
    capabilities: probe.capabilities,
    diagnostics: probe.diagnostics,
    lastError: null,
  });
}

chrome.runtime.onInstalled.addListener(() => {
  void saveStatus({ api: "unknown", target: "unknown", lastError: null });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !["moodmusic.status", "moodmusic.negotiate", "moodmusic.probe"].includes(message.type)) {
    return false;
  }
  const task = async () => {
    if (message.type === "moodmusic.status") {
      return (await chrome.storage.local.get(STATUS_KEY))[STATUS_KEY] ?? null;
    }
    if (message.type === "moodmusic.negotiate") return negotiate();
    return probeActiveTab();
  };
  task()
    .then((result) => sendResponse({ ok: true, result }))
    .catch(async (error) => {
      const messageText = error instanceof Error ? error.message : "未知错误";
      await saveStatus({ lastError: messageText });
      sendResponse({ ok: false, error: messageText });
    });
  return true;
});
