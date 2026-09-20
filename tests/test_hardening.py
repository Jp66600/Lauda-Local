"""Testes das melhorias de segurança, robustez e desempenho.

Cada teste aqui existe por causa de um problema concreto que foi encontrado e
corrigido — não são testes decorativos.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from vellum import runner
from vellum.checkpoint import CheckpointStore, options_fingerprint
from vellum.config import JobOptions
from vellum.runner import RecoveryFailed, run_with_recovery


def _options(tmp_path: Path, **kwargs) -> JobOptions:
    entrada = tmp_path / "entrada.wav"
    if not entrada.exists():
        entrada.write_bytes(b"RIFF____WAVEfmt " + b"\0" * 64)
    base: dict = {"input_path": entrada, "output_dir": tmp_path / "saida"}
    base.update(kwargs)
    return JobOptions(**base)


# --------------------------------------------------------------------------- #
# Segurança: segredo não vai para disco
# --------------------------------------------------------------------------- #
def test_o_token_nao_e_serializado(tmp_path: Path):
    """O dicionário vira arquivo temporário; segredo não se escreve em disco."""
    opcoes = _options(tmp_path, hf_token="hf_segredo_supersecreto")
    dados = opcoes.to_dict()

    assert "hf_token" not in dados
    assert "hf_segredo_supersecreto" not in json.dumps(dados)


def test_o_token_volta_do_ambiente(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_do_ambiente")
    opcoes = JobOptions.from_dict(_options(tmp_path).to_dict())
    assert opcoes.hf_token == "hf_do_ambiente"


def test_sem_token_no_ambiente_fica_none(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    opcoes = JobOptions.from_dict(_options(tmp_path, hf_token="x").to_dict())
    assert opcoes.hf_token is None


def test_o_arquivo_de_job_nao_contem_o_token(tmp_path: Path, monkeypatch):
    """Prova de ponta a ponta: o JSON que chega ao disco não tem o segredo."""
    escritos: list[dict] = []
    script = tmp_path / "fake.py"
    script.write_text(
        "import json,sys,pathlib\n"
        "job=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )

    def command(job_path: Path) -> list[str]:
        escritos.append(json.loads(Path(job_path).read_text(encoding="utf-8")))
        return [sys.executable, str(script), str(job_path)]

    monkeypatch.setattr(runner, "_worker_command", command)
    with pytest.raises(RecoveryFailed):
        run_with_recovery(
            _options(tmp_path, hf_token="hf_nao_pode_vazar"),
            max_attempts=1,
            checkpoint_root=tmp_path / "cp",
        )

    assert escritos, "o job nem chegou a ser escrito"
    assert "hf_nao_pode_vazar" not in json.dumps(escritos[0])


# --------------------------------------------------------------------------- #
# Robustez: matar o filho tem de matar o neto
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(sys.platform not in ("win32", "linux", "darwin"), reason="SO exótico")
def test_matar_o_processo_travado_leva_os_netos_junto(tmp_path: Path, monkeypatch):
    """O worker chama ffmpeg. Matar só o worker deixaria o ffmpeg vivo.

    Aqui o worker falso cria um "neto" que grava um arquivo a cada 0,2 s.
    Depois do travamento e da morte, o arquivo tem de parar de crescer.
    """
    marcador = tmp_path / "neto_vivo.txt"
    neto = tmp_path / "neto.py"
    neto.write_text(
        textwrap.dedent(f"""
            import time, pathlib
            alvo = pathlib.Path(r"{marcador}")
            for i in range(100000):
                alvo.write_text(str(i))
                time.sleep(0.2)
        """),
        encoding="utf-8",
    )

    script = tmp_path / "fake_worker.py"
    script.write_text(
        textwrap.dedent(f"""
            import json, subprocess, sys, time, pathlib
            job = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
            sys.stdout.write(json.dumps(
                {{"t": "progress", "stage": "extract", "fraction": 0.1, "message": "indo"}}
            ) + "\\n")
            sys.stdout.flush()
            subprocess.Popen([sys.executable, r"{neto}"])   # o "ffmpeg" da vida real
            time.sleep(600)                                  # trava de proposito
        """),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        runner, "_worker_command",
        lambda job_path: [sys.executable, str(script), str(job_path)],
    )

    with pytest.raises(RecoveryFailed):
        run_with_recovery(
            _options(tmp_path),
            stall_timeout=1.0,
            max_attempts=1,
            checkpoint_root=tmp_path / "cp",
        )

    assert marcador.exists(), "o neto nem chegou a rodar; teste inconclusivo"
    antes = marcador.read_text(encoding="utf-8")
    time.sleep(1.5)
    depois = marcador.read_text(encoding="utf-8")
    assert antes == depois, "o processo neto continuou vivo depois da matança"


# --------------------------------------------------------------------------- #
# Desempenho: não reler o arquivo duas vezes
# --------------------------------------------------------------------------- #
def test_o_hash_conhecido_evita_reler_o_arquivo(tmp_path: Path, monkeypatch):
    from vellum import pipeline

    arquivo = tmp_path / "grande.wav"
    arquivo.write_bytes(b"conteudo")

    def nao_deve_ler(*args, **kwargs):
        raise AssertionError("o arquivo foi lido de novo apesar do hash conhecido")

    monkeypatch.setattr(pipeline, "sha256_file", nao_deve_ler)
    info = pipeline.build_source_info(arquivo, known_sha256="a" * 64)
    assert info.sha256 == "a" * 64


def test_sem_hash_conhecido_ele_calcula(tmp_path: Path):
    from vellum.pipeline import build_source_info

    arquivo = tmp_path / "pequeno.wav"
    arquivo.write_bytes(b"conteudo")
    assert len(build_source_info(arquivo).sha256) == 64


# --------------------------------------------------------------------------- #
# Disco: extrair direto no ponto, sem cópia
# --------------------------------------------------------------------------- #
def test_salvar_nao_copia_o_wav_sobre_ele_mesmo(tmp_path: Path):
    from tests_helpers import make_result  # type: ignore[import-not-found]

    store = CheckpointStore("teste", root=tmp_path)
    store.prepare()
    store.wav_path.write_bytes(b"audio ja extraido aqui")
    antes = store.wav_path.stat().st_mtime_ns

    store.save("extract", make_result(), wav=store.wav_path)

    assert store.wav_path.read_bytes() == b"audio ja extraido aqui"
    assert store.wav_path.stat().st_mtime_ns == antes, "copiou sobre si mesmo"


def test_prepare_cria_a_pasta(tmp_path: Path):
    store = CheckpointStore("teste", root=tmp_path)
    assert not store.directory.exists()
    assert store.prepare() == store.directory
    assert store.directory.is_dir()


# --------------------------------------------------------------------------- #
# Modo rápido (lotes)
# --------------------------------------------------------------------------- #
def test_batch_size_fora_da_faixa_e_recusado(tmp_path: Path):
    with pytest.raises(ValueError, match="batch-size"):
        _options(tmp_path, batch_size=64)
    with pytest.raises(ValueError, match="batch-size"):
        _options(tmp_path, batch_size=-1)


def test_o_padrao_e_sequencial(tmp_path: Path):
    """Lote é mais rápido mas gera trechos ~6x mais longos: nunca é o padrão."""
    assert _options(tmp_path).batch_size == 0


def test_mudar_o_modo_invalida_o_ponto_de_retomada(tmp_path: Path):
    sequencial = options_fingerprint(_options(tmp_path, batch_size=0))
    lote = options_fingerprint(_options(tmp_path, batch_size=16))
    assert sequencial != lote, "o resultado muda, então o ponto salvo não serve"


def test_engine_em_lote_so_e_criado_quando_pedido(tmp_path: Path):
    from vellum.transcribe import _make_engine

    modelo = object()
    engine, extra = _make_engine(modelo, _options(tmp_path, batch_size=0))
    assert engine is modelo and extra == {}


def test_engine_em_lote_repassa_o_tamanho(tmp_path: Path):
    pytest.importorskip("faster_whisper")
    from vellum.transcribe import _make_engine

    class ModeloFalso:
        pass

    engine, extra = _make_engine(ModeloFalso(), _options(tmp_path, batch_size=8))
    assert extra == {"batch_size": 8}
    assert engine.__class__.__name__ == "BatchedInferencePipeline"


# --------------------------------------------------------------------------- #
# Higiene do supervisor
# --------------------------------------------------------------------------- #
def test_o_supervisor_nao_deixa_processo_para_tras(tmp_path: Path, monkeypatch):
    """Depois de desistir, nenhum filho pode continuar vivo."""
    script = tmp_path / "fake_worker.py"
    script.write_text(
        "import json,sys,time,pathlib\n"
        "sys.stdout.write(json.dumps({'t':'progress','stage':'vad',"
        "'fraction':0.1,'message':'x'})+'\\n'); sys.stdout.flush()\n"
        "time.sleep(600)\n",
        encoding="utf-8",
    )
    filhos: list[subprocess.Popen] = []
    original = subprocess.Popen

    def espiao(*args, **kwargs):
        processo = original(*args, **kwargs)
        filhos.append(processo)
        return processo

    monkeypatch.setattr(
        runner, "_worker_command",
        lambda job_path: [sys.executable, str(script), str(job_path)],
    )
    monkeypatch.setattr(subprocess, "Popen", espiao)

    with pytest.raises(RecoveryFailed):
        run_with_recovery(
            _options(tmp_path), stall_timeout=1.0, max_attempts=2,
            checkpoint_root=tmp_path / "cp",
        )

    time.sleep(0.5)
    vivos = [p for p in filhos if p.poll() is None]
    assert not vivos, f"{len(vivos)} processo(s) ficaram pendurados"
