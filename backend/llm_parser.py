import json
import os
import re
from typing import Dict, Optional

from .config import PROPERTY_SPECS, PROPERTY_KEYS


def _empty() -> Dict:
    return {
        "targets": {key: None for key in PROPERTY_KEYS},
        "weights": {key: 0.0 for key in PROPERTY_KEYS},
        "source": "rule",
    }


def _try_float_dict(obj: Dict) -> Dict:
    out = _empty()
    for key in PROPERTY_KEYS:
        try:
            if obj.get("targets", {}).get(key) is not None:
                out["targets"][key] = float(obj["targets"][key])
        except Exception:
            pass
        try:
            out["weights"][key] = float(obj.get("weights", {}).get(key, out["weights"][key]))
        except Exception:
            pass
    return out


def parse_function_by_rules(text: str) -> Dict:
    t = (text or "").lower()
    out = _empty()

    def setv(key: str, value: float, weight: float):
        out["targets"][key] = value
        out["weights"][key] = max(out["weights"].get(key, 0.0), weight)

    if any(w in t for w in ["磁", "magnet", "spin", "自旋"]):
        setv("mag_density", 0.20, 1.8)
    if any(w in t for w in ["绝缘", "透明", "光电", "半导体", "insulator", "transparent", "semiconductor"]):
        setv("band_gap", 2.0, 1.4)
    if any(w in t for w in ["硬", "刚性", "高模量", "耐压", "hard", "stiff", "modulus"]):
        setv("bulk_modulus", 180.0, 1.4)
    if any(w in t for w in ["二维", "层状", "剥离", "2d", "layered"]):
        setv("larsen_score_2d", 0.75, 1.6)
    if any(w in t for w in ["介电", "高介电", "极化", "电容", "dielectric", "permittivity", "epsilon"]):
        setv("dielectric_constant", 10.0, 1.4)
    if any(w in t for w in ["韧性", "延展", "ductile", "tough"]):
        setv("cauchy_stress", 20.0, 1.2)

    numbers = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*(?:ev|gpa|μb|mub)?", t)
    if numbers and all(v is None for v in out["targets"].values()):
        setv("band_gap", float(numbers[0]), 1.0)

    if all(w == 0 for w in out["weights"].values()):
        for spec in PROPERTY_SPECS:
            out["targets"][spec["key"]] = spec["default_target"]
            out["weights"][spec["key"]] = 0.5

    return out


def parse_function_description(text: str) -> Dict:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return parse_function_by_rules(text)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        schema = {k: "number or null" for k in PROPERTY_KEYS}
        prompt = f"""
Convert the material function description into target property values and weights.
Return strict JSON only, with keys: targets and weights.
Allowed property keys: {PROPERTY_KEYS}
Each target value should be a rough numeric value or null. Each weight should be 0 to 2.
Description: {text}
"""
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = resp.choices[0].message.content.strip()
        data = json.loads(content)
        out = _try_float_dict(data)
        out["source"] = "llm"
        return out
    except Exception:
        return parse_function_by_rules(text)
