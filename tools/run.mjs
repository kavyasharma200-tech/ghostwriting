// Opens a page in headless Chrome (with WebGPU), waits for `window.done`, and prints `window.report`
// or the page's text. Used for the engine tests and the evaluation.
//   node tools/run.mjs http://localhost:8790/test.html [--timeout 600000] [--headed]
import { spawn } from "node:child_process";
import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";
import { homedir, tmpdir } from "node:os";

const args = process.argv.slice(2);
const url = args.find((a) => a.startsWith("http"));
const opt = (n, d) => { const i = args.indexOf(`--${n}`); return i >= 0 ? args[i + 1] : d; };
const timeout = +opt("timeout", 600000);
const headed = args.includes("--headed");
const shotPath = opt("shot", null); // save a screenshot of the page once it is done
const browser = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
// A fixed profile keeps the downloaded model cached between runs.
const profile = opt("profile", join(homedir(), ".cache", "gw-chrome"));
const port = 9400 + Math.floor(Math.random() * 500);
const proc = spawn(browser, [
  ...(headed ? [] : ["--headless=new"]), `--remote-debugging-port=${port}`, "--window-size=1440,900",
  "--enable-unsafe-webgpu", "--enable-features=Vulkan,WebGPU", "--ignore-gpu-blocklist", "--use-angle=d3d11",
  "--no-first-run", "--no-default-browser-check", `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws;
for (let i = 0; i < 80 && !ws; i++) {
  try {
    const page = (await (await fetch(`http://127.0.0.1:${port}/json`)).json()).find((t) => t.type === "page");
    if (page) ws = new WebSocket(page.webSocketDebuggerUrl);
  } catch {}
  if (!ws) await sleep(250);
}
await new Promise((r) => ws.addEventListener("open", r));
let id = 0, failed = false; const pending = new Map();
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.consoleAPICalled") console.log(`[console.${m.params.type}]`, m.params.args.map((a) => a.value ?? a.description).join(" ").slice(0, 400));
  if (m.method === "Runtime.exceptionThrown") failed = true; // an uncaught error means window.done never comes
  if (m.method === "Runtime.exceptionThrown") console.log("[exception]", (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 400));
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Runtime.enable");
await send("Page.enable");
// Always load the latest page and scripts (the model lives in Cache Storage, which this leaves alone).
await send("Network.enable");
await send("Network.setCacheDisabled", { cacheDisabled: true });
await send("Page.navigate", { url });
const t0 = Date.now();
let done = false;
while (Date.now() - t0 < timeout) {
  await sleep(1000);
  const r = await send("Runtime.evaluate", { expression: "!!window.done" });
  if (r.result?.result?.value) { done = true; break; }
  if (failed) break;
}
if (shotPath && done) {
  const { writeFileSync } = await import("node:fs");
  const r = await send("Page.captureScreenshot", { format: "jpeg", quality: 90 });
  writeFileSync(shotPath, Buffer.from(r.result.data, "base64"));
  console.log("screenshot", shotPath);
}
const r = await send("Runtime.evaluate", { expression: "window.report ? JSON.stringify(window.report) : document.body.innerText", returnByValue: true });
console.log(done ? "--- done in " + Math.round((Date.now() - t0) / 1000) + " s" : "--- timed out");
console.log(r.result?.result?.value);
ws.close(); proc.kill(); await sleep(300);
process.exit(0);
