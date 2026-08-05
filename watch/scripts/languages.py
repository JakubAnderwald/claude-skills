#!/usr/bin/env python3
"""ISO 639-1 language codes → human-readable English names.

Used to turn whatever language tag we detect (whisper.cpp's `result.language`,
a caption track like `pl-orig`, or yt-dlp's `language` field) into something
the report can state plainly: "Polish (`pl`)". Covers the languages whisper
recognises, plus a light touch for regional variants (`pt-BR` → "Portuguese (BR)").
"""
from __future__ import annotations

import sys


LANGUAGE_NAMES: dict[str, str] = {
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "as": "Assamese",
    "az": "Azerbaijani", "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian",
    "bn": "Bengali", "bo": "Tibetan", "br": "Breton", "bs": "Bosnian",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "fi": "Finnish",
    "fo": "Faroese", "fr": "French", "gl": "Galician", "gu": "Gujarati",
    "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian", "hy": "Armenian",
    "id": "Indonesian", "is": "Icelandic", "it": "Italian", "iw": "Hebrew",
    "ja": "Japanese", "jw": "Javanese", "jv": "Javanese", "ka": "Georgian",
    "kk": "Kazakh", "km": "Khmer", "kn": "Kannada", "ko": "Korean",
    "la": "Latin", "lb": "Luxembourgish", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lv": "Latvian", "mg": "Malagasy", "mi": "Maori",
    "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi",
    "ms": "Malay", "mt": "Maltese", "my": "Burmese", "ne": "Nepali",
    "nl": "Dutch", "nn": "Norwegian Nynorsk", "no": "Norwegian", "oc": "Occitan",
    "pa": "Punjabi", "pl": "Polish", "ps": "Pashto", "pt": "Portuguese",
    "ro": "Romanian", "ru": "Russian", "sa": "Sanskrit", "sd": "Sindhi",
    "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian", "sn": "Shona",
    "so": "Somali", "sq": "Albanian", "sr": "Serbian", "su": "Sundanese",
    "sv": "Swedish", "sw": "Swahili", "ta": "Tamil", "te": "Telugu",
    "tg": "Tajik", "th": "Thai", "tk": "Turkmen", "tl": "Tagalog",
    "tr": "Turkish", "tt": "Tatar", "uk": "Ukrainian", "ur": "Urdu",
    "uz": "Uzbek", "vi": "Vietnamese", "yi": "Yiddish", "yo": "Yoruba",
    "yue": "Cantonese", "zh": "Chinese",
}

# Regional tags worth naming properly rather than as "Base (REGION)".
REGIONAL_NAMES: dict[str, str] = {
    "pt-br": "Brazilian Portuguese",
    "es-419": "Latin American Spanish",
    "zh-hans": "Chinese (Simplified)",
    "zh-hant": "Chinese (Traditional)",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
}


def normalize(code: str | None) -> str | None:
    """Clean a raw language tag: strip yt-dlp's `-orig` suffix, lowercase it."""
    if not code:
        return None
    tag = code.strip().lower()
    if tag in ("", "auto", "none", "null", "und", "unknown"):
        return None
    if tag.endswith("-orig"):
        tag = tag[: -len("-orig")]
    return tag or None


def base_code(code: str | None) -> str | None:
    """`pt-BR` → `pt`. The part whisper and the name table key on."""
    tag = normalize(code)
    return tag.split("-")[0] if tag else None


def name_for(code: str | None) -> str | None:
    """`pl` → 'Polish'. Returns None when the tag is unknown or missing."""
    tag = normalize(code)
    if not tag:
        return None
    if tag in REGIONAL_NAMES:
        return REGIONAL_NAMES[tag]
    base = tag.split("-")[0]
    name = LANGUAGE_NAMES.get(base)
    if not name:
        return None
    region = tag[len(base) + 1:]
    return f"{name} ({region.upper()})" if region else name


def describe(code: str | None) -> str:
    """Human label for a tag: 'Polish (pl)', or the bare tag when unnamed."""
    tag = normalize(code)
    if not tag:
        return "unknown"
    name = name_for(tag)
    return f"{name} ({tag})" if name else tag


def same_language(a: str | None, b: str | None) -> bool:
    """Do two tags name the same language, ignoring region? (`pt` ≈ `pt-BR`)"""
    ba, bb = base_code(a), base_code(b)
    return bool(ba and bb and ba == bb)


if __name__ == "__main__":
    for arg in sys.argv[1:] or ["pl", "pt-BR", "en-orig", "auto"]:
        print(f"{arg} → {describe(arg)}")
