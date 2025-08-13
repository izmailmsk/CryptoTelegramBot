import json
import os

translations = {}
DEFAULT_LANG = "en"

def load_translations():
    """Loads all translation files from the 'locales' directory."""
    locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
    for filename in os.listdir(locales_dir):
        if filename.endswith(".json"):
            lang_code = filename.split(".")[0]
            with open(os.path.join(locales_dir, filename), 'r', encoding='utf-8') as f:
                translations[lang_code] = json.load(f)

def get_text(key: str, lang: str) -> str:
    """
    Gets a translated string for a given key and language.
    Falls back to the default language if the key is not found in the specified language.
    Returns the key itself if not found in the default language either.
    """
    # Get the dictionary for the specified language, or an empty dict if not found
    lang_translations = translations.get(lang, {})

    # Get the translation, or fall back to the default language's translation
    text = lang_translations.get(key, translations.get(DEFAULT_LANG, {}).get(key))

    # If the key is not found in either, return the key itself as a last resort
    return text if text is not None else key
