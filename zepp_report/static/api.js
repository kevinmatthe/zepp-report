async function api(path, method = "GET", body) {
  const r = await fetch(path, { method, credentials: "same-origin", headers: method === "GET" ? {} : { "Content-Type": "application/json", "X-Zepp-Request": "1" }, ...body === void 0 ? {} : { body: JSON.stringify(body) } });
  if (r.status === 401) {
    window.dispatchEvent(new Event("session-expired"));
    throw Error(path === "/api/login" ? "密码不正确，请重试。" : "请登录后继续。");
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(typeof data.detail === "string" ? data.detail : `请求失败（${r.status}）`);
  return data;
}
async function action(button, fn) {
  if (button) button.disabled = true;
  try {
    await fn();
  } catch (e) {
    window.dispatchEvent(new CustomEvent("app-error", { detail: e.message }));
  } finally {
    if (button) button.disabled = false;
  }
}
export {
  action,
  api
};
