"""Quick mic level meter: run for ~8s, speak, watch the bars."""

import time

import numpy as np
import sounddevice as sd

print("default input:", sd.query_devices(kind="input")["name"])


def cb(indata, frames, t, status):
    rms = float(np.sqrt((indata**2).mean()))
    bar = "#" * int(min(rms, 0.5) * 200)
    print(f"rms={rms:.4f} {bar}", flush=True)


with sd.InputStream(channels=1, samplerate=16000, dtype="float32", callback=cb):
    time.sleep(8)
