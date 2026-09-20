"""Densidade das legendas: de que tamanho cada cue deve ser (BACKLOG-034).

O QA reclamou de duas coisas opostas: em qualidade baixa saía **uma legenda só**
para o vídeo inteiro, e em qualidade alta ele queria legendas curtas, quase
palavra a palavra. As duas queixas têm a mesma raiz — o tamanho da legenda era
consequência acidental de como o modelo cortou os trechos, e nunca uma escolha.

Aqui vira escolha, com três alvos:

* **longa**       — blocos de até ~60 s. Para quem quer o texto corrido dentro
  do player, não legenda de verdade.
* **equilibrada** — 5 a 8 s, cortando em pausa quando dá. É o padrão, e é o que
  se espera de uma legenda.
* **curta**       — 1 a 2 s, para edição fina e karaokê. Usa o tempo das
  palavras quando ele existe.

Três regras valem para os três alvos, e são o motivo deste módulo existir:

1. **Nenhum texto se perde.** Juntar ou partir muda onde a legenda começa e
   termina, nunca o que está escrito.
2. **Nada é inventado no silêncio.** Só juntamos trechos separados por pausas
   curtas; pausa longa continua pausa, e a legenda some — o que a `coverage.py`
   mede como sucesso, não como buraco.
3. **Falantes não se misturam.** Duas pessoas nunca caem na mesma legenda.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .types import SegmentInfo, WordInfo

log = logging.getLogger("vellum.cues")

#: Alvo de duração (mínimo desejável, máximo aceitável) em segundos.
DENSITY_TARGETS: dict[str, tuple[float, float]] = {
    "longa": (30.0, 60.0),
    "equilibrada": (5.0, 8.0),
    "curta": (1.0, 2.0),
}

#: Maior pausa que ainda deixa juntar dois trechos, por densidade. Quem pediu
#: blocos longos aceita atravessar uma respirada; quem pediu curto, não.
JOIN_GAP: dict[str, float] = {"longa": 4.0, "equilibrada": 2.0, "curta": 0.8}

#: Quanto texto cabe numa legenda, por densidade. Tempo não basta como critério:
#: uma fala rápida enche a tela em 5 s. A convenção de legendagem é de duas
#: linhas de ~42 caracteres — daí os 84 do modo equilibrado. O modo longo não é
#: legenda de verdade (é o texto corrido dentro do player) e ganha um parágrafo.
MAX_CHARS: dict[str, int] = {"longa": 600, "equilibrada": 84, "curta": 60}

#: Linhas que a legenda pode ocupar na tela, pela mesma razão. O teto do modo
#: longo é o que cabe nos 600 caracteres: nada de espremer dez linhas numa só.
MAX_LINES: dict[str, int] = {"longa": 15, "equilibrada": 2, "curta": 2}

DEFAULT_DENSITY = "equilibrada"

#: Rótulos para a interface e para a CLI.
DENSITY_LABELS: list[tuple[str, str]] = [
    ("Legendas curtas (1–2 s)", "curta"),
    ("Equilibrada (5–8 s)", "equilibrada"),
    ("Blocos longos (até 1 min)", "longa"),
]

#: Piso de duração de uma legenda. Abaixo disso ninguém lê.
MIN_CUE_SECONDS = 0.4


@dataclass
class Cue:
    """Uma legenda pronta: quando entra, quando sai e o que está escrito."""

    start: float
    end: float
    text: str
    speaker: str | None = None
    words: list[WordInfo] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def resolve_density(name: str | None) -> str:
    """Aceita o que reconhece; qualquer outra coisa cai no padrão."""
    if name in DENSITY_TARGETS:
        return name
    if name:
        log.debug("Densidade de legenda desconhecida (%r); usando o padrão.", name)
    return DEFAULT_DENSITY


def _budget(cue: Cue, max_chars: int) -> int:
    """Orçamento de texto desta legenda, já descontado o rótulo do falante.

    `[SPEAKER_00] ` ocupa treze caracteres da tela como qualquer outro texto.
    Ignorá-lo era o que fazia a segunda linha estourar a largura.
    """
    if not cue.speaker:
        return max_chars
    return max(20, max_chars - (len(cue.speaker) + 3))


def _from_segment(segment: SegmentInfo) -> Cue:
    return Cue(
        start=segment.start,
        end=segment.end,
        text=segment.text.strip(),
        speaker=segment.speaker,
        words=[palavra for palavra in segment.words if palavra.word.strip()],
    )


def _join(
    cues: list[Cue], minimo: float, maximo: float, gap: float, max_chars: int
) -> list[Cue]:
    """Junta legendas curtas demais, sem atravessar pausa nem trocar de falante."""
    resultado: list[Cue] = []
    for cue in cues:
        if not resultado:
            resultado.append(cue)
            continue
        anterior = resultado[-1]
        pausa = cue.start - anterior.end
        juntas = cue.end - anterior.start
        cabe = len(anterior.text) + len(cue.text) + 1 <= _budget(anterior, max_chars)
        if (
            anterior.duration < minimo
            and pausa <= gap
            and juntas <= maximo
            and cabe
            and anterior.speaker == cue.speaker
        ):
            anterior.end = cue.end
            anterior.text = f"{anterior.text} {cue.text}".strip()
            anterior.words = [*anterior.words, *cue.words]
        else:
            resultado.append(cue)
    return resultado


def _split_by_words(cue: Cue, maximo: float, max_chars: int) -> list[Cue]:
    """Parte pelo tempo real das palavras — o corte cai onde a fala respira."""
    pedacos: list[Cue] = []
    atual: list[WordInfo] = []
    letras = 0
    for palavra in cue.words:
        tamanho = len(palavra.word.strip()) + 1
        longo_demais = atual and (palavra.end - atual[0].start) > maximo
        cheio_demais = atual and letras + tamanho > max_chars
        if longo_demais or cheio_demais:
            pedacos.append(_cue_de_palavras(atual, cue.speaker))
            atual = []
            letras = 0
        atual.append(palavra)
        letras += tamanho
    if atual:
        pedacos.append(_cue_de_palavras(atual, cue.speaker))
    return pedacos or [cue]


def _cue_de_palavras(palavras: list[WordInfo], speaker: str | None) -> Cue:
    return Cue(
        start=palavras[0].start,
        end=palavras[-1].end,
        text=" ".join(p.word.strip() for p in palavras).strip(),
        speaker=speaker,
        words=list(palavras),
    )


def _split_evenly(cue: Cue, maximo: float, max_chars: int) -> list[Cue]:
    """Sem tempo por palavra, reparte o texto em partes iguais no tempo.

    É aproximação, e assumida como tal: ninguém fala em ritmo constante. Ainda
    assim é melhor que uma legenda de meio minuto na tela — e quem precisa de
    precisão liga "marcar o tempo das palavras".
    """
    palavras = cue.text.split()
    if len(palavras) < 2:
        return [cue]

    # Quantas palavras cabem no tempo de uma legenda, no ritmo deste trecho.
    por_segundo = len(palavras) / cue.duration if cue.duration > 0 else 0.0
    por_tempo = max(1, int(maximo * por_segundo)) if por_segundo else len(palavras)

    grupos: list[list[str]] = []
    atual: list[str] = []
    letras = 0
    for palavra in palavras:
        tamanho = len(palavra) + 1
        if atual and (letras + tamanho > max_chars or len(atual) >= por_tempo):
            grupos.append(atual)
            atual = []
            letras = 0
        atual.append(palavra)
        letras += tamanho
    if atual:
        grupos.append(atual)
    if len(grupos) == 1:
        return [cue]

    # O tempo de cada pedaço é proporcional a quantas palavras ele levou.
    pedacos: list[Cue] = []
    inicio = cue.start
    consumidas = 0
    for indice, grupo in enumerate(grupos):
        consumidas += len(grupo)
        fim = (
            cue.end if indice == len(grupos) - 1
            else cue.start + cue.duration * consumidas / len(palavras)
        )
        pedacos.append(
            Cue(start=inicio, end=fim, text=" ".join(grupo), speaker=cue.speaker)
        )
        inicio = fim
    return pedacos


def _merge_slivers(cues: list[Cue]) -> list[Cue]:
    """Devolve ao vizinho as lascas curtas demais para serem lidas."""
    resultado: list[Cue] = []
    for cue in cues:
        if resultado and cue.duration < MIN_CUE_SECONDS and (
            cue.start - resultado[-1].end
        ) <= JOIN_GAP["curta"] and resultado[-1].speaker == cue.speaker:
            anterior = resultado[-1]
            anterior.end = max(anterior.end, cue.end)
            anterior.text = f"{anterior.text} {cue.text}".strip()
            anterior.words = [*anterior.words, *cue.words]
        else:
            resultado.append(cue)
    return resultado


def build_cues(segments: list[SegmentInfo], density: str | None = None) -> list[Cue]:
    """Transforma os trechos da transcrição em legendas do tamanho pedido."""
    alvo = resolve_density(density)
    minimo, maximo = DENSITY_TARGETS[alvo]
    gap = JOIN_GAP[alvo]
    max_chars = MAX_CHARS[alvo]

    cues = [_from_segment(s) for s in segments if s.text.strip()]
    if not cues:
        return []

    cues = _join(cues, minimo, maximo, gap, max_chars)

    partidas: list[Cue] = []
    for cue in cues:
        cabe = _budget(cue, max_chars)
        # Tempo não basta: fala rápida enche a tela antes de o relógio virar.
        if cue.duration <= maximo and len(cue.text) <= cabe:
            partidas.append(cue)
        elif cue.words:
            partidas.extend(_split_by_words(cue, maximo, cabe))
        else:
            partidas.extend(_split_evenly(cue, maximo, cabe))

    return _merge_slivers([cue for cue in partidas if cue.text.strip()])
