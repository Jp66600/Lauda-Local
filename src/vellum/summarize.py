"""Resumo local opcional via Ollama (Fase 5).

Nenhuma chamada sai da máquina: o Ollama escuta em 127.0.0.1. Se ele não
estiver no ar, ou o modelo não estiver baixado, o bloco é omitido do relatório
com o motivo — o pipeline nunca quebra por causa disto.

Transcrições longas são resumidas em duas passadas (mapa → redução) para não
estourar a janela de contexto de modelos pequenos.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .config import JobOptions
from .types import SummaryInfo

log = logging.getLogger("vellum.summarize")

#: Checar se o servidor existe é rápido; gerar texto não é.
_PROBE_TIMEOUT = 5.0
_GENERATE_TIMEOUT = 600.0

#: Acima disto a transcrição é resumida em pedaços antes do resumo final.
_CHUNK_CHARS = 9000

_SYSTEM_PROMPT = (
    "Você é um analista que resume transcrições em português do Brasil. "
    "Responda SOMENTE com um objeto JSON válido, sem texto antes ou depois."
)

_SCHEMA_HINT = (
    '{"resumo": "3 a 6 frases", '
    '"topicos": ["tópico 1", "tópico 2"], '
    '"acoes": ["item de ação"], '
    '"citacoes": ["trecho literal relevante"]}'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

#: So falamos HTTP com o Ollama. Sem isto, um OLLAMA_HOST apontando para
#: `file:///...` faria o urlopen ler um arquivo do disco — um vetor bobo, mas
#: gratuito de fechar.
_ALLOWED_SCHEMES = ("http", "https")


def _safe_url(host: str, path: str) -> str:
    """Monta a URL do Ollama recusando esquemas que nao sejam HTTP."""
    from urllib.parse import urlparse

    url = host.rstrip("/") + path
    scheme = urlparse(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(
            f"OLLAMA_HOST precisa comecar com http:// ou https:// (recebido: {host!r})"
        )
    return url


def list_models(options: JobOptions) -> tuple[list[str] | None, str]:
    """Modelos baixados no Ollama local. `None` + motivo quando não dá para saber.

    Separado de `ollama_available` para que quem vai resumir descubra o servidor
    e escolha o modelo com **uma** chamada só.
    """
    try:
        url = _safe_url(options.ollama_host, "/api/tags")
    except ValueError as exc:
        return None, str(exc)

    try:
        with urllib.request.urlopen(url, timeout=_PROBE_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return None, f"Ollama não respondeu em {options.ollama_host} ({exc.__class__.__name__})."
    except json.JSONDecodeError:
        return None, f"Resposta inesperada do Ollama em {options.ollama_host}."

    return [str(model.get("name", "")) for model in payload.get("models", [])], "ok"


def ollama_available(options: JobOptions) -> tuple[bool, str]:
    """Checa se há um Ollama local respondendo e com um modelo utilizável."""
    names, motivo = list_models(options)
    if names is None:
        return False, motivo
    escolhido, motivo = pick_model(options, names)
    return escolhido is not None, motivo


def _listed(wanted: str, names: list[str]) -> bool:
    """O modelo pedido está entre os baixados?

    Pedido **com** tag é exato. Casar só pelo prefixo faria `qwen3:8b` atender
    um pedido de `qwen3:14b` — e o relatório sairia dizendo 14B quando quem
    respondeu foi o 8B. Pedido **sem** tag (`qwen3`) aceita qualquer versão da
    família, que é o que a pessoa quis dizer.
    """
    if ":" in wanted:
        return wanted in names
    return any(name.split(":")[0] == wanted for name in names)


def pick_model(options: JobOptions, names: list[str]) -> tuple[str | None, str]:
    """Escolhe entre o modelo pedido e o de reserva, dizendo qual e por quê.

    Baixar 9 GB no meio de um trabalho não é opção, e desistir do resumo porque
    o modelo grande não está lá também não: se o menor estiver baixado, ele
    serve — desde que o relatório registre a troca.
    """
    wanted = options.ollama_model
    if _listed(wanted, names):
        return wanted, "ok"

    reserva = options.ollama_fallback_model
    if reserva and reserva != wanted and _listed(reserva, names):
        log.info("Modelo '%s' não está baixado; usando '%s'.", wanted, reserva)
        return reserva, (
            f"o modelo '{wanted}' não está baixado; o resumo saiu com '{reserva}'. "
            f"Para usar o maior: ollama pull {wanted}"
        )

    return None, (
        f"Ollama está no ar, mas o modelo '{wanted}' não está baixado "
        f"(disponíveis: {', '.join(names) or 'nenhum'}). Rode: ollama pull {wanted}"
    )


#: Baixar um modelo de 9 GB numa conexão modesta passa de uma hora.
_PULL_TIMEOUT = 7200.0


def pull_model(
    options: JobOptions,
    model: str,
    on_progress: Callable[[float | None, str], None] | None = None,
) -> tuple[bool, str]:
    """Baixa um modelo no Ollama local, relatando o andamento.

    O `/api/pull` responde um fluxo de linhas JSON, cada uma com `status` e, nas
    etapas de download, `completed` e `total`. É daí que sai a porcentagem — sem
    ler o fluxo, a única alternativa seria uma tela parada por vinte minutos.

    Devolve (deu certo, mensagem). Nunca levanta: falha de rede vira mensagem.
    """
    try:
        url = _safe_url(options.ollama_host, "/api/pull")
    except ValueError as exc:
        return False, str(exc)

    corpo = json.dumps({"model": model, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        url, data=corpo, headers={"Content-Type": "application/json"}, method="POST"
    )

    ultimo = ""
    try:
        with urllib.request.urlopen(request, timeout=_PULL_TIMEOUT) as response:
            for linha in response:
                texto = linha.decode("utf-8", errors="replace").strip()
                if not texto:
                    continue
                try:
                    evento = json.loads(texto)
                except json.JSONDecodeError:
                    continue

                if erro := evento.get("error"):
                    return False, str(erro)

                ultimo = str(evento.get("status", "")) or ultimo
                total = evento.get("total")
                feito = evento.get("completed")
                fracao = None
                if isinstance(total, int | float) and total > 0 and isinstance(
                    feito, int | float
                ):
                    fracao = min(1.0, float(feito) / float(total))
                if on_progress is not None:
                    on_progress(fracao, _pull_label(ultimo, feito, total))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, f"falha ao baixar '{model}': {exc.__class__.__name__}: {exc}"

    log.info("Modelo '%s' baixado.", model)
    return True, f"modelo '{model}' baixado."


def _pull_label(status: str, feito: object, total: object) -> str:
    """Uma linha legível: "baixando — 1,4 / 9,0 GB (16%)"."""
    if not isinstance(total, int | float) or not isinstance(feito, int | float) or total <= 0:
        return status or "baixando"
    giga = 1024 ** 3
    return (
        f"{status} — {feito / giga:.1f} / {total / giga:.1f} GB "
        f"({feito / total * 100:.0f}%)"
    ).replace(".", ",")


def _chat(options: JobOptions, prompt: str, model: str | None = None) -> str:
    """Uma rodada de chat com o modelo local. Devolve o conteúdo bruto."""
    url = _safe_url(options.ollama_host, "/api/chat")
    body = json.dumps(
        {
            "model": model or options.ollama_model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(
        request, timeout=_GENERATE_TIMEOUT
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str((payload.get("message") or {}).get("content", ""))


def _parse_json_block(raw: str) -> dict[str, Any]:
    """Extrai o objeto JSON mesmo que o modelo tenha falado antes ou depois."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(raw or "")
    if not match:
        raise ValueError("o modelo não devolveu JSON.")
    return json.loads(match.group(0))


def _as_list(value: Any, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:limit]


def _split_chunks(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    """Divide o texto em blocos, quebrando em fim de frase quando possível."""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(". ", start + size // 2, end)
            if cut > 0:
                end = cut + 1
        chunks.append(text[start:end].strip())
        start = end
    return [chunk for chunk in chunks if chunk]


def summarize_transcript(text: str, options: JobOptions) -> SummaryInfo:
    """Gera resumo/tópicos/ações/citações com o modelo local."""
    if not text.strip():
        return SummaryInfo(available=False, reason="não há transcrição para resumir.")

    names, motivo = list_models(options)
    if names is None:
        return SummaryInfo(available=False, provider="ollama", reason=motivo)

    # Qual modelo respondeu importa para o relatório: pode não ser o pedido.
    modelo, motivo = pick_model(options, names)
    if modelo is None:
        return SummaryInfo(available=False, provider="ollama", reason=motivo)
    nota = "" if motivo == "ok" else motivo

    chunks = _split_chunks(text)
    try:
        if len(chunks) == 1:
            data = _parse_json_block(
                _chat(
                    options,
                    f"Resuma a transcrição abaixo no formato {_SCHEMA_HINT}\n\n"
                    f"TRANSCRIÇÃO:\n{chunks[0]}",
                    modelo,
                )
            )
        else:
            log.info("Transcrição longa: resumindo em %d partes.", len(chunks))
            partials: list[str] = []
            for index, chunk in enumerate(chunks, start=1):
                partial = _parse_json_block(
                    _chat(
                        options,
                        f"Esta é a parte {index} de {len(chunks)} de uma transcrição. "
                        f"Resuma esta parte no formato {_SCHEMA_HINT}\n\nPARTE:\n{chunk}",
                        modelo,
                    )
                )
                partials.append(str(partial.get("resumo", "")).strip())
            data = _parse_json_block(
                _chat(
                    options,
                    "Abaixo estão resumos parciais de uma mesma gravação, em ordem. "
                    f"Consolide tudo em um único resultado no formato {_SCHEMA_HINT}\n\n"
                    "RESUMOS PARCIAIS:\n" + "\n\n".join(partials),
                    modelo,
                )
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return SummaryInfo(
            available=False,
            provider="ollama",
            model=modelo,
            reason=f"falha de comunicação com o Ollama: {exc.__class__.__name__}: {exc}",
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return SummaryInfo(
            available=False,
            provider="ollama",
            model=modelo,
            reason=f"resposta do modelo não pôde ser interpretada: {exc}",
        )

    summary_text = str(data.get("resumo", "")).strip()
    if not summary_text:
        return SummaryInfo(
            available=False,
            provider="ollama",
            model=modelo,
            reason="o modelo devolveu um resumo vazio.",
        )

    return SummaryInfo(
        available=True,
        provider="ollama",
        model=modelo,
        summary=summary_text,
        reason=nota,
        topics=_as_list(data.get("topicos")),
        action_items=_as_list(data.get("acoes")),
        quotes=_as_list(data.get("citacoes")),
    )
