#!/usr/bin/env python3
"""Смоук-тест провайдера на одном реальном фото: сквозной вызов client+parser.

  python scripts/smoke_provider.py --config configs/eval_empero.yaml --mode closed
"""
import argparse
import os
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from src.api_client import VisionLLMClient  # noqa: E402
from src.normalizer import BreedNormalizer  # noqa: E402
from src.prompt_builder import build_prompts  # noqa: E402
from src.response_parser import parse_response  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/eval_empero.yaml")
    ap.add_argument("--mode", default="closed", choices=["closed", "open", "reasoning"])
    ap.add_argument("--image", default="data/oxford/dog/pug/pug_00.jpg")
    ap.add_argument("--truth", default="Pug")
    args = ap.parse_args()

    with open(os.path.join(ROOT, args.config), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    with open(os.path.join(ROOT, "configs", "species", "dog.yaml"), encoding="utf-8") as f:
        species_cfg = yaml.safe_load(f)

    breeds = [b["name"] for b in species_cfg["breeds"]]
    client = VisionLLMClient(cfg["api"], cfg["request"])
    system, user = build_prompts(species_cfg, args.mode, breeds)
    img = os.path.join(ROOT, args.image)

    import time
    t0 = time.time()
    raw, lat = client.chat_vision(system, user, img, reasoning=(args.mode == "reasoning"))
    print(f"[smoke] {cfg['api']['model']} mode={args.mode}")
    print(f"[smoke] latency={lat:.1f}s (total {time.time()-t0:.1f}s) raw_len={len(raw)}")
    print("[smoke] raw[:600]:", raw[:600].replace("\n", " | "))
    parsed = parse_response(raw)
    print("[smoke] parsed:", parsed)
    norm = BreedNormalizer(species_cfg)
    ng = norm.normalize_guesses(parsed.get("guesses", []))
    print("[smoke] normalized:", ng)
    ok = bool(ng) and ng[0]["breed"] == args.truth
    print(f"[smoke] top1 {'CORRECT' if ok else 'WRONG'} (truth={args.truth})")


if __name__ == "__main__":
    main()
