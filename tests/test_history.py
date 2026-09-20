"""Histórico de trabalhos: gravação, leitura tolerante e apresentação."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tests_helpers import make_result

from vellum import history
from vellum.types import CoverageInfo, SegmentInfo, SummaryInfo


def _resultado(**kwargs):
    resultado = make_result()
    for chave, valor in kwargs.items():
        setattr(resultado, chave, valor)
    return resultado


def test_historico_vazio_quando_nao_ha_arquivo():
    assert history.load() == []


def test_grava_e_le_de_volta():
    entrada = history.entry_from_result(_resultado(), "C:/saida")
    history.record(entrada)

    lidas = history.load()
    assert len(lidas) == 1
    assert lidas[0].file_name == "entrada.wav"
    assert lidas[0].model == "small"
    assert lidas[0].status == "ok"
    assert lidas[0].output_dir == "C:/saida"


def test_extrai_cobertura_avisos_e_resumo():
    resultado = _resultado(
        coverage=CoverageInfo(analyzed=True, ratio=0.92, gaps=[(1.0, 5.0)], gap_seconds=4.0),
        summary=SummaryInfo(available=True, model="qwen3:14b"),
        partial_failures=["diarização: sem modelo"],
    )
    entrada = history.entry_from_result(resultado)

    assert entrada.coverage == 0.92
    assert entrada.gaps == 1
    assert entrada.gap_seconds == 4.0
    assert entrada.failures == 1
    assert entrada.summarized is True


def test_confianca_e_media_dos_segmentos():
    resultado = _resultado(
        segments=[
            SegmentInfo(id=0, start=0.0, end=1.0, text="a", avg_logprob=-0.20),
            SegmentInfo(id=1, start=1.0, end=2.0, text="b", avg_logprob=-0.40),
        ]
    )
    assert history.entry_from_result(resultado).confidence == pytest.approx(-0.30)


def test_confianca_desconhecida_quando_o_motor_nao_informa():
    assert history.mean_confidence([SegmentInfo(id=0, start=0, end=1, text="a")]) is None
    assert "desconhec" in history.confidence_label(None)


def test_rotulo_de_confianca_por_faixa():
    assert history.confidence_label(-0.10).startswith("alta")
    assert history.confidence_label(-0.50).startswith("média")
    assert history.confidence_label(-0.90).startswith("baixa")


def test_erro_tambem_vira_linha():
    history.record(history.entry_from_failure("C:/videos/reuniao.mp4", "ffmpeg sumiu\nlinha 2"))
    entrada = history.load()[0]

    assert entrada.status == "erro"
    assert entrada.file_name == "reuniao.mp4"
    assert entrada.detail == "ffmpeg sumiu"      # só a primeira linha


def test_limite_de_entradas():
    for indice in range(history.MAX_ENTRIES + 5):
        history.record(history.HistoryEntry(file_name=f"{indice}.wav"))

    entradas = history.load()
    assert len(entradas) == history.MAX_ENTRIES
    assert entradas[-1].file_name == f"{history.MAX_ENTRIES + 4}.wav"  # o mais novo ficou


def test_arquivo_corrompido_nao_derruba():
    history.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history.HISTORY_PATH.write_text("{isso não é json", encoding="utf-8")
    assert history.load() == []


def test_campo_desconhecido_de_versao_mais_nova_e_ignorado():
    history.HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    history.HISTORY_PATH.write_text(
        json.dumps([{"file_name": "a.wav", "campo_do_futuro": 1}]), encoding="utf-8"
    )
    entradas = history.load()
    assert len(entradas) == 1
    assert entradas[0].file_name == "a.wav"


def test_limpar_apaga_tudo():
    history.record(history.HistoryEntry(file_name="a.wav"))
    history.clear()
    assert history.load() == []
    history.clear()  # apagar duas vezes não pode explodir


def test_tabela_vazia_convida_a_processar():
    texto = history.format_history([])
    assert "Nenhum trabalho ainda" in texto


def test_tabela_tem_cabecalho_e_a_linha_do_trabalho():
    history.record(history.entry_from_result(_resultado(), "C:/saida"))
    texto = history.format_history(history.load())

    assert "ARQUIVO" in texto and "COBERT" in texto and "CONFIANÇA" in texto
    assert "entrada.wav" in texto
    assert "small" in texto


def test_tabela_destaca_cobertura_baixa_e_erro():
    baixa = history.entry_from_result(
        _resultado(coverage=CoverageInfo(analyzed=True, ratio=0.70, gap_seconds=30.0))
    )
    falha = history.entry_from_failure("ruim.mp4", "arquivo sem trilha de áudio")
    texto = history.format_history([baixa, falha])

    assert "O QUE MERECE UM OLHAR" in texto
    assert "70.0%" in texto
    assert "arquivo sem trilha de áudio" in texto


def test_nome_comprido_e_cortado_pelo_meio():
    nome = "reuniao_do_conselho_administrativo_2026_parte_final.mp4"
    cortado = history._cut(nome, 30)
    assert len(cortado) == 30
    assert cortado.endswith(".mp4")      # a extensão sobrevive
    assert cortado.startswith("reuniao")


def test_totais_resumem_o_conjunto():
    entradas = [
        history.HistoryEntry(status="ok", coverage=1.0, realtime_factor=2.0),
        history.HistoryEntry(status="ok", coverage=0.9, realtime_factor=4.0),
        history.HistoryEntry(status="erro"),
    ]
    resumo = history._totals(entradas)
    assert "3 trabalho(s)" in resumo
    assert "1 com erro" in resumo
    assert "95.0%" in resumo
    assert "3.0x" in resumo
