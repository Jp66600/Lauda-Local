"""Densidade das legendas (BACKLOG-034).

A regra que não pode quebrar em nenhum modo: **o texto é o mesmo**. Juntar e
partir mudam quando a legenda entra e sai, nunca o que está escrito.
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vellum.cues import (
    DENSITY_TARGETS,
    MAX_CHARS,
    MIN_CUE_SECONDS,
    build_cues,
    resolve_density,
)
from vellum.types import SegmentInfo, WordInfo


def _seg(id_, start, end, text, speaker=None, words=None):
    return SegmentInfo(
        id=id_, start=start, end=end, text=text, speaker=speaker, words=words or []
    )


def _palavras(texto: str, inicio: float, fim: float) -> list[WordInfo]:
    partes = texto.split()
    passo = (fim - inicio) / len(partes)
    return [
        WordInfo(start=inicio + i * passo, end=inicio + (i + 1) * passo, word=palavra)
        for i, palavra in enumerate(partes)
    ]


def _texto(cues) -> str:
    return " ".join(cue.text for cue in cues)


# ------------------------------------------------------------------ juntar --
def test_equilibrada_junta_trechos_curtos_seguidos():
    segmentos = [
        _seg(0, 0.0, 1.2, "Bom dia."),
        _seg(1, 1.3, 2.4, "Tudo bem?"),
        _seg(2, 2.5, 3.6, "Vamos começar."),
    ]
    cues = build_cues(segmentos, "equilibrada")

    assert len(cues) == 1, "três frases de 1 s viram uma legenda legível"
    assert cues[0].text == "Bom dia. Tudo bem? Vamos começar."
    assert (cues[0].start, cues[0].end) == (0.0, 3.6)


def test_nao_junta_atravessando_pausa_longa():
    """Legenda que atravessa silêncio fica na tela sem ninguém falando."""
    segmentos = [
        _seg(0, 0.0, 1.0, "Primeira."),
        _seg(1, 9.0, 10.0, "Segunda, muito depois."),
    ]
    cues = build_cues(segmentos, "equilibrada")

    assert len(cues) == 2
    assert cues[0].end == 1.0 and cues[1].start == 9.0


def test_nao_junta_falantes_diferentes():
    segmentos = [
        _seg(0, 0.0, 1.0, "Pergunta?", speaker="SPEAKER_00"),
        _seg(1, 1.1, 2.0, "Resposta.", speaker="SPEAKER_01"),
    ]
    cues = build_cues(segmentos, "equilibrada")

    assert len(cues) == 2
    assert [c.speaker for c in cues] == ["SPEAKER_00", "SPEAKER_01"]


def test_longa_faz_blocos_grandes():
    segmentos = [_seg(i, i * 3.0, i * 3.0 + 2.8, f"Frase {i}.") for i in range(10)]

    longa = build_cues(segmentos, "longa")
    equilibrada = build_cues(segmentos, "equilibrada")

    assert len(longa) < len(equilibrada), "é para isso que o modo existe"
    assert max(c.duration for c in longa) <= DENSITY_TARGETS["longa"][1] + 0.01


# ------------------------------------------------------------------ partir --
def test_trecho_gigante_e_partido_sem_perder_texto():
    texto = " ".join(f"palavra{i}" for i in range(60))
    cues = build_cues([_seg(0, 0.0, 30.0, texto)], "equilibrada")

    assert len(cues) > 1
    assert max(c.duration for c in cues) <= DENSITY_TARGETS["equilibrada"][1] + 0.01
    assert _texto(cues).split() == texto.split(), "nenhuma palavra pode sumir"


def test_com_tempo_das_palavras_o_corte_cai_na_palavra():
    texto = "um dois três quatro cinco seis sete oito nove dez"
    segmento = _seg(0, 0.0, 20.0, texto, words=_palavras(texto, 0.0, 20.0))

    cues = build_cues([segmento], "equilibrada")

    assert len(cues) > 1
    assert _texto(cues).split() == texto.split()
    for cue in cues:
        assert cue.start >= 0.0 and cue.end <= 20.0
        # Começo e fim vêm de palavras reais, não de regra de três.
        assert cue.words and cue.start == cue.words[0].start


def test_curta_produz_legendas_de_um_a_dois_segundos():
    texto = "um dois três quatro cinco seis sete oito nove dez onze doze"
    segmento = _seg(0, 0.0, 12.0, texto, words=_palavras(texto, 0.0, 12.0))

    cues = build_cues([segmento], "curta")

    assert len(cues) >= 6
    assert max(c.duration for c in cues) <= DENSITY_TARGETS["curta"][1] + 0.5
    assert _texto(cues).split() == texto.split()


def test_lasca_curta_demais_volta_para_a_vizinha():
    texto = "uma frase inteira aqui"
    segmentos = [
        _seg(0, 0.0, 1.5, texto),
        _seg(1, 1.6, 1.6 + MIN_CUE_SECONDS / 2, "sim"),
    ]
    cues = build_cues(segmentos, "curta")

    assert all(c.duration >= MIN_CUE_SECONDS for c in cues)
    assert "sim" in _texto(cues)


# ------------------------------------------------- invariantes de qualquer --
@pytest.mark.parametrize("densidade", ["curta", "equilibrada", "longa"])
def test_o_texto_sobrevive_em_qualquer_densidade(densidade):
    segmentos = [
        _seg(0, 0.0, 4.0, "Primeira fala mais longa do que parece."),
        _seg(1, 4.2, 6.0, "Segunda."),
        _seg(2, 12.0, 25.0, " ".join(f"p{i}" for i in range(40))),
    ]
    esperado = " ".join(s.text for s in segmentos).split()

    assert _texto(build_cues(segmentos, densidade)).split() == esperado


@pytest.mark.parametrize("densidade", ["curta", "equilibrada", "longa"])
def test_as_legendas_nao_se_sobrepoem_nem_saem_do_arquivo(densidade):
    segmentos = [
        _seg(0, 1.0, 9.0, " ".join(f"p{i}" for i in range(30))),
        _seg(1, 10.0, 14.0, "Outra fala aqui."),
    ]
    cues = build_cues(segmentos, densidade)

    assert cues[0].start >= 1.0
    assert cues[-1].end <= 14.0 + 0.01
    for anterior, seguinte in pairwise(cues):
        assert seguinte.start >= anterior.end - 0.01, "legenda não pode sobrepor legenda"


def test_densidade_desconhecida_cai_no_padrao():
    assert resolve_density("gigante") == "equilibrada"
    assert resolve_density(None) == "equilibrada"
    assert resolve_density("curta") == "curta"


def test_sem_fala_nao_ha_legenda():
    assert build_cues([], "equilibrada") == []
    assert build_cues([_seg(0, 0.0, 2.0, "   ")], "equilibrada") == []


# ------------------------------------------------------ orcamento de texto --
def test_fala_rapida_nao_estoura_a_tela():
    """Tempo não basta: cinco segundos de fala rápida enchem a legenda."""
    texto = " ".join(["palavra"] * 30)          # ~240 caracteres em 6 s
    cues = build_cues([_seg(0, 0.0, 6.0, texto)], "equilibrada")

    assert len(cues) > 1
    assert all(len(c.text) <= MAX_CHARS["equilibrada"] for c in cues)
    assert _texto(cues).split() == texto.split()


def test_juntar_respeita_o_limite_de_texto():
    segmentos = [
        _seg(0, 0.0, 1.0, "a" * 50),
        _seg(1, 1.1, 2.0, "b" * 50),
    ]
    cues = build_cues(segmentos, "equilibrada")

    assert len(cues) == 2, "juntas passariam de 84 caracteres"


@pytest.mark.parametrize("densidade", ["curta", "equilibrada"])
def test_cabe_em_duas_linhas_de_legenda(densidade):
    """A convenção é 2 linhas de ~42; acima disso o player corta ou some."""
    texto = " ".join(f"palavra{i}" for i in range(50))
    cues = build_cues([_seg(0, 0.0, 40.0, texto)], densidade)

    assert all(len(c.text) <= 2 * 42 for c in cues)


def test_modo_longo_aceita_paragrafo():
    texto = " ".join(f"palavra{i}" for i in range(40))
    cues = build_cues([_seg(0, 0.0, 50.0, texto)], "longa")

    assert len(cues) == 1, "no modo longo o texto corrido é o objetivo"


def test_o_rotulo_do_falante_conta_no_orcamento():
    """`[SPEAKER_00] ` ocupa tela; ignorá-lo estourava a segunda linha."""
    from vellum.subtitles import render_srt

    texto = "uma frase de tamanho medio que sozinha ja quase enche a legenda toda"
    cues = build_cues([_seg(0, 0.0, 6.0, texto, speaker="SPEAKER_00")], "equilibrada")

    assert all(len(c.text) <= MAX_CHARS["equilibrada"] - len("SPEAKER_00") - 3
               for c in cues)
    srt = render_srt([_seg(0, 0.0, 6.0, texto, speaker="SPEAKER_00")])
    linhas = [
        linha for linha in srt.splitlines()
        if linha and "-->" not in linha and not linha.isdigit()
    ]
    assert max(len(linha) for linha in linhas) <= 42, "nenhuma linha estoura a largura"
