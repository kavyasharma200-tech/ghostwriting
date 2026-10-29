// Gemma 3 1B in a Web Worker, on the visitor's own GPU. Nothing is sent anywhere.

import { pipeline, TextStreamer, env } from "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.1";

env.allowLocalModels = false;
const MODEL = "onnx-community/gemma-3-1b-it-ONNX-GQA";
let gen = null;

/** Token ids whose text starts with one of the given words (any case, with or without a leading space). */
const idsCache = new Map();
function idsFor(words) {
  const key = words.join("|");
  if (idsCache.has(key)) return idsCache.get(key);
  const ids = new Set();
  for (const w of words) {
    for (const v of [w, " " + w, w.toLowerCase(), " " + w.toLowerCase(), w.toUpperCase(), " " + w.toUpperCase()]) {
      const t = gen.tokenizer.encode(v, { add_special_tokens: false });
      if (t.length) ids.add(Number(t[0]));
    }
  }
  idsCache.set(key, [...ids]);
  return idsCache.get(key);
}

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "load") {
      if (!gen) {
        gen = await pipeline("text-generation", MODEL, {
          device: "webgpu",
          dtype: data.f16 ? "q4f16" : "q4",
          progress_callback: (p) => self.postMessage({ type: "progress", p }),
        });
      }
      self.postMessage({ type: "ready" });
    }
    if (data.type === "generate") {
      const streamer = new TextStreamer(gen.tokenizer, {
        skip_prompt: true,
        skip_special_tokens: true,
        callback_function: (t) => self.postMessage({ type: "token", id: data.id, t }),
      });
      const out = await gen(data.messages, { max_new_tokens: data.max ?? 160, do_sample: false, streamer });
      const msgs = out[0].generated_text;
      const text = Array.isArray(msgs) ? msgs.at(-1).content : String(msgs);
      self.postMessage({ type: "done", id: data.id, text });
    }
    if (data.type === "score") {
      // The model scores its whole 262k vocabulary at every prompt position, so the prompt has to stay short:
      // keep the question, trim the document to fit, and put back any sentence in `must` that the trim cut off.
      const build = (k) => {
        const body = data.body.slice(0, k);
        const missing = (data.must || []).filter((m) => !body.includes(m.slice(0, 40)));
        return data.prefix + body + (missing.length ? "\n" + missing.join("\n") : "");
      };
      const count = (content) => {
        const t = gen.tokenizer.apply_chat_template([{ role: "user", content }], { add_generation_prompt: true, return_dict: true });
        return t.input_ids.dims.at(-1); // the same call the forward pass uses, so the count is exact
      };
      let lo = 0, hi = Math.min(data.body.length, data.maxTokens * 8); // a token is never shorter than 1/8 of this
      while (lo < hi) { const mid = Math.ceil((lo + hi) / 2); if (count(build(mid)) <= data.maxTokens) lo = mid; else hi = mid - 1; }
      const messages = [{ role: "user", content: build(lo) }];
      // One forward pass: how likely is the model's very first word to be `yes` rather than `no`?
      const inputs = gen.tokenizer.apply_chat_template(messages, { add_generation_prompt: true, return_dict: true });
      const { logits } = await gen.model(inputs);
      const [, seq, vocab] = logits.dims;
      const row = logits.data.subarray((seq - 1) * vocab, seq * vocab);
      const pick = (ids) => ids.map((i) => Number(row[i]));
      const y = pick(idsFor(data.yes)), n = pick(idsFor(data.no));
      const m = Math.max(...y, ...n);
      const ey = y.reduce((s, l) => s + Math.exp(l - m), 0), en = n.reduce((s, l) => s + Math.exp(l - m), 0);
      self.postMessage({ type: "done", id: data.id, text: { p: ey / (ey + en), kept: lo, of: data.body.length, tokens: seq } });
    }
  } catch (err) {
    self.postMessage({ type: "error", id: data.id, message: String(err?.message || err) });
  }
};
