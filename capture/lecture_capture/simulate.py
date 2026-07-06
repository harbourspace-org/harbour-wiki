"""Lecture simulator: stream a scripted lecture into Harbour.Wiki, no mic.

Plays a built-in multi-topic lecture through the exact same gateway path the
real recorder uses (start → 6-second event batches → flush), so you can watch
the lecture's structure form in the wiki / MCP in real time.

Event timestamps advance in lecture-time (chunk seconds apart) regardless of
how fast they are sent, so Knottra's temporal windows behave as in a real
lecture even in --fast mode.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from .config import Config, DEFAULT_CHUNK_SECONDS
from .gateway import Gateway

# A scripted lecture with a deliberate topic structure, so the fused record
# shows distinct concepts and links: definitions → representations → BFS →
# DFS → comparison/applications.
SCRIPT = [
    "Today we're going to talk about graphs, and two fundamental ways to explore them.",
    "A graph is a set of vertices connected by edges; edges can be directed or undirected.",
    "We say two vertices are adjacent when an edge connects them directly.",
    "A path is a sequence of vertices where each consecutive pair is adjacent.",
    "Before exploring a graph we need to store it, so let's look at representations.",
    "An adjacency matrix is a V by V grid where entry i j is one if there is an edge from i to j.",
    "The matrix gives constant time edge lookups but always costs V squared memory.",
    "An adjacency list instead stores, for every vertex, the list of its neighbours.",
    "For sparse graphs the adjacency list wins: memory proportional to vertices plus edges.",
    "Now the first traversal: breadth-first search, or BFS.",
    "BFS explores the graph level by level, starting from a source vertex.",
    "It uses a queue: dequeue a vertex, visit its unvisited neighbours, enqueue them.",
    "Because it expands in rings, BFS finds the shortest path in an unweighted graph.",
    "The running time of BFS is order V plus E with an adjacency list.",
    "The second traversal is depth-first search, DFS.",
    "DFS dives as deep as possible along one branch before backtracking.",
    "It uses a stack, either explicitly or through recursion.",
    "DFS naturally discovers structure: back edges reveal cycles in the graph.",
    "A topological ordering of a directed acyclic graph falls out of DFS finish times.",
    "DFS also runs in order V plus E — same asymptotic cost as BFS.",
    "So when do you choose which? BFS when you need shortest unweighted paths or levels.",
    "DFS when you need cycle detection, topological sort, or connected components.",
    "Both are the backbone of almost every graph algorithm you will meet later.",
    "Next lecture we add edge weights and meet Dijkstra's algorithm, which generalizes BFS.",
]


def _build_config(argv: list[str] | None) -> tuple[Config, float]:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="lecture-simulate",
        description="Stream a scripted lecture into Harbour.Wiki (no microphone).",
    )
    parser.add_argument("--class", dest="class_id", required=True, help="Course id to record into")
    parser.add_argument("--class-title", default=None, help="Course title (first creation)")
    parser.add_argument("--lecture-title", default="Graphs: BFS & DFS (simulated)")
    parser.add_argument("--new-lecture", action="store_true", help="Force a new lecture")
    parser.add_argument(
        "--base-url",
        default=os.getenv("HARBOUR_WIKI_BASE_URL", "http://127.0.0.1:3000"),
        help="Harbour.Wiki base URL (env HARBOUR_WIKI_BASE_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("CAPTURE_TOKEN", ""),
        help="Capture token (env CAPTURE_TOKEN)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_CHUNK_SECONDS,
        help="Real seconds between sends (default 6 = lecture pace)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Send quickly (0.5s between events); lecture-time spacing is kept",
    )
    args = parser.parse_args(argv)

    cfg = Config(
        base_url=args.base_url.rstrip("/"),
        token=args.token or None,
        class_id=args.class_id,
        class_title=args.class_title,
        lecture_title=args.lecture_title,
        force_new=args.new_lecture,
        model_size="-",  # unused: no transcription in the simulator
        chunk_seconds=DEFAULT_CHUNK_SECONDS,
        language=None,
        device=None,
    )
    return cfg, (0.5 if args.fast else args.interval)


def main(argv: list[str] | None = None) -> int:
    cfg, interval = _build_config(argv)
    gateway = Gateway(cfg)

    print(f"[simulate] class '{cfg.class_id}' — asking {cfg.base_url} …", flush=True)
    try:
        started = gateway.start()
    except requests.RequestException as error:
        print(f"[simulate] could not reach Harbour.Wiki: {error}", file=sys.stderr, flush=True)
        return 1
    verb = "resuming" if started.resumed else "starting"
    print(f"[simulate] {verb} lecture #{started.lecture} (session {started.session})", flush=True)
    print(
        f"[simulate] {len(SCRIPT)} chunks, one every {interval:g}s — watch the course page "
        "or poll get_lecture_updates while it runs. Ctrl+C stops early (still flushes).",
        flush=True,
    )

    # Lecture-time clock: chunks are chunk_seconds apart regardless of send pace.
    lecture_clock = datetime.now(timezone.utc)
    sent = 0
    try:
        for line in SCRIPT:
            gateway.send_speech(line, 0.93, lecture_clock)
            sent += 1
            print(f"[{sent:>3}/{len(SCRIPT)}] {line}", flush=True)
            lecture_clock += timedelta(seconds=cfg.chunk_seconds)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[simulate] stopped early …", flush=True)
    except requests.RequestException as error:
        print(f"[simulate] send failed: {error}", file=sys.stderr, flush=True)

    try:
        gateway.flush()
        print(
            f"[simulate] lecture #{started.lecture} finalized ({sent} events). "
            "Fusion finishes in the background — open the course page.",
            flush=True,
        )
    except requests.RequestException as error:
        print(f"[simulate] flush failed: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
