"""Interactive model size selector — saves per-language choices to settings.json."""
import sys
import config

EN_MODELS = {
    "1": ("base.en",   "Fast, lower accuracy (~1 GB VRAM)"),
    "2": ("small.en",  "Balanced speed and accuracy (~2 GB VRAM)"),
    "3": ("medium.en", "Best accuracy, slower (~4 GB VRAM)"),
}

NL_MODELS = {
    "1": ("base",   "Fast, lower accuracy (~1 GB VRAM)"),
    "2": ("small",  "Balanced speed and accuracy (~2 GB VRAM)"),
    "3": ("medium", "Best accuracy, slower (~4 GB VRAM)"),
}


def _pick(label: str, models: dict, current: str) -> str | None:
    print(f"\n--- {label} ---")
    print("Larger models are more accurate but take longer to load and process.\n")
    for key, (name, desc) in models.items():
        marker = " <-- active" if name == current else ""
        print(f"  [{key}] {name:<10} — {desc}{marker}")
    print()
    while True:
        raw = input(f"Select {label} model (1-3, or 'q' to skip): ").strip().lower()
        if raw in ("q", "quit", "exit", ""):
            return None
        if raw in models:
            return models[raw][0]
        print("  Invalid choice. Enter 1, 2, or 3.")


def main() -> None:
    cfg = config.load()
    current_en = cfg.get("model_size_en", "small.en")
    current_nl = cfg.get("model_size_nl", "small")

    print(f"\nCurrent models:  English = {current_en}  |  Dutch = {current_nl}")

    choice_en = _pick("English (F13)", EN_MODELS, current_en)
    if choice_en:
        config.set_model_size_en(choice_en)
        print(f"  English model set to: {choice_en}")

    choice_nl = _pick("Dutch (F14)", NL_MODELS, current_nl)
    if choice_nl:
        config.set_model_size_nl(choice_nl)
        print(f"  Dutch model set to: {choice_nl}")

    final = config.load()
    print(f"\nFinal:  English = {final['model_size_en']}  |  Dutch = {final['model_size_nl']}")
    print("Models swap automatically when you switch languages — no restart needed.")


if __name__ == "__main__":
    main()
