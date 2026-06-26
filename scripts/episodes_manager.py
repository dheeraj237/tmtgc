"""
episodes_manager.py — Manage the Soft Skills Engineering episodes.json

Usage:
  python3 episodes_manager.py                        Show this help
  python3 episodes_manager.py --onboard              Add new RSS episodes to JSON
  python3 episodes_manager.py --fill-missing         Fill episodes missing intros
  python3 episodes_manager.py --onboard --fill-missing

Options:
  --model MODEL          Whisper model for Pass 1          [default: base]
  --windows W,W,...      Incremental window sizes (secs)   [default: 60,120,180,240,300]
  --enable-pass2         Run Pass 2 on Pass-1 failures     [default: off]
  --pass2-model MODEL    Whisper model for Pass 2          [default: small]
"""

import argparse
import asyncio
import concurrent.futures
import json
import re
import ssl
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

import aiohttp
from faster_whisper import WhisperModel

# ── Global defaults ──────────────────────────────────────────────────────────

JSON_PATH            = "episodes.json"
FEED_URL             = "https://softskills.audio/feed.xml"
DEFAULT_WINDOWS      = [60, 120, 180, 240, 300]   # incremental seconds per attempt
DEFAULT_MODEL_P1     = "base"
DEFAULT_MODEL_P2     = "small"
ENABLE_PASS2         = False
VAD_PARAMS_P2        = {"threshold": 0.35, "min_speech_duration_ms": 400, "min_silence_duration_ms": 800}
INITIAL_PROMPT_P2    = "It takes more than"
DOWNLOAD_CONCURRENCY = 5
TRANSCRIBE_CONCURRENCY = 2
WHISPER_WORKERS      = 2
RANGE_BUFFER         = 1.1
ITUNES_NS            = "http://www.itunes.com/dtds/podcast-1.0.dtd"

INTRO_RE = re.compile(r"(?i)(It takes more than[^.]*?to be a great (?:software )?engineer\.?)")


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class Episode:
    episode_number: int | None
    title: str
    date: str
    mp3_url: str
    file_size: int
    duration_seconds: int


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_duration(s: str) -> int:
    parts = s.strip().split(":")
    parts = (["0"] * (3 - len(parts))) + parts
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except (ValueError, IndexError):
        return 0


def parse_feed(xml_bytes: bytes) -> list[Episode]:
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    episodes: list[Episode] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        enclosure = item.find("enclosure")
        if enclosure is None:
            continue
        mp3_url = enclosure.get("url", "")
        file_size = int(enclosure.get("length", "0") or "0")
        if file_size == 0 or not mp3_url:
            continue
        pub_date = item.findtext("pubDate") or ""
        try:
            date_str = parsedate_to_datetime(pub_date).strftime("%Y-%m-%d")
        except Exception:
            date_str = pub_date
        duration_seconds = parse_duration(item.findtext(f"{{{ITUNES_NS}}}duration") or "0")
        m = re.search(r"Episode\s+(\d+)", title, re.IGNORECASE)
        episodes.append(Episode(
            episode_number=int(m.group(1)) if m else None,
            title=title,
            date=date_str,
            mp3_url=mp3_url,
            file_size=file_size,
            duration_seconds=duration_seconds,
        ))
    return episodes


def clean_title(title: str) -> str:
    return re.sub(r"(?i)^Episode\s+\d+\s*:\s*", "", title).strip()


def extract_intro(transcript: str) -> str | None:
    m = INTRO_RE.search(transcript)
    if not m:
        return None
    raw = re.sub(r"\s+", " ", m.group(1).strip())
    if not raw.endswith("."):
        raw += "."
    return raw[0].upper() + raw[1:]


# ── JSON I/O ──────────────────────────────────────────────────────────────────

def load_json(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(episodes: list[dict], path: str) -> None:
    episodes_sorted = sorted(
        episodes,
        key=lambda e: (e["episode_number"] is None, e["episode_number"] or 0),
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(episodes_sorted, f, indent=2, ensure_ascii=False)
    total = len(episodes_sorted)
    with_intro = sum(1 for e in episodes_sorted if e.get("has_intro"))
    print(f"Saved {total} episodes → {path}  ({with_intro} with intro)", flush=True)


def url_base(u: str) -> str:
    return u.split("?")[0]


# ── Audio pipeline ────────────────────────────────────────────────────────────

def calc_range_end(file_size: int, duration_seconds: int, max_seconds: int) -> int:
    if duration_seconds <= 0:
        return file_size - 1
    ratio = min((max_seconds / duration_seconds) * RANGE_BUFFER, 1.0)
    return int(file_size * ratio) - 1


async def download_partial(session, ep: Episode, dest_path: Path, sem, max_seconds: int) -> None:
    async with sem:
        range_end = calc_range_end(ep.file_size, ep.duration_seconds, max_seconds)
        headers = {"Range": f"bytes=0-{range_end}"}
        async with session.get(ep.mp3_url, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status not in (200, 206):
                raise RuntimeError(f"HTTP {resp.status}")
            dest_path.write_bytes(await resp.read())


def trim_audio(input_path: Path, output_path: Path, duration: int) -> None:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path), "-t", str(duration),
        "-acodec", "copy", "-y", str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg: {result.stderr[:300]}")


def transcribe(model: WhisperModel, audio_path: Path, **kwargs) -> str:
    segments, _ = model.transcribe(str(audio_path), language="en", vad_filter=True, **kwargs)
    return " ".join(seg.text for seg in segments).strip()


# ── Incremental processing ────────────────────────────────────────────────────

async def process_episode_incremental(
    ep, session, dl_sem, tr_sem, executor, model,
    results, counter, total, label, windows, **transcribe_kwargs
):
    loop = asyncio.get_running_loop()
    max_seconds = max(windows)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw = Path(tmpdir) / f"ep{ep.episode_number}_raw.mp3"
            trimmed = Path(tmpdir) / f"ep{ep.episode_number}_trimmed.mp3"
            await download_partial(session, ep, raw, dl_sem, max_seconds=max_seconds)

            transcript = ""
            found_at = None
            async with tr_sem:
                for window in windows:
                    await loop.run_in_executor(executor, trim_audio, raw, trimmed, window)
                    t = await loop.run_in_executor(
                        executor, lambda p=trimmed: transcribe(model, p, **transcribe_kwargs)
                    )
                    if INTRO_RE.search(t):
                        transcript = t
                        found_at = window
                        break
                    transcript = t

        results[url_base(ep.mp3_url)] = transcript
        counter["done"] = counter.get("done", 0) + 1
        if found_at:
            print(f"[{label}][{counter['done']}/{total}] ✓ intro @{found_at}s — {ep.title[:60]}", flush=True)
        else:
            print(f"[{label}][{counter['done']}/{total}]   no intro (tried {max_seconds}s) — {ep.title[:50]}", flush=True)
    except Exception as exc:
        print(f"[ERROR] Ep {ep.episode_number}: {exc}", file=sys.stderr, flush=True)


async def run_pass(
    label: str,
    episodes: list[Episode],
    model: WhisperModel,
    session: aiohttp.ClientSession,
    dl_sem, tr_sem,
    executor,
    windows: list[int],
    **transcribe_kwargs,
) -> dict[str, str]:
    results: dict[str, str] = {}
    counter: dict = {}
    total = len(episodes)
    tasks = [
        asyncio.create_task(
            process_episode_incremental(
                ep, session, dl_sem, tr_sem, executor, model,
                results, counter, total, label, windows, **transcribe_kwargs,
            )
        )
        for ep in episodes
    ]
    await asyncio.gather(*tasks)
    return results


# ── SSL helper ────────────────────────────────────────────────────────────────

def make_ssl_ctx():
    # softskills.audio certificate is missing Authority Key Identifier
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ── Fetch RSS once, reuse ─────────────────────────────────────────────────────

async def fetch_feed(ssl_ctx) -> list[Episode]:
    print("Fetching RSS feed...", flush=True)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
        async with session.get(FEED_URL, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            xml_bytes = await resp.read()
    return parse_feed(xml_bytes)


# ── Modes ─────────────────────────────────────────────────────────────────────

async def do_onboard(episodes: list[dict], rss: list[Episode], args, ssl_ctx) -> None:
    known_bases = {url_base(e["audio_url"]) for e in episodes}
    new_eps = [ep for ep in rss if url_base(ep.mp3_url) not in known_bases]

    if not new_eps:
        print("No new episodes found — JSON is up to date.", flush=True)
        return

    print(f"Found {len(new_eps)} new episode(s) to onboard.", flush=True)
    results = await _transcribe(new_eps, args, ssl_ctx, label="ONB")

    for ep in new_eps:
        transcript = results.get(url_base(ep.mp3_url), "")
        intro = extract_intro(transcript)
        episodes.append({
            "episode_number": ep.episode_number,
            "title": clean_title(ep.title),
            "intro": intro,
            "has_intro": intro is not None,
            "date_published": ep.date,
            "audio_url": ep.mp3_url,
            "transcript_excerpt": transcript[:500],
        })

    added = len(new_eps)
    found = sum(1 for ep in new_eps if extract_intro(results.get(url_base(ep.mp3_url), "")))
    print(f"Onboarded {added} episode(s), {found} with intro.", flush=True)


async def do_fill_missing(episodes: list[dict], rss: list[Episode], args, ssl_ctx) -> None:
    missing_entries = [e for e in episodes if not e.get("has_intro")]

    if not missing_entries:
        print("All episodes already have intros — nothing to do.", flush=True)
        return

    print(f"{len(missing_entries)} episode(s) missing intros.", flush=True)

    # Cross-reference with RSS to get file_size + duration for byte-range downloads
    rss_by_base = {url_base(ep.mp3_url): ep for ep in rss}
    target_eps: list[Episode] = []
    for entry in missing_entries:
        base = url_base(entry["audio_url"])
        rss_ep = rss_by_base.get(base)
        if rss_ep:
            target_eps.append(rss_ep)
        else:
            # Episode no longer in RSS feed (very old) — skip with warning
            print(f"  [SKIP] Ep {entry.get('episode_number')} not found in RSS feed", flush=True)

    if not target_eps:
        print("No episodes matched in RSS feed.", flush=True)
        return

    results = await _transcribe(target_eps, args, ssl_ctx, label="FIL")

    # Pass 2 if enabled
    if args.enable_pass2:
        p2_eps = [ep for ep in target_eps if not INTRO_RE.search(results.get(url_base(ep.mp3_url), ""))]
        if p2_eps:
            windows_str = "→".join(f"{w}s" for w in args.windows)
            print(f"\n── Pass 2: {args.pass2_model} [{windows_str}] ({len(p2_eps)} episodes) ──", flush=True)
            p2_model = WhisperModel(args.pass2_model, device="cpu", compute_type="int8")
            p2_results = await _transcribe_with_model(p2_eps, p2_model, args, ssl_ctx, label="FP2",
                                                       extra_kwargs={"vad_parameters": VAD_PARAMS_P2,
                                                                     "initial_prompt": INITIAL_PROMPT_P2})
            results.update(p2_results)
            p2_found = sum(1 for tx in p2_results.values() if INTRO_RE.search(tx))
            print(f"Pass 2: {p2_found}/{len(p2_eps)} additional intros found.", flush=True)

    # Update JSON entries in-place
    updated = found = 0
    ep_by_base = {url_base(ep.mp3_url): ep for ep in target_eps}
    for entry in episodes:
        base = url_base(entry["audio_url"])
        if base not in results:
            continue
        transcript = results[base]
        intro = extract_intro(transcript)
        entry["intro"] = intro
        entry["has_intro"] = intro is not None
        entry["transcript_excerpt"] = transcript[:500]
        updated += 1
        if intro:
            found += 1

    print(f"Updated {updated} entries — {found} new intros found.", flush=True)


# ── Transcription helpers ─────────────────────────────────────────────────────

async def _transcribe(episodes: list[Episode], args, ssl_ctx, label: str) -> dict[str, str]:
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    return await _transcribe_with_model(episodes, model, args, ssl_ctx, label=label)


async def _transcribe_with_model(
    episodes: list[Episode], model: WhisperModel, args, ssl_ctx, label: str,
    extra_kwargs: dict | None = None,
) -> dict[str, str]:
    windows_str = "→".join(f"{w}s" for w in args.windows)
    print(f"\n── {label}: {model.model_size_or_path if hasattr(model, 'model_size_or_path') else '?'} [{windows_str}] ({len(episodes)} episodes) ──", flush=True)

    dl_sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    tr_sem = asyncio.Semaphore(TRANSCRIBE_CONCURRENCY)
    kwargs = extra_kwargs or {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=WHISPER_WORKERS) as executor:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
            results = await run_pass(label, episodes, model, session, dl_sem, tr_sem, executor,
                                     windows=args.windows, **kwargs)
    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="episodes_manager.py",
        description="Manage Soft Skills Engineering episodes.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 episodes_manager.py --onboard
  python3 episodes_manager.py --fill-missing
  python3 episodes_manager.py --fill-missing --model small --windows 60,120,180
  python3 episodes_manager.py --fill-missing --enable-pass2
  python3 episodes_manager.py --onboard --fill-missing
        """,
    )
    parser.add_argument("--onboard", action="store_true",
                        help="Fetch RSS and add any new episodes to the JSON")
    parser.add_argument("--fill-missing", action="store_true", dest="fill_missing",
                        help="Transcribe episodes that are missing intros")
    parser.add_argument("--model", default=DEFAULT_MODEL_P1, metavar="MODEL",
                        help=f"Whisper model for Pass 1 (default: {DEFAULT_MODEL_P1})")
    parser.add_argument("--windows", default=",".join(str(w) for w in DEFAULT_WINDOWS),
                        metavar="W,W,...",
                        help=f"Incremental window sizes in seconds (default: {DEFAULT_WINDOWS})")
    parser.add_argument("--enable-pass2", action="store_true", dest="enable_pass2",
                        help="Run Pass 2 (small model + tuned VAD) on Pass-1 failures")
    parser.add_argument("--pass2-model", default=DEFAULT_MODEL_P2, metavar="MODEL", dest="pass2_model",
                        help=f"Whisper model for Pass 2 (default: {DEFAULT_MODEL_P2})")
    return parser


async def main(args) -> None:
    # Parse windows string → list[int]
    try:
        args.windows = [int(w.strip()) for w in args.windows.split(",")]
    except ValueError:
        print("Error: --windows must be comma-separated integers, e.g. 60,120,180", file=sys.stderr)
        sys.exit(1)

    ssl_ctx = make_ssl_ctx()
    episodes = load_json(JSON_PATH)
    print(f"Loaded {len(episodes)} episodes from {JSON_PATH}", flush=True)

    rss = await fetch_feed(ssl_ctx)
    print(f"RSS feed: {len(rss)} episodes", flush=True)

    try:
        if args.onboard:
            await do_onboard(episodes, rss, args, ssl_ctx)
        if args.fill_missing:
            await do_fill_missing(episodes, rss, args, ssl_ctx)
    finally:
        save_json(episodes, JSON_PATH)


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if not args.onboard and not args.fill_missing:
        parser.print_help()
        sys.exit(0)

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\n[Interrupted — progress saved]", file=sys.stderr)
        sys.exit(0)
