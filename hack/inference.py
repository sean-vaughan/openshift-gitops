#!/usr/bin/env python3
"""
Shared inference core for OpenShift Genesis (ADR-0012 authoring loop, ADR-0017
loop engineering).

The ONE endpoint every Genesis agent surface calls — the harvester PR-authoring
step today (hack/harvest_author.py), the OOD/novelty pre-gate and the
outcome-grader next (ADR-0017 four-check stack). "One core, many surfaces":
inference is NOT embedded per-agent; every surface speaks through this module.

It speaks the OpenAI-compatible /v1 chat-completions wire format, so the backend
is swappable by CONFIG ALONE: Ollama + qwen2.5 on the Bazzite box (Phase A) today
-> Granite on RHOAI (vLLM, Phase B) by flipping base_url + model in
hack/inference.json. No agent code changes when the backend moves.

This is a faithful sibling of ~/src/salience-engine/scripts/inference.py — same
resolution order, same chat() contract — mirrored here rather than imported, so
neither repo depends on the other's checkout. The pattern is the shared thing.

Resolution order (highest wins):
  env (INFERENCE_BASE_URL / INFERENCE_MODEL)  >  hack/inference.json  >  defaults

Stdlib only — no pip dependency (the in-cluster gitops-agent image stays slim).
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "inference.json"

DEFAULTS = {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:14b"}


class InferenceError(RuntimeError):
    """Raised when the shared endpoint is unreachable or returns garbage.

    Callers are expected to DEGRADE GRACEFULLY on this — the cheap model only
    ever DRAFTS narrative (ADR-0017 / Engine Role Charter); nothing it produces
    decides a gate, so its absence must never block the deterministic path.
    """


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG.exists():
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
            for k in ("base_url", "model"):
                if data.get(k):
                    cfg[k] = data[k]
        except json.JSONDecodeError:
            pass  # fall back to defaults rather than crash the caller
    # env wins — lets a tunnel/dev run repoint without editing committed config
    cfg["base_url"] = os.environ.get("INFERENCE_BASE_URL", cfg["base_url"]).rstrip("/")
    cfg["model"] = os.environ.get("INFERENCE_MODEL", cfg["model"])
    return cfg


def chat(messages, *, model=None, temperature=0.2, json_object=False, timeout=600):
    """One call against the shared /v1 endpoint. Returns (content, meta).

    json_object=True forces an OpenAI `response_format` JSON object (used by the
    harvester's strict-JSON drafting contract). meta carries the resolved
    endpoint/model and a rough wall-clock tok/s (includes prompt eval + network —
    not the server's pure decode rate). Raises InferenceError on any failure.
    """
    cfg = load_config()
    payload = {
        "model": model or cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as e:
        raise InferenceError(f"cannot reach inference endpoint {cfg['base_url']} — {e}")
    except json.JSONDecodeError as e:
        raise InferenceError(f"non-JSON from {cfg['base_url']} — {e}")
    elapsed = time.monotonic() - started

    try:
        content = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as e:
        raise InferenceError(f"unexpected /v1 response shape ({e}): {body}")

    usage = body.get("usage") or {}
    completion_tokens = usage.get("completion_tokens", 0)
    meta = {
        "endpoint": cfg["base_url"],
        "model": payload["model"],
        "completion_tokens": completion_tokens,
        "tok_per_s": round(completion_tokens / elapsed, 1)
                     if elapsed and completion_tokens else None,
    }
    return content, meta


if __name__ == "__main__":
    # tiny smoke test: `python3 hack/inference.py "say hi in 3 words"`
    import sys
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Reply with exactly: ok"
    try:
        out, m = chat([{"role": "user", "content": prompt}])
        print(out)
        print(f"[{m['model']} @ {m['endpoint']} — {m['tok_per_s']} tok/s]")
    except InferenceError as e:
        print(f"inference unavailable (this is non-fatal for drafting): {e}")
        sys.exit(1)
