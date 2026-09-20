"""Testes da lógica pura de diarização e alinhamento (sem modelos)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vellum.align import refine_segment_boundaries
from vellum.config import JobOptions
from vellum.diarize import (
    SpeakerTurn,
    _agglomerative,
    _chunks_from_segments,
    _merge_turns,
    assign_speakers,
    check_readiness,
    renumber_speakers,
    speaker_stats,
)
from vellum.types import SegmentInfo, WordInfo

numpy = pytest.importorskip("numpy")


# --------------------------------------------------------------------------- #
# alinhamento
# --------------------------------------------------------------------------- #
def test_alinhamento_encolhe_segmento_ate_a_primeira_e_ultima_palavra():
    segment = SegmentInfo(
        id=0,
        start=0.0,
        end=3.0,
        text="olá mundo",
        words=[WordInfo(1.2, 1.6, " olá"), WordInfo(1.6, 2.4, " mundo")],
    )
    assert refine_segment_boundaries([segment]) == 1
    assert (segment.start, segment.end) == (1.2, 2.4)


def test_alinhamento_nao_encolhe_alem_do_limite_de_seguranca():
    """Folga maior que 2 s vira suspeita de timestamp ruim: não encolhe."""
    segment = SegmentInfo(
        id=0,
        start=0.0,
        end=6.0,
        text="olá mundo",
        words=[WordInfo(1.2, 1.6, " olá"), WordInfo(1.6, 2.4, " mundo")],
    )
    refine_segment_boundaries([segment])
    assert (segment.start, segment.end) == (1.2, 6.0), "só o início cabia no limite"


def test_alinhamento_ignora_palavra_com_timestamp_absurdo():
    segment = SegmentInfo(
        id=0,
        start=0.0,
        end=30.0,
        text="olá",
        words=[WordInfo(20.0, 20.4, " olá")],  # 20 s de folga: suspeito demais
    )
    refine_segment_boundaries([segment])
    assert (segment.start, segment.end) == (0.0, 30.0)


def test_alinhamento_remove_sobreposicao_entre_segmentos():
    first = SegmentInfo(id=0, start=0.0, end=5.0, text="a")
    second = SegmentInfo(id=1, start=4.0, end=9.0, text="b")
    refine_segment_boundaries([first, second])
    assert second.start == 5.0


def test_alinhamento_sem_palavras_nao_faz_nada():
    segment = SegmentInfo(id=0, start=1.0, end=2.0, text="a")
    assert refine_segment_boundaries([segment]) == 0
    assert (segment.start, segment.end) == (1.0, 2.0)


# --------------------------------------------------------------------------- #
# atribuição de falantes
# --------------------------------------------------------------------------- #
def _dialogue() -> list[SegmentInfo]:
    return [
        SegmentInfo(id=0, start=0.0, end=4.0, text="primeira"),
        SegmentInfo(id=1, start=4.0, end=8.0, text="segunda"),
        SegmentInfo(id=2, start=8.0, end=12.0, text="terceira"),
    ]


def test_assign_speakers_usa_maior_sobreposicao():
    segments = _dialogue()
    turns = [
        SpeakerTurn(0.0, 3.9, "A"),
        SpeakerTurn(3.9, 7.5, "B"),
        SpeakerTurn(7.5, 12.0, "A"),
    ]
    assert assign_speakers(segments, turns) == 3
    assert [segment.speaker for segment in segments] == ["A", "B", "A"]


def test_assign_speakers_sem_turnos_nao_marca_nada():
    segments = _dialogue()
    assert assign_speakers(segments, []) == 0
    assert all(segment.speaker is None for segment in segments)


def test_renumber_speakers_fica_contiguo_na_ordem_de_aparicao():
    segments = _dialogue()
    segments[0].speaker = "SPEAKER_02"
    segments[1].speaker = "SPEAKER_07"
    segments[2].speaker = "SPEAKER_02"
    renumber_speakers(segments)
    assert [segment.speaker for segment in segments] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_00",
    ]


def test_speaker_stats_ordena_por_tempo():
    segments = _dialogue()
    segments[0].speaker = "SPEAKER_01"
    segments[1].speaker = "SPEAKER_00"
    segments[2].speaker = "SPEAKER_00"
    stats = speaker_stats(segments, duration=12.0)
    assert [stat.speaker for stat in stats] == ["SPEAKER_00", "SPEAKER_01"]
    assert stats[0].seconds == 8.0
    assert stats[0].ratio == pytest.approx(0.6667, abs=1e-3)


def test_merge_turns_junta_vizinhos_do_mesmo_falante():
    turns = [
        SpeakerTurn(0.0, 2.0, "A"),
        SpeakerTurn(2.1, 4.0, "A"),
        SpeakerTurn(4.0, 6.0, "B"),
    ]
    merged = _merge_turns(turns)
    assert len(merged) == 2
    assert (merged[0].start, merged[0].end, merged[0].speaker) == (0.0, 4.0, "A")


# --------------------------------------------------------------------------- #
# clusterização
# --------------------------------------------------------------------------- #
def _two_clusters():
    """Dois grupos bem separados no espaço de embeddings."""
    base_a = numpy.array([1.0, 0.0, 0.0], dtype=numpy.float32)
    base_b = numpy.array([0.0, 1.0, 0.0], dtype=numpy.float32)
    noise = numpy.array([0.02, 0.01, 0.0], dtype=numpy.float32)
    return numpy.vstack([base_a, base_a + noise, base_b, base_b + noise, base_a - noise])


def test_agglomerative_separa_dois_falantes():
    labels = _agglomerative(
        _two_clusters(), threshold=0.30, num_speakers=None, min_speakers=1, max_speakers=10
    )
    assert len(set(labels)) == 2
    assert labels[0] == labels[1] == labels[4]
    assert labels[2] == labels[3]


def test_agglomerative_respeita_num_speakers():
    labels = _agglomerative(
        _two_clusters(), threshold=0.01, num_speakers=1, min_speakers=1, max_speakers=10
    )
    assert len(set(labels)) == 1


def test_agglomerative_rotulos_seguem_ordem_de_aparicao():
    labels = _agglomerative(
        _two_clusters(), threshold=0.30, num_speakers=None, min_speakers=1, max_speakers=10
    )
    assert labels[0] == 0, "o primeiro trecho sempre recebe o rótulo 0"


def test_agglomerative_com_um_unico_trecho():
    single = numpy.array([[1.0, 0.0, 0.0]], dtype=numpy.float32)
    assert _agglomerative(
        single, threshold=0.3, num_speakers=None, min_speakers=1, max_speakers=10
    ) == [0]


def test_chunks_ignoram_segmentos_curtos_e_dividem_longos():
    segments = [
        SegmentInfo(id=0, start=0.0, end=0.3, text="curto"),
        SegmentInfo(id=1, start=1.0, end=13.0, text="longo"),
    ]
    chunks = _chunks_from_segments(segments)
    assert all(index == 1 for index, _, _ in chunks), "o segmento curto deve sair fora"
    assert len(chunks) == 3, "12 s viram 3 trechos de 4 s"
    assert chunks[0][1] == 1.0 and chunks[-1][2] == 13.0


# --------------------------------------------------------------------------- #
# disponibilidade
# --------------------------------------------------------------------------- #
def test_check_readiness_explica_backend_escolhido(tmp_path: Path):
    options = JobOptions(input_path=tmp_path, output_dir=tmp_path, models_dir=tmp_path)
    readiness = check_readiness(options)
    # O ambiente pode ou não ter torch; o contrato é a mensagem sempre existir.
    assert readiness.reason
    if readiness.ready:
        assert readiness.backend in ("pyannote", "ecapa")
