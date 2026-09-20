"""Smoke tests do pipeline: áudio sintético, vídeo mudo e arquivo inválido.

Os testes que carregam o modelo Whisper só rodam com VELLUM_TEST_ASR=1
(baixar o modelo leva minutos na primeira vez).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import ffmpeg_required

from vellum.config import JobOptions
from vellum.errors import ProbeError
from vellum.extract import extract_audio, temp_wav_path
from vellum.pipeline import process_media
from vellum.probe import probe_media

asr_required = pytest.mark.skipif(
    os.environ.get("VELLUM_TEST_ASR") != "1",
    reason="defina VELLUM_TEST_ASR=1 para rodar a transcrição de verdade",
)

diarize_required = pytest.mark.skipif(
    os.environ.get("VELLUM_TEST_DIARIZE") != "1",
    reason="defina VELLUM_TEST_DIARIZE=1 para rodar a diarização de verdade",
)


@ffmpeg_required
def test_probe_audio_sintetico(tone_wav: Path):
    probe = probe_media(tone_wav)
    assert probe.has_audio and not probe.has_video
    assert probe.duration == pytest.approx(3.0, abs=0.2)
    assert probe.audio[0].sample_rate == 44100


@ffmpeg_required
def test_probe_video_mudo(silent_video: Path):
    probe = probe_media(silent_video)
    assert probe.has_video and not probe.has_audio
    assert probe.video[0].width == 320 and probe.video[0].height == 240


@ffmpeg_required
def test_probe_arquivo_invalido_falha_com_mensagem_clara(invalid_file: Path):
    with pytest.raises(ProbeError) as excinfo:
        probe_media(invalid_file)
    assert "não conseguiu ler" in str(excinfo.value)


@ffmpeg_required
def test_extract_normaliza_para_16k_mono(tone_wav: Path):
    with temp_wav_path() as wav:
        extract_audio(tone_wav, wav)
        probe = probe_media(wav)
        assert probe.audio[0].sample_rate == 16000
        assert probe.audio[0].channels == 1
        assert probe.audio[0].codec == "pcm_s16le"
    assert not wav.exists(), "o WAV temporário não foi removido"


@ffmpeg_required
def test_video_mudo_gera_relatorio_sem_transcricao(silent_video: Path, tmp_path: Path):
    options = JobOptions(input_path=silent_video, output_dir=tmp_path, write_srt=True)
    result = process_media(options)

    report = Path(result.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "[INDISPONÍVEL] Transcrição:" in report
    assert "não possui trilha de áudio" in " ".join(result.partial_failures)
    assert "srt" not in result.outputs, "não deve gerar legenda sem segmentos"

    data = json.loads(Path(result.outputs["data.json"]).read_text(encoding="utf-8"))
    assert data["segments"] == []
    assert data["source"]["sha256"]


@ffmpeg_required
@asr_required
def test_audio_sem_fala_produz_relatorio_com_aviso(tone_wav: Path, tmp_path: Path):
    options = JobOptions(input_path=tone_wav, output_dir=tmp_path, model="tiny", device="cpu")
    result = process_media(options)

    report = Path(result.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "3. QUALIDADE E DIAGNÓSTICO" in report
    assert result.diagnostics.analyzed
    assert result.diagnostics.mean_volume_db is not None
    # Um tom puro não é fala: o VAD deve descartar quase tudo.
    assert len(result.segments) <= 2


@ffmpeg_required
@asr_required
def test_saida_deterministica(tone_wav: Path, tmp_path: Path):
    """Mesmo arquivo + mesmos parâmetros = mesmo layout de TXT."""
    options_a = JobOptions(input_path=tone_wav, output_dir=tmp_path / "a", model="tiny", device="cpu")
    options_b = JobOptions(input_path=tone_wav, output_dir=tmp_path / "b", model="tiny", device="cpu")
    first = Path(process_media(options_a).outputs["report.txt"]).read_text(encoding="utf-8")
    second = Path(process_media(options_b).outputs["report.txt"]).read_text(encoding="utf-8")

    def strip_volatile(text: str) -> list[str]:
        """Remove o que muda entre execuções: relógio, tempos e caminhos."""
        skip = ("Processado em", "Tempo total", "Velocidade", "Caminho", "Pasta de saída")
        return [
            line
            for line in text.splitlines()
            if not any(marker in line for marker in skip)
            and " s   [" not in line
            and str(tmp_path) not in line
        ]

    assert strip_volatile(first) == strip_volatile(second)


@ffmpeg_required
@asr_required
@diarize_required
def test_diarizacao_separa_dois_locutores(dialogo_wav: Path, tmp_path: Path):
    """Áudio com dois timbres alternados deve virar dois falantes rotulados."""
    options = JobOptions(
        input_path=dialogo_wav,
        output_dir=tmp_path,
        model="small",
        language="pt",
        diarize=True,
        diarize_backend="ecapa",
        write_srt=True,
    )
    result = process_media(options)

    if not result.diarization.available:
        pytest.skip(f"diarização indisponível neste ambiente: {result.diarization.reason}")

    speakers = {segment.speaker for segment in result.segments if segment.speaker}
    assert speakers == {"SPEAKER_00", "SPEAKER_01"}, "esperava exatamente dois falantes"
    assert result.diarization.speaker_count == 2

    report = Path(result.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "SPEAKER_00:" in report
    assert "[INDISPONÍVEL] Diarização" not in report

    srt = Path(result.outputs["srt"]).read_text(encoding="utf-8")
    assert "[SPEAKER_00]" in srt


# --------------------------------------------------------------------------- #
# Retomada
# --------------------------------------------------------------------------- #
@ffmpeg_required
def test_retoma_do_ponto_salvo_sem_transcrever_de_novo(tone_wav: Path, tmp_path: Path):
    """Com um ponto salvo na etapa `asr`, o pipeline NÃO carrega modelo nenhum.

    É a prova de que a retomada economiza o trabalho caro: este teste roda sem
    baixar nada, e falharia com timeout se a transcrição fosse refeita.
    """
    from vellum.checkpoint import CheckpointStore, job_key
    from vellum.pipeline import build_source_info
    from vellum.probe import probe_media
    from vellum.types import (
        AudioDiagnostics,
        JobResult,
        LanguageInfo,
        ProcessingInfo,
        SegmentInfo,
    )

    raiz = tmp_path / "checkpoints"
    options = JobOptions(input_path=tone_wav, output_dir=tmp_path / "saida", model="tiny")

    # Semeia um ponto como se a transcrição já tivesse terminado.
    parcial = JobResult(
        source=build_source_info(tone_wav),
        probe=probe_media(tone_wav),
        processing=ProcessingInfo(model="tiny", device="cpu", compute_type="int8"),
        language=LanguageInfo(code="pt", probability=0.9, source="auto"),
        diagnostics=AudioDiagnostics(analyzed=True, mean_volume_db=-18.0),
        text="fala recuperada do ponto salvo",
        segments=[SegmentInfo(id=0, start=0.0, end=2.0,
                              text="fala recuperada do ponto salvo")],
    )
    store = CheckpointStore(job_key(parcial.source.sha256, options), root=raiz)
    store.save("asr", parcial)

    # Se a transcrição fosse refeita, isto estouraria: não existe modelo aqui.
    import vellum.pipeline as pipeline_module

    def nao_deve_ser_chamado(*args, **kwargs):
        raise AssertionError("a transcrição foi refeita apesar do ponto salvo")

    original = pipeline_module.transcribe_audio
    pipeline_module.transcribe_audio = nao_deve_ser_chamado
    try:
        result = process_media(options, checkpoint_root=raiz)
    finally:
        pipeline_module.transcribe_audio = original

    assert result.text == "fala recuperada do ponto salvo"
    assert result.language.code == "pt"
    relatorio = Path(result.outputs["report.txt"]).read_text(encoding="utf-8")
    assert "fala recuperada do ponto salvo" in relatorio
    assert any("Retomado de um ponto salvo" in aviso for aviso in result.partial_failures)

    # Concluiu: o ponto sai do disco para não ressuscitar num processamento futuro.
    assert store.load() is None


@ffmpeg_required
def test_sem_ponto_salvo_o_pipeline_roda_normalmente(silent_video: Path, tmp_path: Path):
    options = JobOptions(input_path=silent_video, output_dir=tmp_path)
    result = process_media(options, checkpoint_root=tmp_path / "checkpoints")
    assert not any("Retomado" in aviso for aviso in result.partial_failures)


@ffmpeg_required
def test_resume_desligado_ignora_o_ponto(tone_wav: Path, tmp_path: Path):
    """Com resume=False nem sequer olhamos para o disco."""
    options = JobOptions(input_path=tone_wav, output_dir=tmp_path / "saida", model="tiny")
    result = process_media(
        options, resume=False, checkpoint_root=tmp_path / "checkpoints"
    )
    assert not any("Retomado" in aviso for aviso in result.partial_failures)
