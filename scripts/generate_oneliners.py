import json
import random
import re
import sys
import urllib.error
import urllib.request

EPISODES_JSON = "episodes.json"
REAL_OUT = "real_oneliners.txt"
GENERATED_OUT = "generated_oneliners.txt"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"
GENERATE_COUNT = 100
SEED_EXAMPLES = 25


def load_real_oneliners(json_path: str) -> list[str]:
    with open(json_path, encoding="utf-8") as f:
        episodes = json.load(f)
    oneliners = [
        e["intro"] for e in episodes
        if e.get("has_intro") and e.get("intro")
    ]
    # Deduplicate preserving order
    seen: set[str] = set()
    unique = []
    for line in oneliners:
        normalized = re.sub(r"\s+", " ", line.lower().strip())
        if normalized not in seen:
            seen.add(normalized)
            unique.append(line)
    return sorted(unique)


def build_prompt(examples: list[str], count: int) -> str:
    seed = random.sample(examples, min(SEED_EXAMPLES, len(examples)))
    seed_block = "\n".join(f"- {e}" for e in seed)
    return f"""You generate humorous one-liners for the "Soft Skills Engineering" podcast.

Format: "It takes more than [X] to be a great software engineer."

Real examples from the show (for style only — do NOT copy or paraphrase these):
{seed_block}

Rules:
- Funny and painfully relatable to software engineers
- Reference real things: AI/LLM hype, ChatGPT, Docker, Kubernetes, microservices, JIRA tickets,
  standups, technical debt, 10x engineers, stack overflow, PRs, code reviews, pair programming,
  agile ceremonies, on-call alerts at 3am, Slack notifications, npm install, git blame, etc.
- Keep [X] to one short clause or one sentence max
- Must be original — do not reuse any example above
- Output ONLY the one-liners, one per line, no numbering, no bullet points, no extra text

Generate {count} original one-liners:"""


def call_ollama(prompt: str) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "")
    except urllib.error.URLError as e:
        print(f"[ERROR] Cannot reach Ollama at {OLLAMA_URL}: {e}", file=sys.stderr)
        print("Start Ollama with: ollama serve", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"[ERROR] Ollama call failed: {e}", file=sys.stderr)
        return ""


def parse_generated(raw: str, real_set: set[str]) -> list[str]:
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        # Strip leading numbers/bullets
        line = re.sub(r"^[\d\-\*\•\.]+[\.\)\s]+", "", line).strip()
        if not line:
            continue
        # Must look like our format
        if not re.search(r"(?i)it takes more than", line):
            continue
        # Normalize to check for near-duplicates against real ones
        normalized = re.sub(r"\s+", " ", line.lower().strip())
        if normalized in real_set:
            continue
        # Ensure period at end
        if not line.endswith("."):
            line += "."
        lines.append(line)
    # Deduplicate generated
    seen: set[str] = set()
    unique = []
    for line in lines:
        norm = re.sub(r"\s+", " ", line.lower().strip())
        if norm not in seen:
            seen.add(norm)
            unique.append(line)
    return unique


def save_lines(lines: list[str], path: str, header: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {header}\n\n")
        for line in lines:
            f.write(line + "\n")


def main() -> None:
    print(f"Loading intros from {EPISODES_JSON}...", flush=True)
    real = load_real_oneliners(EPISODES_JSON)
    save_lines(real, REAL_OUT, f"{len(real)} real one-liners from Soft Skills Engineering podcast")
    print(f"Saved {len(real)} real one-liners → {REAL_OUT}", flush=True)

    real_normalized = {re.sub(r"\s+", " ", r.lower().strip()) for r in real}

    print(f"Calling Ollama ({OLLAMA_MODEL}) to generate {GENERATE_COUNT} one-liners...", flush=True)
    prompt = build_prompt(real, GENERATE_COUNT)
    raw = call_ollama(prompt)

    if not raw:
        print("No response from Ollama — skipping generated file.", flush=True)
        return

    generated = parse_generated(raw, real_normalized)
    save_lines(generated, GENERATED_OUT, f"{len(generated)} AI-generated one-liners (Ollama {OLLAMA_MODEL})")
    print(f"Saved {len(generated)} generated one-liners → {GENERATED_OUT}", flush=True)

    print("\nSample generated:")
    for line in generated[:5]:
        print(f"  {line}")


if __name__ == "__main__":
    main()
