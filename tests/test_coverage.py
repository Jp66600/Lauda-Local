"""Cobertura da linha do tempo.

O caso que estes testes existem para pegar: o relatório sai bonito, com texto
correto, e mesmo assim dez minutos do vídeo nunca foram lidos. Sem uma medida
explícita, não há como o usuário desconfiar.
"""

from __future__ import annotations

import logging

from lauda.coverage import (
    analyze_coverage,
    invert_spans,
    merge_spans,
    overlap_seconds,
)
from lauda.types import SegmentInfo


def seg(start: float, end: float) -> SegmentInfo:
    return SegmentInfo(id=0, start=start, end=end, text="texto")


# ------------------------------------------------------------- as primitivas
def test_intervalos_que_se_tocam_viram_um():
    assert merge_spans([(0, 5), (4, 8), (20, 22)]) == [(0, 8), (20, 22)]


def test_intervalo_invertido_e_o_que_sobra():
    assert invert_spans([(2, 5)], duration=10) == [(0.0, 2), (5, 10)]
    assert invert_spans([], duration=10) == [(0.0, 10)]
    assert invert_spans([(0, 10)], duration=10) == []


def test_sobreposicao_soma_so_o_que_encosta():
    assert overlap_seconds((0, 10), [(2, 4), (8, 20)]) == 4.0
    assert overlap_seconds((0, 10), [(50, 60)]) == 0.0


# --------------------------------------------------------------- a medida
def test_arquivo_inteiro_transcrito():
    info = analyze_coverage([seg(0, 30)], duration=30)

    assert info.analyzed is True
    assert info.ratio == 1.0
    assert info.gaps == []


def test_o_miolo_perdido_vira_buraco():
    """O sintoma relatado no QA: texto no começo e no fim, nada no meio."""
    info = analyze_coverage([seg(0, 10), seg(80, 90)], duration=90)

    assert info.gaps == [(10.0, 80.0)]
    assert info.gap_seconds == 70.0
    assert info.ratio is not None and info.ratio < 0.25


def test_silencio_nao_e_buraco():
    """Pausa é sucesso: não há o que transcrever ali."""
    info = analyze_coverage(
        [seg(0, 10), seg(80, 90)], duration=90, silence_spans=[(10, 80)]
    )

    assert info.gaps == [], "o miolo era silêncio medido, não trecho perdido"
    assert info.silence_seconds == 70.0


def test_silencio_parcial_ainda_conta_como_buraco():
    """Metade do buraco em silêncio não absolve o resto."""
    info = analyze_coverage(
        [seg(0, 10), seg(80, 90)], duration=90, silence_spans=[(10, 40)]
    )

    assert info.gaps == [(10.0, 80.0)]


def test_respiro_entre_frases_nao_conta():
    info = analyze_coverage([seg(0, 10), seg(10.8, 30)], duration=30)

    assert info.gaps == [], "0,8 s entre frases é respiro, não trecho perdido"


def test_sem_duracao_nao_inventa_numero():
    info = analyze_coverage([seg(0, 10)], duration=None)

    assert info.analyzed is False
    assert info.ratio is None
    assert "duração" in info.reason


def test_cobertura_baixa_avisa_no_log(caplog):
    """É o guardrail: o trecho perdido tem de gritar em algum lugar."""
    with caplog.at_level(logging.WARNING, logger="lauda.coverage"):
        analyze_coverage([seg(0, 10), seg(80, 90)], duration=90)

    assert any("Cobertura" in registro.message for registro in caplog.records)


def test_cobertura_boa_nao_polui_o_log(caplog):
    with caplog.at_level(logging.WARNING, logger="lauda.coverage"):
        analyze_coverage([seg(0, 30)], duration=30)

    assert caplog.records == []


def test_segmentos_sobrepostos_nao_inflam_a_conta():
    """Somar durações contaria a sobreposição duas vezes e passaria de 100%."""
    info = analyze_coverage([seg(0, 20), seg(15, 30)], duration=30)

    assert info.covered_seconds == 30.0
    assert info.ratio == 1.0


# --------------------------------------------------------------------------- #
# Fim a fim: o buraco plantado tem de aparecer no laudo
# --------------------------------------------------------------------------- #
def test_o_buraco_plantado_aparece_no_relatorio():
    """Critério de aceite: apagar um trecho do merge tem de ficar visível.

    Reproduz o sintoma relatado no QA — texto nas pontas, nada no meio — e
    verifica que o relatório o denuncia em vez de parecer completo.
    """
    from tests_helpers import make_result

    from lauda.report import render_report

    resultado = make_result()
    resultado.probe.duration = 90.0
    resultado.segments = [seg(0, 10), seg(80, 90)]
    resultado.coverage = analyze_coverage(resultado.segments, 90.0)

    laudo = render_report(resultado)

    assert "Cobertura da linha do tempo" in laudo
    assert "22.2% do arquivo" in laudo
    assert "00:00:10" in laudo and "00:01:20" in laudo, "o intervalo do buraco"


def test_relatorio_sem_medida_diz_por_que():
    """Bloco que falha vira [INDISPONÍVEL] com o motivo, nunca some."""
    from tests_helpers import make_result

    from lauda.report import render_report

    resultado = make_result()
    resultado.coverage = analyze_coverage(resultado.segments, duration=None)

    laudo = render_report(resultado)
    assert "[INDISPONÍVEL] Cobertura" in laudo
