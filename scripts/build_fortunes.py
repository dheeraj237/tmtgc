#!/usr/bin/env python3
"""Generates data/tmtgc.txt from episodes.json."""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_JSON = os.path.join(SCRIPT_DIR, "..", "..", "episodes.json")
DEFAULT_OUT = os.path.join(SCRIPT_DIR, "..", "data", "tmtgc.txt")


def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON
    out_path = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT

    with open(json_path, encoding="utf-8") as f:
        episodes = json.load(f)

    seen = set()
    intros = []
    for ep in episodes:
        intro = (ep.get("intro") or "").strip()
        if intro and intro not in seen:
            seen.add(intro)
            intros.append(intro)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n%\n".join(intros))
        f.write("\n")

    print(f"Wrote {len(intros)} unique intros to {out_path}")


if __name__ == "__main__":
    main()
