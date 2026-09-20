"""Cobertura da linha do tempo: o que foi transcrito e o que ficou de fora.

A pergunta que este módulo responde é simples e incômoda: *o arquivo inteiro
foi percorrido?* Sem ela, um relatório bonito pode estar escondendo dez minutos
de vídeo que ninguém leu — e não há como o usuário desconfiar, porque o texto
que existe parece correto.

O trecho não transcrito quase sempre é **silêncio**, e silêncio é sucesso: nada
a transcrever ali. Por isso um buraco só vira alerta quando não é silêncio. Os
intervalos de silêncio saem do `silencedetect`, que já roda no diagnóstico de
áudio — nenhuma passada extra de ffmpeg.
"""

from __future__ import annotations

import logging

from .types import CoverageInfo, SegmentInfo

log = logging.getLogger("vellum.coverage")

#: Buraco menor que isto é respiro entre frases, não trecho perdido.
MIN_GAP_SECONDS = 1.5

#: Fração do buraco que precisa ser silêncio para ele contar como silêncio.
SILENCE_FRACTION = 0.6

#: Abaixo disto o relatório avisa. Não é motivo para falhar o trabalho: vídeo
#: com música longa ou trecho mudo cai aqui legitimamente.
LOW_COVERAGE_RATIO = 0.95


def merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Une intervalos que se tocam ou se sobrepõem, em ordem."""
    limpos = [(inicio, fim) for inicio, fim in spans if fim > inicio]
    if not limpos:
        return []
    limpos.sort()
    unidos = [limpos[0]]
    for inicio, fim in limpos[1:]:
        ultimo_inicio, ultimo_fim = unidos[-1]
        if inicio <= ultimo_fim:
            unidos[-1] = (ultimo_inicio, max(ultimo_fim, fim))
        else:
            unidos.append((inicio, fim))
    return unidos


def invert_spans(
    spans: list[tuple[float, float]], duration: float
) -> list[tuple[float, float]]:
    """O complemento dos intervalos dentro de [0, duration]."""
    buracos: list[tuple[float, float]] = []
    cursor = 0.0
    for inicio, fim in merge_spans(spans):
        if inicio > cursor:
            buracos.append((cursor, min(inicio, duration)))
        cursor = max(cursor, fim)
        if cursor >= duration:
            break
    if cursor < duration:
        buracos.append((cursor, duration))
    return [(inicio, fim) for inicio, fim in buracos if fim > inicio]


def overlap_seconds(
    span: tuple[float, float], others: list[tuple[float, float]]
) -> float:
    """Quanto do intervalo é coberto por algum dos outros."""
    inicio, fim = span
    total = 0.0
    for outro_inicio, outro_fim in others:
        total += max(0.0, min(fim, outro_fim) - max(inicio, outro_inicio))
    return total


def analyze_coverage(
    segments: list[SegmentInfo],
    duration: float | None,
    silence_spans: list[tuple[float, float]] | None = None,
    *,
    min_gap: float = MIN_GAP_SECONDS,
) -> CoverageInfo:
    """Compara o que foi transcrito com a duração do arquivo.

    Devolve sempre um `CoverageInfo`; quando a duração é desconhecida, ele vem
    marcado como não analisado em vez de inventar um número.
    """
    if not duration or duration <= 0:
        return CoverageInfo(analyzed=False, reason="duração do arquivo desconhecida.")

    falas = merge_spans([(segment.start, segment.end) for segment in segments])
    cobertos = sum(fim - inicio for inicio, fim in falas)
    silencios = merge_spans(silence_spans or [])

    buracos: list[tuple[float, float]] = []
    for inicio, fim in invert_spans(falas, duration):
        if fim - inicio < min_gap:
            continue
        # Buraco que é quase todo silêncio não é trecho perdido: é pausa.
        if overlap_seconds((inicio, fim), silencios) >= (fim - inicio) * SILENCE_FRACTION:
            continue
        buracos.append((round(inicio, 2), round(fim, 2)))

    info = CoverageInfo(
        analyzed=True,
        duration=round(duration, 3),
        covered_seconds=round(min(cobertos, duration), 3),
        ratio=round(min(1.0, cobertos / duration), 4),
        silence_seconds=round(sum(fim - inicio for inicio, fim in silencios), 3),
        gaps=buracos,
        gap_seconds=round(sum(fim - inicio for inicio, fim in buracos), 3),
    )

    if info.ratio is not None and info.ratio < LOW_COVERAGE_RATIO and buracos:
        log.warning(
            "Cobertura de %.0f%% da linha do tempo: %d trecho(s) sem texto e sem "
            "silêncio, somando %.0f s. Veja a seção 5 do relatório.",
            info.ratio * 100, len(buracos), info.gap_seconds,
        )
    return info
