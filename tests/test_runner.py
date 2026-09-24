"""Testes do supervisor: travamento, morte do processo e retomada.

Em vez do worker de verdade, estes testes usam processos falsos que se
comportam mal de propósito — travar, morrer, cair na primeira e funcionar na
segunda. É a única forma de exercitar a recuperação sem depender de uma
transcrição real dar errado.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from lauda import runner
from lauda.config import JobOptions
from lauda.limits import ResourceLimits
from lauda.runner import RecoveryFailed, _degrade, run_with_recovery


@pytest.fixture()
def entrada(tmp_path: Path) -> Path:
    path = tmp_path / "entrada.wav"
    path.write_bytes(b"RIFF____WAVEfmt " + b"\0" * 64)
    return path


def _options(entrada: Path, tmp_path: Path, **kwargs) -> JobOptions:
    base = dict(input_path=entrada, output_dir=tmp_path / "saida")
    base.update(kwargs)
    return JobOptions(**base)


def _fake_worker(tmp_path: Path, corpo: str) -> Path:
    """Escreve um script que faz as vezes do processo filho."""
    script = tmp_path / "fake_worker.py"
    script.write_text(
        "import json, sys, time, pathlib\n"
        "job = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
        "def emit(ev):\n"
        "    sys.stdout.write(json.dumps(ev) + '\\n'); sys.stdout.flush()\n"
        + textwrap.dedent(corpo),
        encoding="utf-8",
    )
    return script


def _use_fake(monkeypatch, script: Path) -> list[dict]:
    """Faz o supervisor chamar o script falso e guarda o job de cada chamada.

    Guardamos o CONTEÚDO, não o caminho: a pasta de trabalho é temporária e
    some quando o supervisor retorna.
    """
    chamadas: list[dict] = []

    def command(job_path: Path) -> list[str]:
        chamadas.append(json.loads(Path(job_path).read_text(encoding="utf-8")))
        return [sys.executable, str(script), str(job_path)]

    monkeypatch.setattr(runner, "_worker_command", command)
    return chamadas


# --------------------------------------------------------------------------- #
# Rebaixamento entre tentativas
# --------------------------------------------------------------------------- #
def test_segunda_tentativa_desliga_a_gpu(entrada: Path, tmp_path: Path):
    opcoes = _options(entrada, tmp_path, model="small")
    novas, como = _degrade(opcoes, 2)
    assert novas.limits.use_gpu is False
    assert "GPU" in como


def test_terceira_tentativa_diminui_o_modelo(entrada: Path, tmp_path: Path):
    opcoes = _options(entrada, tmp_path, model="small",
                      limits=ResourceLimits(gpu_percent=0))
    novas, como = _degrade(opcoes, 3)
    assert novas.model == "base"
    assert "modelo" in como


def test_rebaixamento_para_no_menor_modelo(entrada: Path, tmp_path: Path):
    opcoes = _options(entrada, tmp_path, model="tiny",
                      limits=ResourceLimits(gpu_percent=0))
    novas, _ = _degrade(opcoes, 3)
    assert novas.model == "tiny", "não existe modelo menor que tiny"


# --------------------------------------------------------------------------- #
# Caminho feliz
# --------------------------------------------------------------------------- #
def test_primeira_tentativa_bem_sucedida(entrada: Path, tmp_path: Path, monkeypatch):
    script = _fake_worker(tmp_path, """
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.5, 'message': 'indo'})
        import sys
        sys.path.insert(0, r'%s')
        from tests_helpers import write_fake_result
        write_fake_result(job['result_path'])
        emit({'t': 'done', 'result': job['result_path']})
    """ % str(Path(__file__).parent))
    _use_fake(monkeypatch, script)

    progresso: list[tuple[str, float]] = []
    resultado, tentativas = run_with_recovery(
        _options(entrada, tmp_path),
        progress=lambda s, f, m: progresso.append((s, f)),
        checkpoint_root=tmp_path / "cp",
    )

    assert len(tentativas) == 1
    assert tentativas[0].exit_code == 0
    assert progresso == [("asr", 0.5)]
    assert resultado.text == "resultado de teste"


# --------------------------------------------------------------------------- #
# Travamento: o coração da funcionalidade
# --------------------------------------------------------------------------- #
def test_processo_travado_e_morto_e_retomado(entrada: Path, tmp_path: Path, monkeypatch):
    """Trava na primeira, funciona na segunda — e ninguém fica pendurado."""
    script = _fake_worker(tmp_path, """
        import sys
        sys.path.insert(0, r'%s')
        from tests_helpers import write_fake_result
        marcador = pathlib.Path(job['result_path']).parent / 'ja_travou'
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.3, 'message': 'transcrevendo'})
        if not marcador.exists():
            marcador.write_text('sim')
            time.sleep(600)          # trava de propósito
        write_fake_result(job['result_path'])
        emit({'t': 'done', 'result': job['result_path']})
    """ % str(Path(__file__).parent))
    _use_fake(monkeypatch, script)

    eventos: list[tuple[str, str]] = []
    resultado, tentativas = run_with_recovery(
        _options(entrada, tmp_path),
        on_event=lambda k, m: eventos.append((k, m)),
        stall_timeout=1.0,
        checkpoint_root=tmp_path / "cp",
    )

    assert len(tentativas) == 2, "deveria ter tentado de novo"
    assert tentativas[0].stalled is True
    assert "asr" in tentativas[0].reason
    assert tentativas[1].exit_code == 0
    assert resultado.text == "resultado de teste"

    tipos = [tipo for tipo, _ in eventos]
    assert "travou" in tipos, "o usuário precisa saber que travou"
    assert "reiniciando" in tipos


def test_o_limite_de_travamento_e_maior_no_asr():
    """A etapa de transcrição fica muda baixando modelo; isso não é travamento.

    A folga é multiplicador do tempo pedido, e não um teto fixo — senão o
    supervisor ignoraria o limite escolhido por quem chamou.
    """
    assert runner.ASR_STALL_FACTOR > 1.0


def test_processo_que_morre_e_retomado(entrada: Path, tmp_path: Path, monkeypatch):
    script = _fake_worker(tmp_path, """
        import sys
        sys.path.insert(0, r'%s')
        from tests_helpers import write_fake_result
        marcador = pathlib.Path(job['result_path']).parent / 'ja_morreu'
        emit({'t': 'progress', 'stage': 'extract', 'fraction': 0.1, 'message': 'extraindo'})
        if not marcador.exists():
            marcador.write_text('sim')
            sys.exit(3)              # morre sem dizer nada
        write_fake_result(job['result_path'])
        emit({'t': 'done', 'result': job['result_path']})
    """ % str(Path(__file__).parent))
    _use_fake(monkeypatch, script)

    resultado, tentativas = run_with_recovery(
        _options(entrada, tmp_path), stall_timeout=30.0, checkpoint_root=tmp_path / "cp"
    )
    assert len(tentativas) == 2
    assert tentativas[0].exit_code == 3
    assert tentativas[0].stalled is False
    assert resultado.text == "resultado de teste"


def test_erro_do_pipeline_chega_com_a_mensagem(entrada: Path, tmp_path: Path, monkeypatch):
    script = _fake_worker(tmp_path, """
        emit({'t': 'error', 'message': 'o ffprobe nao conseguiu ler o arquivo',
              'kind': 'ProbeError'})
        sys.exit(1)
    """)
    _use_fake(monkeypatch, script)

    with pytest.raises(RecoveryFailed) as excinfo:
        run_with_recovery(
            _options(entrada, tmp_path), max_attempts=2, checkpoint_root=tmp_path / "cp"
        )
    assert "nao conseguiu ler" in str(excinfo.value)


def test_desiste_depois_do_limite_de_tentativas(entrada: Path, tmp_path: Path, monkeypatch):
    script = _fake_worker(tmp_path, """
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.1, 'message': 'indo'})
        time.sleep(600)
    """)
    chamadas = _use_fake(monkeypatch, script)

    eventos: list[tuple[str, str]] = []
    with pytest.raises(RecoveryFailed):
        run_with_recovery(
            _options(entrada, tmp_path),
            on_event=lambda k, m: eventos.append((k, m)),
            stall_timeout=1.0,
            max_attempts=2,
            checkpoint_root=tmp_path / "cp",
        )

    assert len(chamadas) == 2
    assert any(tipo == "desistiu" for tipo, _ in eventos)


def test_as_opcoes_rebaixadas_chegam_ao_filho(entrada: Path, tmp_path: Path, monkeypatch):
    """A segunda tentativa precisa mesmo mandar GPU desligada."""
    script = _fake_worker(tmp_path, """
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.1, 'message': 'indo'})
        time.sleep(600)
    """)
    chamadas = _use_fake(monkeypatch, script)

    with pytest.raises(RecoveryFailed):
        run_with_recovery(
            _options(entrada, tmp_path),
            stall_timeout=1.0,
            max_attempts=2,
            checkpoint_root=tmp_path / "cp",
        )

    primeira, segunda = chamadas
    assert primeira["options"]["limits"]["gpu_percent"] == 100
    assert segunda["options"]["limits"]["gpu_percent"] == 0
    assert segunda["resume"] is True, "a retomada precisa continuar ligada"


def test_o_worker_do_executavel_empacotado_chama_a_si_mesmo(monkeypatch, tmp_path):
    """No .exe não há `python -m`: o próprio aplicativo assume o papel."""
    from lauda.runner import _worker_command

    monkeypatch.setattr("lauda.runner.sys.frozen", True, raising=False)
    monkeypatch.setattr("lauda.runner.sys.executable", r"C:\App\Lauda Local.exe")

    comando = _worker_command(tmp_path / "job.json")
    assert comando[0].endswith("Lauda Local.exe")
    assert "--worker" in comando
    assert "-m" not in comando, "o executável empacotado não entende -m"


# --------------------------------------------------------------------------- #
# Pausar e retomar
# --------------------------------------------------------------------------- #
def test_pausar_congela_o_processo_e_retomar_conclui(
    entrada: Path, tmp_path: Path, monkeypatch
):
    """O filho só termina depois de descongelado — e termina inteiro."""
    import threading
    import time

    marcador = tmp_path / "passou.txt"
    script = _fake_worker(tmp_path, f"""
        import pathlib
        emit({{'t': 'progress', 'stage': 'asr', 'fraction': 0.5, 'message': 'meio'}})
        time.sleep(0.6)
        pathlib.Path({str(marcador)!r}).write_text('fim', encoding='utf-8')
        sys.path.insert(0, {str(Path(__file__).parent)!r})
        from tests_helpers import write_fake_result
        write_fake_result(job['result_path'])
        emit({{'t': 'done', 'result': job['result_path']}})
    """)
    _use_fake(monkeypatch, script)

    pausa = threading.Event()
    pausa.set()          # pausado antes mesmo de o filho chegar ao fim

    def solta_depois() -> None:
        time.sleep(1.2)
        pausa.clear()

    threading.Thread(target=solta_depois, daemon=True).start()
    comeco = time.monotonic()
    resultado, tentativas = run_with_recovery(
        _options(entrada, tmp_path), pause=pausa, checkpoint_root=tmp_path / "cp"
    )
    duracao = time.monotonic() - comeco

    assert resultado.text, "o trabalho tem de concluir depois de retomado"
    assert len(tentativas) == 1, "pausar não pode disparar uma nova tentativa"
    assert marcador.exists()
    assert duracao >= 1.2, "ficou parado enquanto a pausa estava ligada"


def test_pausado_nao_conta_como_travado(entrada: Path, tmp_path: Path, monkeypatch):
    """O vigia de travamento tem de parar junto: senão pausar é o mesmo que matar."""
    import threading
    import time

    script = _fake_worker(tmp_path, """
        sys.path.insert(0, %r)
        from tests_helpers import write_fake_result   # importa antes do silêncio
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.5, 'message': 'meio'})
        time.sleep(0.2)
        write_fake_result(job['result_path'])
        emit({'t': 'done', 'result': job['result_path']})
    """ % str(Path(__file__).parent))
    _use_fake(monkeypatch, script)

    pausa = threading.Event()
    pausa.set()
    threading.Thread(
        target=lambda: (time.sleep(4.0), pausa.clear()), daemon=True
    ).start()

    # Pausa (4 s) BEM maior que o teto de travamento (1 s, que vira 3 s na
    # etapa asr): sem a trégua, o supervisor mataria o filho antes de ele
    # poder terminar. A folga depois de retomado é de propósito — numa máquina
    # lenta, importar e gravar o resultado não pode ser confundido com
    # travamento e transformar este teste em loteria.
    resultado, tentativas = run_with_recovery(
        _options(entrada, tmp_path), pause=pausa, stall_timeout=1.0,
        checkpoint_root=tmp_path / "cp",
    )

    assert resultado.text
    assert len(tentativas) == 1, "o vigia não pode acordar durante a pausa"
    assert not tentativas[0].stalled


def test_cancelar_durante_a_pausa_descongela_antes_de_matar(
    entrada: Path, tmp_path: Path, monkeypatch
):
    """Matar processo congelado deixa zumbi; o supervisor solta antes."""
    import threading

    script = _fake_worker(tmp_path, """
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.5, 'message': 'meio'})
        time.sleep(30)
    """)
    _use_fake(monkeypatch, script)

    soltos: list[int] = []
    original = runner._resume
    monkeypatch.setattr(
        runner, "_resume", lambda p: (soltos.append(p.pid), original(p))[1]
    )
    # Vale mesmo se congelar nao funcionar nesta maquina: descongelar antes de
    # matar tem de acontecer de qualquer jeito.

    pausa, cancelar = threading.Event(), threading.Event()
    pausa.set()
    threading.Thread(
        target=lambda: (__import__("time").sleep(0.8), cancelar.set()), daemon=True
    ).start()

    with pytest.raises(RecoveryFailed, match="cancelado"):
        run_with_recovery(
            _options(entrada, tmp_path), pause=pausa, cancel=cancelar,
            checkpoint_root=tmp_path / "cp",
        )

    assert soltos, "descongelou antes de matar"


def test_maquina_que_nao_deixa_congelar_avisa_em_vez_de_mentir(
    entrada: Path, tmp_path: Path, monkeypatch
):
    """Sem poder congelar, o trabalho continua — e quem chamou fica sabendo.

    Uma tela dizendo "Pausado" enquanto a máquina segue a todo vapor é pior
    que não ter o botão.
    """
    import threading

    script = _fake_worker(tmp_path, """
        sys.path.insert(0, %r)
        from tests_helpers import write_fake_result
        emit({'t': 'progress', 'stage': 'asr', 'fraction': 0.5, 'message': 'meio'})
        time.sleep(0.2)
        write_fake_result(job['result_path'])
        emit({'t': 'done', 'result': job['result_path']})
    """ % str(Path(__file__).parent))
    _use_fake(monkeypatch, script)
    monkeypatch.setattr(runner, "_suspend", lambda _p: False)

    avisos: list[tuple[str, str]] = []
    pausa = threading.Event()
    pausa.set()
    threading.Thread(
        target=lambda: (__import__("time").sleep(0.7), pausa.clear()), daemon=True
    ).start()

    resultado, tentativas = run_with_recovery(
        _options(entrada, tmp_path), pause=pausa,
        on_event=lambda kind, msg: avisos.append((kind, msg)),
        checkpoint_root=tmp_path / "cp",
    )

    assert resultado.text, "o trabalho continua mesmo sem conseguir pausar"
    assert len(tentativas) == 1
    assert any(kind == "pausa_falhou" for kind, _ in avisos)


# --------------------------------------------------------------------------- #
# Rebaixamento da etapa que falhou
# --------------------------------------------------------------------------- #
def test_travou_na_diarizacao_desliga_a_diarizacao(entrada: Path, tmp_path: Path):
    """E mantém o modelo: trocá-lo jogaria fora a transcrição já pronta."""
    opcoes = _options(entrada, tmp_path, diarize=True, model="large-v3")

    degradado, como = _degrade(opcoes, 2, "diarize")

    assert degradado.diarize is False
    assert degradado.model == "large-v3", "a transcrição pronta tem de continuar valendo"
    assert degradado.limits.use_gpu, "a GPU não tem nada a ver com o travamento"
    assert "quem fala" in como


def test_travou_na_transcricao_rebaixa_o_ambiente(entrada: Path, tmp_path: Path):
    """Sem etapa culpada identificável, vale a escada de sempre."""
    opcoes = _options(entrada, tmp_path, diarize=True)

    degradado, como = _degrade(opcoes, 2, "asr")

    assert degradado.diarize is True, "não mexe no que não falhou"
    assert not degradado.limits.use_gpu
    assert "GPU" in como


def test_diarizacao_ja_desligada_cai_na_escada_normal(entrada: Path, tmp_path: Path):
    opcoes = _options(entrada, tmp_path, diarize=False)

    degradado, como = _degrade(opcoes, 2, "diarize")

    assert not degradado.limits.use_gpu or degradado.model != opcoes.model
    assert "quem fala" not in como


def test_miniaturas_e_resumo_tambem_saem_quando_sao_a_causa(entrada: Path, tmp_path: Path):
    visual, _ = _degrade(_options(entrada, tmp_path, visual=True), 2, "visual")
    resumo, _ = _degrade(_options(entrada, tmp_path, summarize=True), 2, "summarize")

    assert visual.visual is False
    assert resumo.summarize is False
