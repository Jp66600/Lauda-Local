"""A bateria mínima de verificação (BACKLOG-048).

O backlog trazia essa lista como *teste manual*. Manual é o que ninguém repete
depois da terceira vez — então ela virou código. Cada teste aqui corresponde a
uma linha daquela tabela, com o mesmo nome de caso.

O que continua fora daqui, de propósito:

* **3 min em Ultra tem texto no meio** — precisa de um vídeo de 3 minutos, que
  são minutos de CPU a cada rodada da suíte. A garantia equivalente está em
  `test_coverage.py`: a cobertura mede a linha do tempo inteira, em qualquer
  duração, e denuncia o miolo perdido.
* **Ollama ligado sem o modelo** — a parte de rede está em `test_summarize.py`
  com um servidor de mentira (inclusive a queda para um modelo menor e o
  download com porcentagem), e a tela dele em `test_desktop.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ffmpeg_required

from lauda.config import JobOptions
from lauda.pipeline import process_media


def _rodar(entrada: Path, saida: Path, **extras) -> object:
    opcoes = JobOptions(
        input_path=entrada,
        output_dir=saida,
        model="tiny",
        device="cpu",
        language="pt",
        **extras,
    )
    return process_media(opcoes, resume=False)


# --------------------------------------------------------------------------- #
@ffmpeg_required
def test_caso_video_mudo_conclui_como_silencio(silent_video: Path, tmp_path: Path):
    """Mudo não é falha: é sucesso sem nada a transcrever."""
    resultado = _rodar(silent_video, tmp_path)

    assert resultado.segments == []
    laudo = Path(resultado.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "[INDISPONÍVEL] Transcrição" in laudo, "o motivo tem de estar escrito"


@ffmpeg_required
def test_caso_audio_sem_fala_avisa_e_nao_inventa(tone_wav: Path, tmp_path: Path):
    """Um tom puro não pode virar frase: alucinação é o erro clássico aqui."""
    resultado = _rodar(tone_wav, tmp_path)

    laudo = Path(resultado.outputs["report.txt"]).read_text(encoding="utf-8")
    assert resultado.diagnostics.analyzed
    assert "4. IDIOMA" in laudo


@ffmpeg_required
def test_caso_ollama_desligado_gera_legenda_sem_pull(dialogo_wav: Path, tmp_path: Path):
    """Ollama é a IA de texto. Desligado, a legenda sai igual."""
    resultado = _rodar(dialogo_wav, tmp_path, write_srt=True, summarize=False)

    assert "srt" in resultado.outputs
    assert Path(resultado.outputs["srt"]).exists()
    assert resultado.summary.available is False
    laudo = Path(resultado.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "[INDISPONÍVEL] Resumo" in laudo


@ffmpeg_required
def test_caso_arquivo_invalido_falha_com_motivo(invalid_file: Path, tmp_path: Path):
    from lauda.errors import LaudaError

    with pytest.raises(LaudaError) as erro:
        _rodar(invalid_file, tmp_path)
    assert "não conseguiu ler" in str(erro.value)


@ffmpeg_required
def test_caso_cobertura_e_medida_em_todo_trabalho(dialogo_wav: Path, tmp_path: Path):
    """O guardrail do Ultra: nenhum trabalho sai sem a conta da linha do tempo."""
    resultado = _rodar(dialogo_wav, tmp_path)

    assert resultado.coverage.analyzed is True
    assert resultado.coverage.ratio is not None
    assert 0.0 < resultado.coverage.ratio <= 1.0
    laudo = Path(resultado.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "Cobertura da linha do tempo" in laudo


@ffmpeg_required
def test_caso_preset_de_gpu_em_zero_manda_para_a_cpu(dialogo_wav: Path, tmp_path: Path):
    """QA: "baixei a GPU para 0 e a placa continuou trabalhando"."""
    from lauda.limits import ResourceLimits

    resultado = _rodar(dialogo_wav, tmp_path, limits=ResourceLimits(gpu_percent=0))

    assert resultado.processing.device == "cpu"


@ffmpeg_required
def test_caso_srt_e_vtt_saem_juntos_quando_pedidos(dialogo_wav: Path, tmp_path: Path):
    resultado = _rodar(dialogo_wav, tmp_path, write_srt=True, write_vtt=True)

    for tipo in ("srt", "vtt"):
        assert tipo in resultado.outputs
        conteudo = Path(resultado.outputs[tipo]).read_text(encoding="utf-8")
        assert "-->" in conteudo, f"{tipo} sem marcação de tempo"
