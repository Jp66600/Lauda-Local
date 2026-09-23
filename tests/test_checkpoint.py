"""Testes dos pontos de retomada."""

from __future__ import annotations

import json
import time
from pathlib import Path

from lauda import checkpoint as cp
from lauda.checkpoint import CheckpointStore, job_key, options_fingerprint, purge_old
from lauda.config import JobOptions
from lauda.types import (
    AudioDiagnostics,
    JobResult,
    LanguageInfo,
    ProbeResult,
    ProcessingInfo,
    SegmentInfo,
    SourceInfo,
)


def _options(tmp_path: Path, **kwargs) -> JobOptions:
    base = dict(input_path=tmp_path / "a.wav", output_dir=tmp_path / "out")
    base.update(kwargs)
    return JobOptions(**base)


def _result(texto: str = "olá mundo") -> JobResult:
    return JobResult(
        source=SourceInfo(
            name="a.wav", path="/tmp/a.wav", size_bytes=10, size_human="10 B",
            sha256="a" * 64, modified_at="2026-09-04T00:00:00-03:00",
        ),
        probe=ProbeResult(format_name="wav", duration=12.0),
        processing=ProcessingInfo(model="small", device="cpu"),
        language=LanguageInfo(code="pt"),
        diagnostics=AudioDiagnostics(analyzed=True, mean_volume_db=-20.0),
        text=texto,
        segments=[SegmentInfo(id=0, start=0.0, end=2.0, text=texto)],
    )


# --------------------------------------------------------------------------- #
# Identidade do trabalho
# --------------------------------------------------------------------------- #
def test_mudar_o_modelo_invalida_o_ponto(tmp_path: Path):
    a = options_fingerprint(_options(tmp_path, model="small"))
    b = options_fingerprint(_options(tmp_path, model="medium"))
    assert a != b


def test_mudar_a_pasta_de_saida_nao_invalida(tmp_path: Path):
    """Trocar onde salvar não justifica transcrever tudo de novo."""
    a = options_fingerprint(_options(tmp_path, output_dir=tmp_path / "x"))
    b = options_fingerprint(_options(tmp_path, output_dir=tmp_path / "y"))
    assert a == b


def test_pedir_legenda_nao_invalida(tmp_path: Path):
    a = options_fingerprint(_options(tmp_path, write_srt=False))
    b = options_fingerprint(_options(tmp_path, write_srt=True))
    assert a == b


def test_desligar_a_gpu_invalida_porque_muda_o_resultado(tmp_path: Path):
    from lauda.limits import ResourceLimits

    a = options_fingerprint(_options(tmp_path))
    b = options_fingerprint(_options(tmp_path, limits=ResourceLimits(gpu_percent=0)))
    assert a != b


def test_chave_junta_arquivo_e_opcoes(tmp_path: Path):
    opcoes = _options(tmp_path)
    assert job_key("f" * 64, opcoes) != job_key("e" * 64, opcoes)


# --------------------------------------------------------------------------- #
# Salvar e retomar
# --------------------------------------------------------------------------- #
def test_ida_e_volta_do_ponto(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    assert store.load() is None

    store.save("asr", _result("primeira fala"))
    salvo = store.load()

    assert salvo is not None
    assert salvo.stage == "asr"
    assert salvo.stage_index == 3
    assert salvo.result.text == "primeira fala"
    assert len(salvo.result.segments) == 1
    assert "asr" in salvo.describe()


def test_o_wav_extraido_viaja_junto(tmp_path: Path):
    wav = tmp_path / "audio_origem.wav"
    wav.write_bytes(b"RIFF____WAVEfmt ")
    store = CheckpointStore("teste", root=tmp_path)

    store.save("extract", _result(), wav=wav)
    salvo = store.load()

    assert salvo is not None and salvo.wav_path is not None
    assert salvo.wav_path.exists()
    assert salvo.wav_path.read_bytes() == wav.read_bytes()


def test_wav_apagado_no_meio_tempo_nao_quebra(tmp_path: Path):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"RIFF")
    store = CheckpointStore("teste", root=tmp_path)
    store.save("extract", _result(), wav=wav)

    store.wav_path.unlink()
    salvo = store.load()

    assert salvo is not None
    assert salvo.wav_path is None, "sem o áudio, a retomada precisa reextrair"


def test_concluir_apaga_o_ponto(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    store.save("asr", _result())
    assert store.state_path.exists()

    store.clear()
    assert not store.directory.exists()
    assert store.load() is None


def test_contador_de_tentativas(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    store.save("asr", _result())
    assert store.bump_attempts() == 1
    assert store.bump_attempts() == 2
    assert store.load().attempts == 2


# --------------------------------------------------------------------------- #
# Robustez: um ponto ruim nunca pode impedir o trabalho
# --------------------------------------------------------------------------- #
def test_arquivo_corrompido_e_descartado(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    store.save("asr", _result())
    store.state_path.write_text("{isto não é json", encoding="utf-8")

    assert store.load() is None
    assert not store.directory.exists(), "o ponto inútil precisa sair do caminho"


def test_formato_antigo_e_descartado(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    store.save("asr", _result())
    dados = json.loads(store.state_path.read_text(encoding="utf-8"))
    dados["format_version"] = 0
    store.state_path.write_text(json.dumps(dados), encoding="utf-8")

    assert store.load() is None


def test_ponto_vencido_e_descartado(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    store.save("asr", _result())
    dados = json.loads(store.state_path.read_text(encoding="utf-8"))
    dados["saved_at"] = time.time() - cp.MAX_AGE_SECONDS - 60
    store.state_path.write_text(json.dumps(dados), encoding="utf-8")

    assert store.load() is None


def test_salvar_e_atomico(tmp_path: Path):
    """Nunca deve sobrar um .tmp: um ponto pela metade é pior que nenhum."""
    store = CheckpointStore("teste", root=tmp_path)
    store.save("asr", _result())
    assert not list(store.directory.glob("*.tmp"))


def test_purge_remove_so_os_velhos(tmp_path: Path):
    novo = CheckpointStore("novo", root=tmp_path)
    velho = CheckpointStore("velho", root=tmp_path)
    novo.save("asr", _result())
    velho.save("asr", _result())

    antigo = time.time() - cp.MAX_AGE_SECONDS - 60
    import os

    os.utime(velho.state_path, (antigo, antigo))

    assert purge_old(root=tmp_path) == 1
    assert novo.directory.exists()
    assert not velho.directory.exists()
