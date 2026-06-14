"""
Thin client over the Google Gemini API — used ONLY to narrate an optimizer
result, never to compute one.

Boundary (deliberate, and load-bearing for the platform's honesty claim):
  * the optimizer picks the plan by exhaustive simulation (m1_crowd/optimizer.py);
  * this module turns that finished result into a short control-room brief.

So the decision path stays algorithmic. If the key is missing or the call fails,
the endpoint still returns the full recommendation — the brief just falls back to
a deterministic template. The demo therefore never depends on a network call.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings

log = logging.getLogger("railsetu.gemini")

SYSTEM = """You are a station control-room advisor for Indian Railways.

You are given the RESULT of a pedestrian-flow optimisation that has ALREADY been
computed by an exhaustive simulation. Your job is to explain it to a duty
controller who must act in the next few minutes.

Rules:
- Use ONLY the numbers given. Never invent or estimate a figure.
- Be direct and operational. No preamble, no restating the question.
- 3 short paragraphs, plain prose, no markdown headers or bullets:
  1. What the recommended measure is, and the effect in numbers.
  2. WHY it works — the physical mechanism (back-pressure, choke-point
     capacity, queue relocation).
  3. One caution or thing to watch while executing it.
- Under 140 words total.
- Never claim lives saved or predict a real-world outcome. This is a model.
"""


class GeminiError(RuntimeError):
    """Gemini could not be reached or returned an unusable response."""


class GeminiClient:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def configured(self) -> bool:
        return bool(self.s.gemini_api_key)

    def health(self) -> dict:
        return {
            "client": "GeminiClient",
            "configured": self.configured,
            "model": self.s.gemini_model if self.configured else None,
        }

    def brief(self, prompt: str) -> str:
        if not self.configured:
            raise GeminiError("no GEMINI api key configured")

        url = (
            f"{self.s.gemini_base_url}/v1beta/models/"
            f"{self.s.gemini_model}:generateContent"
        )
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,          # explanatory, not creative
                "maxOutputTokens": self.s.gemini_max_tokens,
            },
        }
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={"x-goog-api-key": self.s.gemini_api_key},
                timeout=self.s.gemini_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response is not None else ""
            raise GeminiError(f"HTTP {e.response.status_code}: {body}") from e
        except Exception as e:  # noqa: BLE001 — surface one typed error upward
            raise GeminiError(str(e)) from e

        # Response shape varies (safety blocks, empty candidates) — be defensive.
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError):
            raise GeminiError(f"unexpected response shape: {str(data)[:200]}")

        if not text:
            raise GeminiError("empty completion")
        return text


def build_prompt(result: dict, scenario_title: str) -> str:
    """Render the optimizer output as the factual context for the brief."""
    b, r, i = result["baseline"], result["recommended"], result["impact"]
    lines = [
        f"SCENARIO: {scenario_title}",
        "",
        "NO ACTION (baseline):",
        f"  peak density {b['peak_density']} p/m2 (LOS {b['peak_los']}), "
        f"{b['crush_count']} crush points, worst node {b['worst_node']}, "
        f"{b['cleared']} people cleared",
        "",
        "RECOMMENDED PLAN (chosen by exhaustive simulation of all 16 combinations):",
        f"  measures: {', '.join(r['labels']) or 'none'}",
        f"  peak density {r['peak_density']} p/m2 (LOS {r['peak_los']}), "
        f"{r['crush_count']} crush points, worst node {r['worst_node']}, "
        f"{r['cleared']} people cleared",
        f"  change: peak {i['peak_before']} -> {i['peak_after']} "
        f"({i['peak_reduction_pct']}% reduction), "
        f"crush {i['crush_before']} -> {i['crush_after']}, "
        f"throughput {i['cleared_before']} -> {i['cleared_after']}",
        "",
        "EACH MEASURE ON ITS OWN (for context on why the others were not chosen):",
    ]
    for p in result["single_levers"]:
        lines.append(
            f"  {', '.join(p['labels'])}: peak {p['peak_density']} p/m2 "
            f"(LOS {p['peak_los']}), {p['crush_count']} crush points, "
            f"worst node {p['worst_node']}, {p['cleared']} cleared"
        )
    lines += [
        "",
        "NOTE: density is persons per square metre on the Fruin Level-of-Service "
        "scale; 5.0 and above is the crush regime. Identical 'cleared' figures "
        "between two plans mean throughput was unchanged.",
        "",
        "Write the control-room brief.",
    ]
    return "\n".join(lines)


def fallback_brief(result: dict) -> str:
    """Deterministic brief used when Gemini is unconfigured or unreachable.

    Same facts, no network. Keeps the button useful on a dead conference wifi.
    """
    r, i = result["recommended"], result["impact"]
    if not r["active"]:
        return (
            f"No intervention is required. Peak density stays at "
            f"{i['peak_after']} p/m² (LOS {r['peak_los']}) with "
            f"{r['crush_count']} crush points; flow is within safe limits."
        )

    measures = " + ".join(r["labels"])
    txt = (
        f"Apply {measures}. Modelled peak density falls from {i['peak_before']} "
        f"to {i['peak_after']} p/m² ({i['peak_reduction_pct']}% reduction) and "
        f"crush points go {i['crush_before']} → {i['crush_after']}. "
    )
    if i["cleared_after"] >= i["cleared_before"]:
        txt += (
            f"Throughput is not reduced ({i['cleared_before']} → "
            f"{i['cleared_after']} cleared), so the crush is removed at no cost "
            f"to how fast the station empties. "
        )
    txt += (
        "The mechanism is back-pressure: holding people in roomy areas and "
        "releasing them at the rate the stairs can actually pass stops the "
        "landing from packing beyond its capacity. "
        f"Chosen by exhaustive simulation of all {result['evaluated']} "
        "mitigation combinations."
    )
    return txt
