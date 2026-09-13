const labels = {
  ready: "可用",
  degraded: "能力不足",
  unknown: "未知",
};

function send(message) {
  return chrome.runtime.sendMessage(message);
}

function render(status) {
  document.querySelector("#api").textContent = labels[status?.api] ?? status?.api ?? "未知";
  document.querySelector("#target").textContent = labels[status?.target] ?? status?.target ?? "未知";
  document.querySelector("#protocol").textContent = status?.protocolVersion ?? "1.0";
  const summary = document.querySelector("#summary");
  const details = document.querySelector("#details");
  if (status?.lastError) {
    summary.textContent = status.lastError;
    summary.dataset.state = "error";
  } else if (status?.target === "ready") {
    summary.textContent = "页面与本机协议已完成能力协商";
    summary.dataset.state = "ready";
  } else {
    summary.textContent = "打开并选中 QQ 音乐网页版后进行检测";
    summary.dataset.state = "idle";
  }
  if (status?.diagnostics) {
    details.hidden = false;
    details.textContent = JSON.stringify(status.diagnostics, null, 2);
  } else {
    details.hidden = true;
  }
}

document.querySelector("#probe").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "正在检测…";
  const response = await send({ type: "moodmusic.probe" });
  if (response?.ok) render(response.result);
  else render({ lastError: response?.error ?? "检测失败" });
  button.disabled = false;
  button.textContent = "重新检测";
});

void send({ type: "moodmusic.status" }).then((response) => render(response?.result));
