import sounddevice as sd

devices = sd.query_devices()
print("Available audio input devices:\n")
for i, device in enumerate(devices):
    if device['max_input_channels'] > 0:
        print(f"  [{i}] {device['name']}")
