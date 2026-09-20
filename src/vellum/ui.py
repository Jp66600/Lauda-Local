"""Interface local com Gradio (Fase 4).

Roda em 127.0.0.1: nada é publicado na internet. `--share` apenas expõe a
porta na rede local (`0.0.0.0`), sem túnel externo.

    vellum ui
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import gradio as gr

from . import APP_NAME, APP_VERSION
from .config import DEVICE_CHOICES, DIARIZE_BACKEND_CHOICES, MODEL_CHOICES, JobOptions
from .errors import VellumError
from .hardware import detect_hardware, select_runtime
from .pipeline import process_media
from .utils import format_duration_human

log = logging.getLogger("vellum.ui")

LANGUAGE_CHOICES = [
    ("Detectar automaticamente", "auto"),
    ("Português", "pt"),
    ("Inglês", "en"),
    ("Espanhol", "es"),
    ("Francês", "fr"),
    ("Alemão", "de"),
    ("Italiano", "it"),
    ("Japonês", "ja"),
]

#: Peso relativo de cada etapa na barra de progresso (soma 1,0).
_STAGE_LABELS = {
    "probe": "Lendo metadados",
    "extract": "Extraindo áudio",
    "vad": "Analisando o áudio",
    "asr": "Transcrevendo",
    "align": "Alinhando",
    "diarize": "Identificando falantes",
    "render": "Gerando relatório",
}

_CSS = """
.mi-header { text-align: center; }
.mi-footer { opacity: .7; font-size: .9em; text-align: center; }
"""

#: O Gradio 6 moveu `css` do construtor de Blocks para o launch().
_GRADIO_MAJOR = int(gr.__version__.split(".", 1)[0])


def _hardware_banner() -> str:
    hardware = detect_hardware()
    choice = select_runtime(requested_model="large-v3-turbo", hardware=hardware)
    extra = f" — sugestão: {choice.model} em {choice.device}"
    return f"{hardware.summary}{extra}"


def _run_job(
    file_obj: Any,
    output_dir: str,
    model: str,
    language: str,
    device: str,
    diarize: bool,
    diarize_backend: str,
    words: bool,
    make_srt: bool,
    make_vtt: bool,
    make_json: bool,
    visual: bool,
    summarize: bool,
    history: list[list[str]] | None,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, str, list[str], list[list[str]], list[list[str]]]:
    """Handler do botão Processar. Devolve (status, relatório, arquivos, histórico)."""
    history = list(history or [])
    if not file_obj:
        return "Escolha um arquivo primeiro.", "", [], history, history

    source = Path(getattr(file_obj, "name", file_obj))
    destination = Path(output_dir).expanduser() if output_dir.strip() else Path("./saida")

    try:
        options = JobOptions(
            input_path=source,
            output_dir=destination,
            model=model,
            language=language,
            device=device,
            diarize=diarize,
            diarize_backend=diarize_backend,
            word_timestamps=words,
            write_srt=make_srt,
            write_vtt=make_vtt,
            write_json=make_json,
            visual=visual,
            summarize=summarize,
        )
    except ValueError as exc:
        return f"Configuração inválida: {exc}", "", [], history, history

    def report(stage: str, fraction: float, message: str) -> None:
        label = _STAGE_LABELS.get(stage, stage)
        progress(min(1.0, fraction), desc=f"{label} — {message}")

    try:
        result = process_media(options, progress=report)
    except VellumError as exc:
        return f"Falhou: {exc}", "", [], history, history
    except Exception as exc:  # pragma: no cover - bug real
        log.exception("Erro inesperado na UI")
        return f"Erro inesperado: {exc}", "", [], history, history

    report_path = result.outputs.get("report.txt")
    text = Path(report_path).read_text(encoding="utf-8") if report_path else ""
    files = [path for path in result.outputs.values() if Path(path).exists()]

    status_lines = [
        f"Concluído em {result.processing.elapsed_seconds:.1f} s "
        f"({result.processing.realtime_factor or 0:.2f}x tempo real)",
        f"Modelo {result.processing.model} em {result.processing.device} "
        f"({result.processing.compute_type})",
        f"Idioma: {result.language.code or '—'} | "
        f"{result.stats.words} palavras em {len(result.segments)} segmentos",
    ]
    if result.diarization.available:
        status_lines.append(f"Falantes identificados: {result.diarization.speaker_count}")
    for failure in result.partial_failures:
        status_lines.append(f"⚠ {failure}")

    history.append(
        [
            source.name,
            result.processing.model,
            result.language.code or "—",
            format_duration_human(result.probe.duration),
            f"{result.processing.elapsed_seconds:.1f} s".replace(".", ","),
            str(destination),
        ]
    )
    return "\n".join(status_lines), text, files, history, history


def build_interface() -> gr.Blocks:
    blocks_kwargs: dict[str, Any] = {"title": f"{APP_NAME} {APP_VERSION}"}
    if _GRADIO_MAJOR < 6:
        blocks_kwargs["css"] = _CSS

    with gr.Blocks(**blocks_kwargs) as demo:
        gr.Markdown(
            f"# {APP_NAME}\n"
            "Extração local de informação de áudio e vídeo. "
            "**Nenhum arquivo sai desta máquina.**",
            elem_classes="mi-header",
        )
        gr.Markdown(f"`{_hardware_banner()}`")

        with gr.Row():
            with gr.Column(scale=1):
                file_input = gr.File(
                    label="Arraste um arquivo de áudio ou vídeo",
                    file_count="single",
                    type="filepath",
                )
                output_dir = gr.Textbox(
                    label="Pasta de saída", value="./saida", placeholder="./saida"
                )
                model = gr.Dropdown(
                    label="Modelo", choices=list(MODEL_CHOICES), value="small"
                )
                language = gr.Dropdown(
                    label="Idioma", choices=LANGUAGE_CHOICES, value="auto"
                )
                device = gr.Radio(
                    label="Device", choices=list(DEVICE_CHOICES), value="auto"
                )

                with gr.Accordion("Opções", open=True):
                    diarize = gr.Checkbox(label="Diarização de falantes", value=False)
                    diarize_backend = gr.Dropdown(
                        label="Backend da diarização",
                        choices=list(DIARIZE_BACKEND_CHOICES),
                        value="auto",
                        info="ecapa não exige token do Hugging Face.",
                    )
                    words = gr.Checkbox(label="Timestamps por palavra", value=False)
                    with gr.Row():
                        make_srt = gr.Checkbox(label="SRT", value=False)
                        make_vtt = gr.Checkbox(label="VTT", value=False)
                        make_json = gr.Checkbox(label="JSON", value=True)
                    visual = gr.Checkbox(
                        label="Camada visual (cortes de cena + thumbnails)", value=False
                    )
                    summarize = gr.Checkbox(
                        label="Resumo com Ollama local (se estiver rodando)", value=False
                    )

                run_button = gr.Button("Processar", variant="primary")

            with gr.Column(scale=2):
                status = gr.Textbox(label="Status", lines=6, interactive=False)
                report_view = gr.Textbox(label="Relatório", lines=28, interactive=False)
                downloads = gr.Files(label="Arquivos gerados")

        history_state = gr.State([])
        history_table = gr.Dataframe(
            headers=["Arquivo", "Modelo", "Idioma", "Duração", "Tempo", "Saída"],
            label="Histórico da sessão",
            interactive=False,
            wrap=True,
        )

        run_button.click(
            fn=_run_job,
            inputs=[
                file_input, output_dir, model, language, device,
                diarize, diarize_backend, words,
                make_srt, make_vtt, make_json, visual, summarize,
                history_state,
            ],
            outputs=[status, report_view, downloads, history_state, history_table],
        )

        gr.Markdown(
            "Processamento 100% offline. Os modelos são baixados uma vez e "
            "reutilizados a partir de `./models`.",
            elem_classes="mi-footer",
        )
    return demo


def launch(share: bool = False, port: int = 0) -> None:
    """Sobe o servidor local da UI.

    `port=0` deixa o Gradio procurar a primeira porta livre a partir da 7860 —
    importante para o atalho de duplo clique, que não deve quebrar só porque
    uma janela antiga do app ainda está aberta.
    """
    demo = build_interface()
    launch_kwargs: dict[str, Any] = {
        # S104 aceito e deliberado: `--share` existe justamente para expor a
        # interface na rede LOCAL. Sem a flag, escutamos so em 127.0.0.1.
        "server_name": "0.0.0.0" if share else "127.0.0.1",  # noqa: S104
        "server_port": port or None,
        "share": False,  # nunca cria túnel público
        "inbrowser": True,
    }
    if _GRADIO_MAJOR >= 6:
        launch_kwargs["css"] = _CSS
    else:  # o Gradio 5 ainda expõe a aba de API; a UI local não precisa dela
        launch_kwargs["show_api"] = False
    demo.queue().launch(**launch_kwargs)
