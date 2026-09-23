"""Refinamento dos limites de tempo dos segmentos (etapa `align`).

O que esta etapa faz: quando existem timestamps por palavra, encolhe o início e
o fim de cada segmento até a primeira/última palavra falada e elimina
sobreposições entre segmentos vizinhos. Isso melhora legenda e diarização sem
custo perceptível.

O que ela NÃO faz: alinhamento forçado com wav2vec2 (o que o WhisperX faz).
Isso exigiria mais ~1 GB de modelo por idioma para um ganho pequeno sobre os
timestamps por palavra que o próprio Whisper já entrega, então ficou de fora
por decisão de projeto — e não por esquecimento.
"""

from __future__ import annotations

import itertools
import logging

from .types import SegmentInfo

log = logging.getLogger("lauda.align")

#: Não encolhe mais que isto: proteção contra palavra com timestamp esquisito.
_MAX_TRIM_SECONDS = 2.0
#: Duração mínima de um segmento depois do ajuste.
_MIN_SEGMENT_SECONDS = 0.08


def refine_segment_boundaries(segments: list[SegmentInfo]) -> int:
    """Ajusta início/fim dos segmentos in-place. Devolve quantos mudaram."""
    changed = 0
    for segment in segments:
        if not segment.words:
            continue
        words = [word for word in segment.words if word.end > word.start]
        if not words:
            continue

        first, last = words[0].start, words[-1].end
        new_start = segment.start
        new_end = segment.end
        if 0.0 < first - segment.start <= _MAX_TRIM_SECONDS:
            new_start = round(first, 3)
        if 0.0 < segment.end - last <= _MAX_TRIM_SECONDS:
            new_end = round(last, 3)

        if new_end - new_start < _MIN_SEGMENT_SECONDS:
            continue
        if (new_start, new_end) != (segment.start, segment.end):
            segment.start, segment.end = new_start, new_end
            changed += 1

    changed += _remove_overlaps(segments)
    if changed:
        log.debug("Alinhamento ajustou %d limite(s) de segmento.", changed)
    return changed


def _remove_overlaps(segments: list[SegmentInfo]) -> int:
    """Empurra o início de um segmento que invade o anterior."""
    fixed = 0
    for previous, current in itertools.pairwise(segments):
        if current.start < previous.end:
            candidate = round(previous.end, 3)
            if current.end - candidate >= _MIN_SEGMENT_SECONDS:
                current.start = candidate
                fixed += 1
    return fixed
