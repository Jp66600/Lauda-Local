"""Testa o bloco de resumo contra um Ollama simulado (nada de rede externa)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lauda.config import JobOptions
from lauda.summarize import ollama_available, pull_model, summarize_transcript

_ANSWER = {
    "resumo": "Duas pessoas discutem um projeto que roda totalmente offline.",
    "topicos": ["privacidade", "processamento local"],
    "acoes": ["Publicar o repositório"],
    "citacoes": ["Tudo roda na máquina local."],
}


class _FakeOllama(BaseHTTPRequestHandler):
    models = [{"name": "llama3.1:8b"}]
    # O modelo pode falar antes do JSON; o parser precisa aguentar isso.
    wrap_answer = False
    pull_events: list[dict] = []

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/api/tags":
            self._send({"models": self.models})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/api/pull":
            corpo = b"".join(
                (json.dumps(evento) + chr(10)).encode("utf-8") for evento in self.pull_events
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        content = json.dumps(_ANSWER, ensure_ascii=False)
        if self.wrap_answer:
            content = f"Claro! Aqui vai:\n{content}\nEspero ter ajudado."
        self._send({"message": {"role": "assistant", "content": content}})

    def log_message(self, *args: object) -> None:  # silencia o log do servidor
        return


@pytest.fixture()
def fake_ollama():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def _options(host: str, tmp_path: Path, model: str = "llama3.1:8b") -> JobOptions:
    return JobOptions(
        input_path=tmp_path, output_dir=tmp_path, ollama_host=host, ollama_model=model
    )


def test_detecta_ollama_no_ar(fake_ollama: str, tmp_path: Path):
    available, reason = ollama_available(_options(fake_ollama, tmp_path))
    assert available, reason


def test_avisa_quando_modelo_nao_esta_baixado(fake_ollama: str, tmp_path: Path):
    available, reason = ollama_available(_options(fake_ollama, tmp_path, "qwen2.5:14b"))
    assert not available
    assert "não está baixado" in reason


def test_avisa_quando_ollama_esta_fora(tmp_path: Path):
    # Porta fechada de propósito.
    available, reason = ollama_available(_options("http://127.0.0.1:1", tmp_path))
    assert not available
    assert "não respondeu" in reason


def test_resumo_completo(fake_ollama: str, tmp_path: Path):
    summary = summarize_transcript("Uma transcrição qualquer.", _options(fake_ollama, tmp_path))
    assert summary.available
    assert summary.provider == "ollama"
    assert summary.summary.startswith("Duas pessoas")
    assert summary.topics == ["privacidade", "processamento local"]
    assert summary.action_items == ["Publicar o repositório"]
    assert summary.quotes == ["Tudo roda na máquina local."]


def test_aceita_json_cercado_de_texto(fake_ollama: str, tmp_path: Path):
    _FakeOllama.wrap_answer = True
    try:
        summary = summarize_transcript("Outra transcrição.", _options(fake_ollama, tmp_path))
    finally:
        _FakeOllama.wrap_answer = False
    assert summary.available
    assert summary.topics


def test_transcricao_longa_usa_mapa_reducao(fake_ollama: str, tmp_path: Path):
    texto = ("Uma frase longa sobre o projeto local. " * 800)  # ~30 mil caracteres
    summary = summarize_transcript(texto, _options(fake_ollama, tmp_path))
    assert summary.available


def test_texto_vazio_nao_chama_o_modelo(tmp_path: Path):
    summary = summarize_transcript("   ", _options("http://127.0.0.1:1", tmp_path))
    assert not summary.available
    assert "não há transcrição" in summary.reason


def test_o_modelo_padrao_e_o_qwen3_14b(tmp_path: Path):
    """Decisão de produto: sair do Llama. Tag canônico, nunca `latest`."""
    from lauda.config import JobOptions

    padrao = JobOptions(input_path=tmp_path, output_dir=tmp_path).ollama_model
    assert padrao == "qwen3:14b"
    assert "latest" not in padrao, "tag flutuante muda o resultado sem aviso"


def test_modelo_ausente_diz_qual_baixar(tmp_path: Path, monkeypatch):
    """Trocar o padrão deixa quem já tinha o Llama sem resumo: o motivo tem de
    aparecer no relatório, com o comando pronto."""
    from lauda.summarize import ollama_available

    class RespostaFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "llama3.1:8b"}]}).encode()

    monkeypatch.setattr("lauda.summarize.urllib.request.urlopen",
                        lambda *a, **k: RespostaFalsa())
    disponivel, motivo = ollama_available(
        _options("http://127.0.0.1:11434", tmp_path, model="qwen3:14b")
    )

    assert disponivel is False
    assert "qwen3:14b" in motivo
    assert "ollama pull qwen3:14b" in motivo


# --------------------------------------------------------------------------- #
# Reserva quando o modelo grande nao esta baixado (BACKLOG-025)
# --------------------------------------------------------------------------- #
def test_usa_o_modelo_pedido_quando_ele_existe(tmp_path: Path):
    from lauda.summarize import pick_model

    escolhido, motivo = pick_model(
        _options("http://127.0.0.1:1", tmp_path, "qwen3:14b"), ["qwen3:14b", "qwen3:8b"]
    )
    assert escolhido == "qwen3:14b"
    assert motivo == "ok"


def test_cai_para_o_menor_em_vez_de_desistir(tmp_path: Path):
    """Baixar 9 GB no meio do trabalho nao e opcao; desistir do resumo tambem nao."""
    from lauda.summarize import pick_model

    escolhido, motivo = pick_model(
        _options("http://127.0.0.1:1", tmp_path, "qwen3:14b"), ["qwen3:8b", "mistral"]
    )
    assert escolhido == "qwen3:8b"
    assert "nao esta baixado" in motivo.replace("ã", "a") or "não está baixado" in motivo
    assert "ollama pull qwen3:14b" in motivo, "e diz como ter o maior"


def test_sem_nenhum_dos_dois_diz_o_que_fazer(tmp_path: Path):
    from lauda.summarize import pick_model

    escolhido, motivo = pick_model(
        _options("http://127.0.0.1:1", tmp_path, "qwen3:14b"), ["mistral"]
    )
    assert escolhido is None
    assert "ollama pull qwen3:14b" in motivo


def test_a_troca_de_modelo_aparece_no_resultado(fake_ollama: str, tmp_path: Path, monkeypatch):
    """O relatorio precisa dizer que o resumo saiu com o modelo menor."""
    monkeypatch.setattr(_FakeOllama, "models", [{"name": "qwen3:8b"}])

    info = summarize_transcript(
        "uma transcricao qualquer para resumir.",
        _options(fake_ollama, tmp_path, "qwen3:14b"),
    )

    assert info.available is True
    assert info.model == "qwen3:8b", "o modelo relatado e o que respondeu"
    assert "qwen3:14b" in info.reason, "e o motivo da troca fica registrado"


def test_tag_pedida_e_exata(tmp_path: Path):
    """O bug que isto prende: 8B respondendo a um pedido de 14B, relatado como 14B."""
    from lauda.summarize import _listed

    assert _listed("qwen3:14b", ["qwen3:8b"]) is False
    assert _listed("qwen3:14b", ["qwen3:14b"]) is True


def test_pedido_sem_tag_aceita_a_familia(tmp_path: Path):
    from lauda.summarize import _listed

    assert _listed("qwen3", ["qwen3:14b"]) is True
    assert _listed("qwen3", ["mistral:7b"]) is False


# --------------------------------------------------------------------------- #
# Download do modelo com andamento (BACKLOG-027)
# --------------------------------------------------------------------------- #
def test_o_rotulo_do_download_fala_em_gigabytes():
    from lauda.summarize import _pull_label

    assert _pull_label("baixando", 1.5 * 1024**3, 9.0 * 1024**3) == (
        "baixando — 1,5 / 9,0 GB (17%)"
    )
    assert _pull_label("verificando", None, None) == "verificando"
    assert _pull_label("", None, None) == "baixando", "nunca deixar o rótulo vazio"


def test_o_download_relata_o_andamento(fake_ollama: str, tmp_path: Path, monkeypatch):
    """Sem ler o fluxo, a tela ficaria parada por vinte minutos."""
    monkeypatch.setattr(_FakeOllama, "pull_events", [
        {"status": "pulling manifest"},
        {"status": "downloading", "completed": 2 * 1024**3, "total": 8 * 1024**3},
        {"status": "downloading", "completed": 8 * 1024**3, "total": 8 * 1024**3},
        {"status": "success"},
    ])
    vistos: list[tuple] = []

    ok, mensagem = pull_model(
        _options(fake_ollama, tmp_path, "qwen3:14b"),
        "qwen3:14b",
        lambda fracao, texto: vistos.append((fracao, texto)),
    )

    assert ok is True
    assert "baixado" in mensagem
    assert [f for f, _ in vistos if f is not None] == [0.25, 1.0]
    assert any("GB" in texto for _, texto in vistos)


def test_erro_no_download_vira_mensagem(fake_ollama: str, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(_FakeOllama, "pull_events", [{"error": "modelo não existe"}])

    ok, mensagem = pull_model(
        _options(fake_ollama, tmp_path, "nao-existe"), "nao-existe"
    )
    assert ok is False
    assert "não existe" in mensagem


def test_host_invalido_nao_tenta_baixar(tmp_path: Path):
    ok, mensagem = pull_model(_options("file:///etc", tmp_path), "qwen3:14b")
    assert ok is False
    assert "http://" in mensagem
