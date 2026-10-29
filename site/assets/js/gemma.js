// The main-thread side of Gemma: load once, then ask one thing at a time.

// How much of a document Gemma reads. The model returns a score for each of its 262k vocabulary entries at every
// position of the prompt, so a long prompt overflows a GPU buffer; the worker trims the document to this many tokens.
export const MAX_TOKENS = 320;

let worker = null, ready = null, seq = 0;
const pending = new Map();
const listeners = new Set();

export async function webgpu() {
  if (!navigator.gpu) return { ok: false, why: "This browser has no WebGPU." };
  const adapter = await navigator.gpu.requestAdapter().catch(() => null);
  if (!adapter) return { ok: false, why: "WebGPU is here, but no graphics adapter answered." };
  return { ok: true, f16: adapter.features.has("shader-f16") };
}

export function onProgress(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export const isReady = () => !!ready && ready.done;

export function load() {
  if (ready) return ready.promise;
  ready = { done: false };
  ready.promise = (async () => {
    const gpu = await webgpu();
    if (!gpu.ok) throw new Error(gpu.why);
    worker = new Worker(new URL("./gemma-worker.js", import.meta.url), { type: "module" });
    worker.onmessage = ({ data }) => {
      if (data.type === "progress") listeners.forEach((fn) => fn(data.p));
      if (data.type === "token") pending.get(data.id)?.onToken?.(data.t);
      if (data.type === "done") { pending.get(data.id)?.resolve(data.text); pending.delete(data.id); }
      if (data.type === "error") {
        const p = pending.get(data.id);
        if (p) { p.reject(new Error(data.message)); pending.delete(data.id); }
        else ready.fail?.(new Error(data.message));
      }
    };
    await new Promise((resolve, reject) => {
      ready.fail = reject;
      const h = ({ data }) => { if (data.type === "ready") { worker.removeEventListener("message", h); resolve(); } };
      worker.addEventListener("message", h);
      worker.postMessage({ type: "load", f16: gpu.f16 });
    });
    ready.done = true;
  })();
  ready.promise.catch(() => { ready = null; });
  return ready.promise;
}

let queue = Promise.resolve();
function run(msg, onToken) {
  const job = queue.then(async () => {
    await load();
    const id = ++seq;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject, onToken });
      worker.postMessage({ ...msg, id });
    });
  });
  queue = job.catch(() => {});
  return job;
}

/** Asks Gemma one question. Calls run one after another, because the GPU only has one of them. */
export const ask = (messages, { max = 160, onToken } = {}) => run({ type: "generate", messages, max }, onToken);

/**
 * Gemma's own probability that its first word is one of `yes` rather than `no`, in one forward pass, after a
 * question and a document. The document is trimmed to fit, but every sentence in `must` stays in.
 * Resolves to { p, kept, of, tokens }: p from 0 to 1, and how many of the document's characters were read.
 */
export const lean = (question, document, { yes = ["Yes"], no = ["No"], must = [] } = {}) =>
  run({ type: "score", prefix: question, body: document, must, yes, no, maxTokens: MAX_TOKENS });
