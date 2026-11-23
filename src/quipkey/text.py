"""Clean-up applied to the recognized text before it's typed."""
from __future__ import annotations

import re

FILLER_RE = re.compile(r"(?i)(?:^|(?<=[\s,.!?]))(?:um+|uh+|erm+|uhm+|hmm+|mm+)\b[,.]?\s*")


def clean_text(text: str, cfg: dict) -> str:
    text = text.strip()
    if cfg["remove_fillers"]:
        text = FILLER_RE.sub("", text).strip()
        text = re.sub(r"\s{2,}", " ", text)
        if text[:1].islower():
            text = text[0].upper() + text[1:]
    if text and cfg["trailing_space"]:
        text += " "
    return text


def short_mic_name(name: str) -> str:
    """'Microphone (6- Antlion Wireless Microphone)' -> 'Antlion Wireless Microphone'."""
    m = re.match(r"^[^()]*\((.+?)\)?\s*$", name)
    n = m.group(1) if m else name
    return re.sub(r"^\d+-\s*", "", n).strip() or name
