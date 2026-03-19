"""Shared audio utilities for ScribeVibe."""

import winsound


def play(path: str) -> None:
    """Play a WAV file asynchronously."""
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
