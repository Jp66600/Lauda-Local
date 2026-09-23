"""Testes das partes puras: formatação, estatísticas, legendas e relatório."""

from __future__ import annotations

from lauda.report import render_plain_transcript, render_report
from lauda.subtitles import render_srt, render_vtt
from lauda.textstats import compute_stats, tokenize
from lauda.types import (
    AudioDiagnostics,
    JobResult,
    LanguageInfo,
    ProbeResult,
    ProcessingInfo,
    SegmentInfo,
    SourceInfo,
)
from lauda.utils import format_srt_time, format_timestamp, human_size, safe_stem


# --------------------------------------------------------------------------- #
# utils
# --------------------------------------------------------------------------- #
def test_format_timestamp_arredonda_em_milissegundos():
    assert format_timestamp(0) == "00:00:00.000"
    assert format_timestamp(1.2345) == "00:00:01.234"  # round-half-even
    assert format_timestamp(59.9996) == "00:01:00.000"
    assert format_timestamp(3661.5) == "01:01:01.500"
    assert format_timestamp(None) == "--:--:--.---"


def test_format_srt_time_usa_virgula():
    assert format_srt_time(72.34) == "00:01:12,340"


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(1024) == "1,00 KB"
    assert human_size(1024 ** 3) == "1,00 GB"


def test_safe_stem_remove_acentos_e_espacos():
    assert safe_stem("Entrevista Final (áudio).mp4") == "Entrevista_Final_audio_.mp4"


# --------------------------------------------------------------------------- #
# textstats
# --------------------------------------------------------------------------- #
def test_tokenize_ignora_numeros_e_pontuacao():
    assert tokenize("Olá, mundo! 123 tudo-bem?") == ["olá", "mundo", "tudo-bem"]


def test_top_words_remove_stopwords_pt():
    text = "o projeto é um projeto local e o projeto roda offline no computador local"
    stats = compute_stats(text, [], language="pt", duration=60.0, top_n=5)
    top = dict(stats.top_words)
    assert top["projeto"] == 3
    assert top["local"] == 2
    assert "o" not in top and "um" not in top
    assert stats.words_per_minute == 14.0


def test_top_words_ordem_deterministica():
    text = "beta beta alfa alfa gama"
    first = compute_stats(text, [], language="pt", duration=None, top_n=3).top_words
    second = compute_stats(text, [], language="pt", duration=None, top_n=3).top_words
    assert first == second == [("alfa", 2), ("beta", 2), ("gama", 1)]


# --------------------------------------------------------------------------- #
# legendas
# --------------------------------------------------------------------------- #
def _segments() -> list[SegmentInfo]:
    return [
        SegmentInfo(id=0, start=0.0, end=2.5, text="Primeira fala.", speaker="SPEAKER_00"),
        SegmentInfo(id=1, start=2.5, end=5.0, text="Segunda fala.", speaker="SPEAKER_01"),
    ]


def test_render_srt():
    srt = render_srt(_segments())
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,500\n[SPEAKER_00] Primeira fala.")
    assert "2\n00:00:02,500 --> 00:00:05,000" in srt


def test_render_vtt_tem_cabecalho():
    vtt = render_vtt(_segments(), with_speaker=False)
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:02.500" in vtt


# --------------------------------------------------------------------------- #
# relatório
# --------------------------------------------------------------------------- #
def _job_result() -> JobResult:
    result = JobResult(
        source=SourceInfo(
            name="entrevista.mp4",
            path="/tmp/entrevista.mp4",
            size_bytes=1048576,
            size_human="1,00 MB",
            sha256="a" * 64,
            modified_at="2026-09-04T01:00:00-03:00",
        ),
        probe=ProbeResult(format_name="mov,mp4", duration=5.0, bit_rate=128000, nb_streams=1),
        processing=ProcessingInfo(
            app_name="Lauda Local",
            app_version="0.2.0",
            engine="faster-whisper",
            engine_version="1.2.1",
            model="small",
            device="cpu",
            compute_type="int8",
            started_at="2026-09-04T01:00:00-03:00",
            finished_at="2026-09-04T01:00:10-03:00",
            elapsed_seconds=10.0,
            realtime_factor=0.5,
        ),
        language=LanguageInfo(code="pt", probability=0.98, source="auto"),
        diagnostics=AudioDiagnostics(analyzed=True, mean_volume_db=-20.0, max_volume_db=-1.0),
        text="Primeira fala. Segunda fala.",
        segments=_segments(),
    )
    result.outputs = {"report.txt": "/saida/entrevista.report.txt"}
    return result


def test_relatorio_tem_todas_as_secoes_em_ordem():
    report = render_report(_job_result())
    titles = [
        "1. IDENTIDADE DO ARQUIVO",
        "2. METADADOS TÉCNICOS",
        "3. QUALIDADE E DIAGNÓSTICO",
        "4. IDIOMA",
        "5. TRANSCRIÇÃO COMPLETA",
        "6. DIARIZAÇÃO",
        "7. ESTRUTURA E RESUMO LOCAL",
        "8. CAMADA VISUAL",
        "9. RODAPÉ",
    ]
    positions = [report.index(title) for title in titles]
    assert positions == sorted(positions), "as seções mudaram de ordem"
    assert report.startswith("=" * 78)
    assert "[00:00:00.000 → 00:00:02.500] SPEAKER_00: Primeira fala." in report


def test_relatorio_marca_blocos_indisponiveis():
    report = render_report(_job_result())
    assert "[INDISPONÍVEL] Diarização:" in report
    assert "[INDISPONÍVEL] Camada visual:" in report


def test_relatorio_formata_numeros_em_pt_br():
    report = render_report(_job_result())
    # milhar com ponto, decimal com vírgula — e um não pode virar o outro
    assert "Tamanho         : 1.048.576 bytes (1,00 MB)" in report


def test_relatorio_e_deterministico():
    assert render_report(_job_result()) == render_report(_job_result())


def test_transcricao_pura_nao_tem_cabecalho():
    plain = render_plain_transcript(_job_result())
    assert plain.strip() == "Primeira fala. Segunda fala."
