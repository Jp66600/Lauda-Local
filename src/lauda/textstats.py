"""Estatísticas locais do texto: contagens e palavras frequentes sem stopwords."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path

from .config import SUPPORTED_STOPWORD_LANGS
from .types import SegmentInfo, TextStats

log = logging.getLogger("lauda.textstats")

_RESOURCES = Path(__file__).parent / "resources" / "stopwords"

#: Palavra = sequência de letras (Unicode), aceitando hífen e apóstrofo internos.
_WORD_RE = re.compile(r"[^\W\d_]+(?:[’'-][^\W\d_]+)*", re.UNICODE)

#: Palavras muito curtas viram ruído no ranking mesmo fora da lista de stopwords.
_MIN_WORD_LEN = 3


@lru_cache(maxsize=8)
def load_stopwords(language: str | None) -> frozenset[str]:
    """Carrega a lista de stopwords do idioma; vazio se não houver lista."""
    if not language:
        return frozenset()
    code = language.lower().split("-")[0]
    if code not in SUPPORTED_STOPWORD_LANGS:
        return frozenset()
    path = _RESOURCES / f"{code}.txt"
    if not path.exists():  # pragma: no cover - instalação incompleta
        log.warning("Lista de stopwords ausente: %s", path)
        return frozenset()
    words = {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    return frozenset(words)


def tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(text)]


def _fold(word: str) -> str:
    """Remove acentos para agrupar 'está'/'esta' no ranking."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", word) if not unicodedata.combining(ch)
    )


def compute_stats(
    text: str,
    segments: list[SegmentInfo],
    *,
    language: str | None,
    duration: float | None,
    top_n: int = 25,
) -> TextStats:
    """Contagens do texto + ranking determinístico de palavras frequentes."""
    tokens = tokenize(text)
    stopwords = load_stopwords(language)
    folded_stopwords = {_fold(word) for word in stopwords}

    counter: Counter[str] = Counter()
    for token in tokens:
        if len(token) < _MIN_WORD_LEN:
            continue
        if token in stopwords or _fold(token) in folded_stopwords:
            continue
        counter[token] += 1

    # Ordem estável: frequência desc, depois alfabética -> mesmo TXT sempre.
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:top_n]

    words_per_minute = None
    if duration and duration > 0 and tokens:
        words_per_minute = round(len(tokens) / (duration / 60.0), 1)

    return TextStats(
        characters=len(text),
        characters_no_spaces=len(re.sub(r"\s+", "", text)),
        words=len(tokens),
        unique_words=len(set(tokens)),
        segments=len(segments),
        words_per_minute=words_per_minute,
        top_words=ranked,
        stopwords_language=(language.lower().split("-")[0] if language else None)
        if stopwords
        else None,
    )
