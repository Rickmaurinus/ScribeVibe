"""Interactive microphone selector — saves chosen device ID to settings.json."""
import re
import sys
import sounddevice as sd
import config

_SKIP_NAMES = {
    "microsoft sound mapper - input",
    "primary sound capture driver",
}

# WASAPI exclusive-mode aliases like "Chat Mic (Chat Mic)"
_WASAPI_ALIAS_RE = re.compile(r"^(.+) \(\1\)$", re.IGNORECASE)


def _is_junk(name: str) -> bool:
    low = name.lower()
    if "@system32" in low:
        return True
    if low in _SKIP_NAMES:
        return True
    if "pc speaker" in low or "stereo mix" in low or "with sst" in low:
        return True
    if _WASAPI_ALIAS_RE.match(name):
        return True
    return False


def get_clean_mic_list() -> list[tuple[int, str, str]]:
    """Return deduplicated (device_id, name, api_name) for real input devices.

    Deduplication is exact-name based: if the same name appears under multiple
    APIs, keep only the WASAPI entry (lowest latency), then DirectSound, then MME.
    """
    hostapis = sd.query_hostapis()
    devices = sd.query_devices()

    # Collect all valid candidates with their API info
    candidates: list[tuple[int, str, str]] = []
    for i, d in enumerate(devices):
        if d["max_input_channels"] == 0:
            continue
        name = d["name"]
        if _is_junk(name):
            continue
        api_name = hostapis[d["hostapi"]]["name"]
        candidates.append((i, name, api_name))

    # Prefer MME > DirectSound > WASAPI.
    # MME uses WinMM (not KS) internally, making it the most compatible
    # choice with PortAudio on Windows — especially for virtual/GoXLR devices.
    api_priority = {"MME": 0, "Windows DirectSound": 1, "Windows WASAPI": 2}

    # First pass: among full-name duplicates keep the highest-priority API
    best: dict[str, tuple[int, str, str]] = {}
    for i, name, api in candidates:
        key = name.lower()
        if key not in best:
            best[key] = (i, name, api)
        else:
            if api_priority.get(api, 99) < api_priority.get(best[key][2], 99):
                best[key] = (i, name, api)

    # Second pass: drop non-MME entries whose name is a longer version of an
    # already-accepted MME entry (MME names are truncated to 31 chars)
    mme_names = [n.lower() for _, n, a in best.values() if a == "MME"]
    deduped = {
        k: v for k, v in best.items()
        if v[2] == "MME" or not any(k.startswith(m) for m in mme_names)
    }

    return sorted(deduped.values(), key=lambda x: x[0])


def main() -> None:
    mics = get_clean_mic_list()

    if not mics:
        print("No valid microphones found.")
        sys.exit(1)

    print("\n--- Available Input Devices ---")
    valid_ids = set()
    for i, name, api in mics:
        api_tag = f"[*{api}*]" if api == "MME" else f"[{api}]"
        print(f"  [{i:2}]  {name[:48]:<48}  {api_tag}")
        valid_ids.add(i)
    print("-------------------------------\n")

    while True:
        raw = input("Enter device ID (or 'q' to quit): ").strip().lower()
        if raw in ("q", "quit", "exit"):
            print("Cancelled.")
            sys.exit(0)
        if raw.isdigit() and int(raw) in valid_ids:
            device_id = int(raw)
            break
        print("  Invalid ID. Please choose a number from the list above.")

    config.set_device(device_id)
    final = sd.query_devices(device_id)
    print(f"\nSaved. Active microphone: [{device_id}] {final['name']}")


if __name__ == "__main__":
    main()
