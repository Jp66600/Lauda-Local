"""CLI do Lauda Local (Typer + Rich)."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from . import APP_NAME, APP_VERSION
from .config import (
    DEVICE_CHOICES,
    DIARIZE_BACKEND_CHOICES,
    MODEL_CHOICES,
    JobOptions,
    defaults_from_env,
)
from .cues import DEFAULT_DENSITY
from .errors import LaudaError
from .limits import ResourceLimits
from .logging_setup import setup_logging
from .pipeline import ensure_processable, process_media
from .runner import run_with_recovery

console = Console()
app = typer.Typer(
    name="lauda",
    help=f"{APP_NAME} {APP_VERSION} — extração local de informação de áudio e vídeo.",
    no_args_is_help=True,
    add_completion=False,
)


def _load_dotenv() -> None:
    # Um .env ausente ou ilegivel nao pode impedir o programa de abrir.
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except Exception as exc:  # pragma: no cover - python-dotenv ausente
        logging.getLogger("lauda.cli").debug("Sem .env (%s).", exc)


def _fix_console_encoding() -> None:
    """Evita UnicodeEncodeError no console legado do Windows (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        # Sem reconfigure seguimos com a codificacao do sistema: acentos
        # errados sao menos graves que o programa nao abrir.
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover - stream sem reconfigure
            logging.getLogger("lauda.cli").debug("Console sem UTF-8 (%s).", exc)


@app.command("run")
def run_command(
    entrada: Path = typer.Argument(..., help="Arquivo de áudio ou vídeo a processar."),
    output: Path = typer.Option(
        Path("./saida"), "--output", "-o", help="Pasta de saída dos relatórios."
    ),
    model: str = typer.Option(
        None, "--model", "-m", help=f"Modelo Whisper: {', '.join(MODEL_CHOICES)}."
    ),
    lang: str = typer.Option(
        None, "--lang", "-l", help="Idioma: auto, pt, en, es, ... (auto detecta)."
    ),
    device: str = typer.Option(
        None, "--device", "-d", help=f"Device: {', '.join(DEVICE_CHOICES)}."
    ),
    compute_type: str = typer.Option(
        "auto", "--compute-type", help="int8, int8_float16, float16, float32 ou auto."
    ),
    beam_size: int = typer.Option(5, "--beam-size", help="Beam search (1 = mais rápido)."),
    vad: bool = typer.Option(True, "--vad/--no-vad", help="Filtro de voz (reduz alucinação)."),
    words: bool = typer.Option(
        False, "--words/--no-words", help="Timestamps por palavra (Bloco C)."
    ),
    diarize: bool = typer.Option(
        False, "--diarize/--no-diarize", help="Diarização de falantes (best-effort)."
    ),
    diarize_backend: str = typer.Option(
        "auto",
        "--diarize-backend",
        help=f"Backend da diarização: {', '.join(DIARIZE_BACKEND_CHOICES)} "
        "(ecapa não exige token do Hugging Face).",
    ),
    num_speakers: int | None = typer.Option(
        None, "--num-speakers", help="Número exato de falantes, se você souber."
    ),
    min_speakers: int | None = typer.Option(
        None, "--min-speakers", help="Mínimo de falantes esperado."
    ),
    max_speakers: int | None = typer.Option(
        None, "--max-speakers", help="Máximo de falantes esperado."
    ),
    speaker_threshold: float = typer.Option(
        0.30,
        "--speaker-threshold",
        help="Distância de cosseno para separar falantes no backend ecapa "
        "(menor = mais falantes).",
    ),
    srt: bool = typer.Option(False, "--srt", help="Também gerar legenda .srt."),
    vtt: bool = typer.Option(False, "--vtt", help="Também gerar legenda .vtt."),
    densidade: str = typer.Option(
        DEFAULT_DENSITY, "--legenda-tamanho",
        help="Tamanho das legendas: curta (1-2 s), equilibrada (5-8 s) ou longa.",
    ),
    json_out: bool = typer.Option(True, "--json/--no-json", help="Gerar o .data.json."),
    visual: bool = typer.Option(
        False, "--visual", help="Camada visual leve (cortes de cena + thumbnails)."
    ),
    summarize: bool = typer.Option(
        False, "--summarize", help="Bloco de resumo via Ollama local, se disponível."
    ),
    cpu: int = typer.Option(
        100, "--cpu", min=10, max=100, help="Limite de CPU em % (vira nº de threads)."
    ),
    ram: int = typer.Option(
        50, "--ram", min=10, max=100, help="Limite de RAM em % (teto para escolher o modelo)."
    ),
    gpu: int = typer.Option(
        100, "--gpu", min=0, max=100, help="Limite de GPU em % (0 desliga a placa)."
    ),
    vram: int = typer.Option(
        100, "--vram", min=10, max=100, help="Limite de VRAM em % (teto para escolher o modelo)."
    ),
    recover: bool = typer.Option(
        True,
        "--recover/--no-recover",
        help="Supervisiona o processamento: mata se travar e retoma do ponto salvo.",
    ),
    resume: bool = typer.Option(
        True, "--resume/--no-resume", help="Usar pontos de retomada salvos."
    ),
    stall_timeout: float = typer.Option(
        300.0, "--stall-timeout", help="Segundos sem sinal antes de considerar travado."
    ),
    batch_size: int = typer.Option(
        0,
        "--batch-size",
        min=0,
        max=32,
        help="Modo rápido: transcreve em lotes (0 = desligado). Fica ~2x mais "
        "rápido na GPU, mas os trechos saem ~6x mais longos — pior para legenda "
        "e diarização.",
    ),
    attempts: int = typer.Option(
        3, "--attempts", min=1, max=5, help="Quantas tentativas antes de desistir."
    ),
    top_words: int = typer.Option(25, "--top-words", help="Quantas palavras frequentes listar."),
    keep_temp: bool = typer.Option(False, "--keep-temp", help="Não apagar o WAV temporário."),
    initial_prompt: str | None = typer.Option(
        None, "--prompt", help="Prompt inicial (nomes próprios, jargão)."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log detalhado."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Só avisos e erros."),
) -> None:
    """Processa um arquivo e gera relatório TXT + JSON (+ legendas)."""
    _fix_console_encoding()
    _load_dotenv()
    log = setup_logging(verbose=verbose, quiet=quiet)
    defaults = defaults_from_env()

    try:
        options = JobOptions(
            input_path=entrada,
            output_dir=output,
            model=model or defaults["model"],
            language=lang or defaults["language"],
            device=device or defaults["device"],
            compute_type=compute_type,
            beam_size=beam_size,
            batch_size=batch_size,
            vad=vad,
            word_timestamps=words,
            diarize=diarize,
            diarize_backend=diarize_backend,
            num_speakers=num_speakers,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            speaker_threshold=speaker_threshold,
            write_srt=srt,
            write_vtt=vtt,
            subtitle_density=densidade,
            write_json=json_out,
            visual=visual,
            summarize=summarize,
            top_words=top_words,
            keep_temp=keep_temp,
            initial_prompt=initial_prompt,
            hf_token=os.environ.get("HF_TOKEN") or None,
            limits=ResourceLimits(
                cpu_percent=cpu, ram_percent=ram, gpu_percent=gpu, vram_percent=vram
            ),
        )
        ensure_processable(options)
    except (ValueError, LaudaError) as exc:
        console.print(f"[bold red]Erro:[/bold red] {exc}")
        raise typer.Exit(code=2) from exc

    console.print(
        Panel.fit(
            f"[bold]{APP_NAME}[/bold] {APP_VERSION}\n"
            f"Arquivo : {options.input_path.name}\n"
            f"Modelo  : {options.model}   Device: {options.device}   Idioma: {options.language}\n"
            f"Saída   : {options.output_dir}",
            border_style="cyan",
        )
    )

    columns = (
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    )
    try:
        with Progress(*columns, console=console, disable=quiet) as progress_bar:
            task = progress_bar.add_task("iniciando", total=100)

            def report(stage: str, fraction: float, message: str) -> None:
                progress_bar.update(
                    task, completed=min(100.0, fraction * 100), description=f"{stage}: {message}"
                )

            if recover:
                result, tentativas = run_with_recovery(
                    options,
                    progress=report,
                    on_event=lambda kind, message: console.print(
                        f"[yellow]{kind}:[/yellow] {message}"
                    ),
                    stall_timeout=stall_timeout,
                    max_attempts=attempts,
                )
                if len(tentativas) > 1:
                    result.partial_failures.append(
                        f"O processamento precisou de {len(tentativas)} tentativas."
                    )
            else:
                result = process_media(options, progress=report, resume=resume)
    except LaudaError as exc:
        console.print(f"[bold red]Falhou:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:  # pragma: no cover - interativo
        console.print("[yellow]Interrompido pelo usuário.[/yellow]")
        raise typer.Exit(code=130) from None
    except Exception as exc:  # pragma: no cover - bug real
        log.exception("Erro inesperado")
        console.print(f"[bold red]Erro inesperado:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    table = Table(title="Arquivos gerados", show_header=True, header_style="bold cyan")
    table.add_column("Tipo")
    table.add_column("Caminho", overflow="fold")
    for kind in sorted(result.outputs):
        table.add_row(kind, result.outputs[kind])
    console.print(table)

    if result.partial_failures:
        console.print("[yellow]Avisos:[/yellow]")
        for failure in result.partial_failures:
            console.print(f"  • {failure}")

    console.print(
        f"[green]Concluído[/green] em {result.processing.elapsed_seconds:.1f}s "
        f"({result.processing.realtime_factor or 0:.2f}x tempo real) — "
        f"{result.stats.words} palavras, {len(result.segments)} segmentos."
    )


@app.command("doctor")
def doctor_command() -> None:
    """Verifica ffmpeg, hardware, modelos e dependências opcionais."""
    _fix_console_encoding()
    _load_dotenv()
    setup_logging()

    from .diarize import check_readiness
    from .hardware import detect_hardware, select_runtime

    table = Table(title=f"{APP_NAME} {APP_VERSION} — diagnóstico", show_header=False)

    try:
        from .ffmpeg_tools import resolve_tools

        tools = resolve_tools()
        table.add_row("ffmpeg", f"[green]OK[/green] {tools.version or ''} ({tools.ffmpeg})")
        table.add_row("ffprobe", f"[green]OK[/green] ({tools.ffprobe})")
    except LaudaError as exc:
        table.add_row("ffmpeg", f"[red]AUSENTE[/red] — {exc.hint or exc.message}")

    hardware = detect_hardware()
    table.add_row("Hardware", hardware.summary)
    choice = select_runtime(requested_model="large-v3-turbo", hardware=hardware)
    table.add_row(
        "Escolha automática",
        f"device={choice.device}, compute_type={choice.compute_type}, modelo={choice.model}",
    )
    for note in choice.notes:
        table.add_row("", f"[yellow]{note}[/yellow]")

    try:
        import faster_whisper

        table.add_row("faster-whisper", f"[green]OK[/green] {faster_whisper.__version__}")
    except Exception as exc:
        table.add_row("faster-whisper", f"[red]AUSENTE[/red] — {exc}")

    models_dir = Path(os.environ.get("LAUDA_MODELS_DIR", "./models")).resolve()
    cached = sorted(path.name for path in models_dir.glob("models--*")) if models_dir.exists() else []
    table.add_row("Pasta de modelos", f"{models_dir} ({len(cached)} em cache)")
    for name in cached[:10]:
        table.add_row("", name)

    options = JobOptions(input_path=Path("."), output_dir=Path("."), models_dir=models_dir)
    readiness = check_readiness(options)
    table.add_row(
        "Diarização",
        f"[green]pronta[/green] ({readiness.reason})"
        if readiness.ready
        else f"[yellow]indisponível[/yellow] — {readiness.reason}",
    )

    try:
        import gradio

        table.add_row("Interface (Gradio)", f"[green]OK[/green] {gradio.__version__}")
    except Exception:
        table.add_row(
            "Interface (Gradio)",
            '[yellow]ausente[/yellow] — pip install "lauda[ui]"',
        )

    from .summarize import ollama_available

    ok, reason = ollama_available(options)
    table.add_row(
        "Resumo (Ollama)",
        f"[green]OK[/green] {options.ollama_model} em {options.ollama_host}"
        if ok
        else f"[yellow]indisponível[/yellow] — {reason}",
    )

    console.print(table)


@app.command("checkpoints")
def checkpoints_command(
    limpar: bool = typer.Option(
        False, "--limpar", help="Apaga TODOS os pontos de retomada guardados."
    ),
) -> None:
    """Lista (ou apaga) os pontos de retomada de trabalhos interrompidos."""
    _fix_console_encoding()
    from .checkpoint import CHECKPOINT_ROOT, CheckpointStore, purge_old

    if limpar:
        import shutil

        if CHECKPOINT_ROOT.exists():
            shutil.rmtree(CHECKPOINT_ROOT, ignore_errors=True)
        console.print("[green]Pontos de retomada apagados.[/green]")
        return

    removidos = purge_old()
    if removidos:
        console.print(f"[dim]{removidos} ponto(s) vencido(s) removido(s).[/dim]")

    if not CHECKPOINT_ROOT.exists():
        console.print("Nenhum trabalho interrompido. Nada a retomar.")
        return

    tabela = Table(title="Trabalhos interrompidos", header_style="bold cyan")
    tabela.add_column("Arquivo de origem")
    tabela.add_column("Parou em")
    tabela.add_column("Trechos")
    tabela.add_column("Tentativas")

    encontrados = 0
    for directory in sorted(CHECKPOINT_ROOT.iterdir()):
        if not directory.is_dir():
            continue
        salvo = CheckpointStore(directory.name, root=CHECKPOINT_ROOT).load()
        if salvo is None:
            continue
        encontrados += 1
        tabela.add_row(
            salvo.result.source.name,
            salvo.stage,
            str(len(salvo.result.segments)),
            str(salvo.attempts),
        )

    if encontrados:
        console.print(tabela)
        console.print(
            "[dim]Rodar o mesmo arquivo com as mesmas opções continua de onde parou.[/dim]"
        )
    else:
        console.print("Nenhum trabalho interrompido. Nada a retomar.")


@app.command("disco")
def disco_command(
    remover: str = typer.Option(
        None, "--remover", help="Apaga um modelo baixado (ex.: --remover small)."
    ),
) -> None:
    """Mostra quanto o aplicativo ocupa e o que dá para liberar."""
    _fix_console_encoding()
    _load_dotenv()
    from .checkpoint import CHECKPOINT_ROOT
    from .disk import (
        component_sizes,
        format_size,
        installed_models,
        remove_model,
        tree_size,
    )

    models_dir = Path(os.environ.get("LAUDA_MODELS_DIR", "./models")).resolve()

    if remover:
        apagados, liberado = remove_model(models_dir, remover)
        if not apagados:
            console.print(f"[yellow]Nenhum modelo chamado '{remover}' está baixado.[/yellow]")
            raise typer.Exit(code=1)
        console.print(
            f"[green]Removido:[/green] {', '.join(apagados)} "
            f"({format_size(liberado)} liberados)."
        )
        return

    tabela = Table(title="Espaço ocupado", header_style="bold cyan")
    tabela.add_column("Parte")
    tabela.add_column("Tamanho", justify="right")
    tabela.add_column("Dá para remover?")

    for nome, tamanho, nota in component_sizes(models_dir, CHECKPOINT_ROOT):
        tabela.add_row(nome, format_size(tamanho), nota)
    console.print(tabela)

    modelos = installed_models(models_dir)
    if modelos:
        tabela_modelos = Table(title="Modelos baixados", header_style="bold cyan")
        tabela_modelos.add_column("Modelo")
        tabela_modelos.add_column("Tamanho", justify="right")
        for nome, tamanho in modelos:
            tabela_modelos.add_row(nome, format_size(tamanho))
        console.print(tabela_modelos)
        console.print(
            "[dim]Para liberar espaço: lauda disco --remover <modelo>. "
            "Ele volta a ser baixado automaticamente quando for usado.[/dim]"
        )

    pontos = tree_size(CHECKPOINT_ROOT)
    if pontos:
        console.print(
            f"[dim]Pontos de retomada ocupam {format_size(pontos)}. "
            "Limpe com: lauda checkpoints --limpar[/dim]"
        )


@app.command("models")
def models_command() -> None:
    """Lista os modelos suportados e o custo aproximado de memória."""
    _fix_console_encoding()
    from .hardware import MODEL_MEMORY_GB, detect_hardware, memory_budget_gb

    hardware = detect_hardware()
    device = "GPU" if hardware.has_cuda else "CPU"
    budget = memory_budget_gb(hardware, "cuda" if hardware.has_cuda else "cpu")
    table = Table(title="Modelos Whisper suportados", header_style="bold cyan")
    table.add_column("Modelo")
    table.add_column("Memória aprox. (int8)")
    table.add_column(f"Cabe na {device}?")
    for name in MODEL_CHOICES:
        need = MODEL_MEMORY_GB.get(name, 3.6)
        fits = "[green]sim[/green]" if budget is None or need <= budget else "[yellow]não (será rebaixado)[/yellow]"
        table.add_row(name, f"{need:.1f} GB", fits)
    console.print(table)
    console.print(f"[dim]{hardware.summary}[/dim]")
    if budget is not None:
        console.print(f"[dim]Orçamento considerado para a {device}: {budget:.1f} GB[/dim]")


@app.command("app")
def app_command(
    theme: str = typer.Option(
        None, "--theme", help="Tema da janela: auto, claro ou escuro."
    ),
) -> None:
    """Abre o aplicativo em janela própria (sem navegador)."""
    from .desktop import main as desktop_main
    from .theme import THEME_CHOICES

    if theme is not None and theme not in THEME_CHOICES:
        console.print(
            f"[bold red]Erro:[/bold red] tema inválido: {theme!r}. "
            f"Use: {', '.join(THEME_CHOICES)}"
        )
        raise typer.Exit(code=2)

    raise typer.Exit(code=desktop_main(theme=theme))


@app.command("ui")
def ui_command(
    share: bool = typer.Option(False, "--share", help="Expor a UI na rede local."),
    port: int = typer.Option(
        0, "--port", help="Porta do servidor (0 = primeira livre a partir da 7860)."
    ),
) -> None:
    """Abre a interface no navegador (alternativa ao `app`, requer Gradio)."""
    _fix_console_encoding()
    _load_dotenv()
    setup_logging()
    try:
        from .ui import launch
    except ImportError as exc:
        console.print(
            "[yellow]A UI ainda não está disponível.[/yellow] "
            f"Instale o Gradio com: pip install \"lauda[ui]\"  ({exc})"
        )
        raise typer.Exit(code=3) from exc
    launch(share=share, port=port)


def main() -> None:
    # Antes de qualquer leitura de preferencia ou ponto de retomada: quem usou
    # o nome antigo mantem o que era dele.
    from .profile import migrate_legacy_profile

    migrate_legacy_profile()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
