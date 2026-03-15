"""
Phase 3 test — toggle hotkeys and audio feedback.

F13 (first press) → STARTED RECORDING (ENGLISH) + start beep
F13/F14 (second press) → STOPPED RECORDING + stop beep + done beep

Press Ctrl+C to exit.
"""
import interface


def on_start(language: str) -> None:
    pass  # printing and audio are handled inside HotkeyListener


def on_stop(audio_data) -> None:
    pass  # printing and audio are handled inside HotkeyListener


if __name__ == "__main__":
    listener = interface.HotkeyListener(on_start=on_start, on_stop=on_stop)
    listener.start()
    print("Listening for F13 (English) and F14 (Dutch)... Press Ctrl+C to quit.\n")
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        print("\nExiting.")
