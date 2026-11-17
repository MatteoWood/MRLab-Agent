"""Measures a recorded Live session (Saved/Recordings/<time>/events.jsonl, written when bRecordSession is on).

Usage: python Tools/analyze_recording.py <recording folder>

Prints, per minute of the session: decisions per side, input tokens per decision, cost; the delay from each transcript
fragment to its decision; and where transcript fragments arrive relative to the audio they describe.
"""
import base64
import json
import statistics
import sys
from pathlib import Path

PRICE_PER_TOKEN = 0.10 / 1e6  # Decisions, gpt-6-luna, uncached input (README section 5)
RATE = 24000                  # Live API audio, samples per second
VOICE_DELAY_MS = 120          # the plugin holds Frank's voice back by this much (lip sync lookahead + margin)


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else float("nan")


def main():
    folder = Path(sys.argv[1])
    lines = [json.loads(line) for line in folder.joinpath("events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    sent_ms = 0.0       # microphone audio sent so far, in ms of audio
    received_ms = 0.0   # Frank's audio received so far
    fragments = {}      # event_id -> (arrival t, side, text)
    decisions = []      # (t, side, delay s, input tokens, cached tokens)
    in_lag = []         # visitor: arrival time minus fragment end, in ms of the session timeline
    out_lead = []       # Frank: when the fragment's audio is heard minus when its text arrived (ms; > 0: text first)

    for entry in lines:
        t, direction, msg = entry["t"], entry["d"], entry["m"]
        kind = msg.get("type", "")
        if direction == "out" and kind == "session.input_audio.append":
            sent_ms += len(base64.b64decode(msg["audio"])) / 2 / RATE * 1000
        elif direction == "in" and kind == "session.output_audio.delta":
            received_ms += len(base64.b64decode(msg["delta"])) / 2 / RATE * 1000
        elif direction == "in" and kind in ("session.input_transcript.delta", "session.output_transcript.delta"):
            user = kind.startswith("session.input")
            fragments[msg.get("event_id")] = (t, "visitor" if user else "Frank", msg.get("delta", ""))
            if "end_ms" in msg and user:
                in_lag.append(sent_ms - msg["end_ms"])
            if "start_ms" in msg and not user:
                # Frank's audio timeline = audio received; the text of a fragment starting at start_ms is heard once
                # that much audio has played (received + the plugin's delay, assuming the stream arrives in real time).
                out_lead.append(msg["start_ms"] + VOICE_DELAY_MS - received_ms)
        elif direction == "in" and kind == "decision.event":
            inner = msg.get("event", {})
            decision = inner.get("decision", {})
            usage = decision.get("usage", {})
            source = fragments.get(msg.get("source_event_id"))
            decisions.append((t, source[1] if source else "?", t - source[0] if source else None,
                              usage.get("input_tokens", 0), usage.get("input_tokens_details", {}).get("cached_tokens", 0)))

    duration = lines[-1]["t"] if lines else 0
    print(f"Session {duration / 60:.1f} min, {len(decisions)} decisions, {len(fragments)} transcript fragments")
    print("minute  visitor  Frank  tokens/decision  cached  cost/min")
    for minute in range(int(duration // 60) + 1):
        chunk = [d for d in decisions if minute * 60 <= d[0] < (minute + 1) * 60]
        if not chunk:
            continue
        tokens = sum(d[3] for d in chunk)
        cached = sum(d[4] for d in chunk)
        print(f"{minute + 1:6d}  {sum(d[1] == 'visitor' for d in chunk):7d}  {sum(d[1] == 'Frank' for d in chunk):5d}"
              f"  {tokens / len(chunk):15.0f}  {cached / max(tokens, 1):6.0%}  ${tokens * PRICE_PER_TOKEN:.4f}")
    total_tokens = sum(d[3] for d in decisions)
    print(f"total input tokens {total_tokens}, cost ${total_tokens * PRICE_PER_TOKEN:.3f} "
          f"(${total_tokens * PRICE_PER_TOKEN / max(duration / 60, 1e-9):.4f} per minute on average, uncached price)")

    for side in ("visitor", "Frank"):
        delays = [d[2] for d in decisions if d[1] == side and d[2] is not None]
        if delays:
            print(f"delay fragment -> decision, {side}: median {statistics.median(delays):.2f} s, "
                  f"90 % {pct(delays, 0.9):.2f} s, max {max(delays):.2f} s (n={len(delays)})")
    if in_lag:
        print(f"visitor fragment arrives {statistics.median(in_lag):.0f} ms after its audio was sent (median; "
              f"10-90 %: {pct(in_lag, 0.1):.0f} to {pct(in_lag, 0.9):.0f} ms)")
    if out_lead:
        print(f"Frank fragment text arrives {statistics.median(out_lead):.0f} ms before its audio is heard (median; "
              f"10-90 %: {pct(out_lead, 0.1):.0f} to {pct(out_lead, 0.9):.0f} ms; negative = after)")


if __name__ == "__main__":
    main()
