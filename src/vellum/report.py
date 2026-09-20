"""Renderização do relatório humano (.report.txt).

O TXT é um laudo: seções fixas, numeradas, na mesma ordem sempre. Quando um
bloco não pôde ser produzido, ele aparece como "[INDISPONÍVEL] <bloco>: motivo"
em vez de sumir — o leitor precisa saber o que faltou e por quê.
"""

from __future__ import annotations

from pathlib import Path

from .types import (
    AudioStreamInfo,
    JobResult,
    SegmentInfo,
    VideoStreamInfo,
)
from .utils import format_duration_human, format_timestamp, wrap_bullet, wrap_text

WIDTH = 78
_LABEL = 16

_H1 = "=" * WIDTH
_H2 = "-" * WIDTH

#: Tags de container que valem a pena mostrar com nome amigável.
_TAG_LABELS: dict[str, str] = {
    "title": "title",
    "artist": "artist",
    "album": "album",
    "album_artist": "album_artist",
    "date": "date",
    "creation_time": "creation_time",
    "encoder": "encoder",
    "comment": "comment",
    "description": "description",
    "genre": "genre",
    "track": "track",
    "location": "GPS (location)",
    "com.apple.quicktime.location.ISO6709": "GPS (ISO-6709)",
    "com.apple.quicktime.make": "device_make",
    "com.apple.quicktime.model": "device_model",
    "com.apple.quicktime.creationdate": "creation_date",
}


def _kv(label: str, value: object, *, indent: str = "") -> str:
    text = "—" if value in (None, "", []) else str(value)
    return f"{indent}{label:<{_LABEL}}: {text}"


def _section(number: int, title: str) -> list[str]:
    return ["", f"{number}. {title.upper()}", _H2]


def _unavailable(block: str, reason: str) -> list[str]:
    return wrap_text(f"[INDISPONÍVEL] {block}: {reason}", width=WIDTH)


def _fmt_float(value: float | None, suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}".replace(".", ",") + suffix


def _fmt_bitrate(bits_per_second: int | None) -> str:
    if not bits_per_second:
        return "—"
    return f"{bits_per_second:,} bps ({bits_per_second / 1000:.0f} kbps)".replace(",", ".")


# --------------------------------------------------------------------------- #
# Seções
# --------------------------------------------------------------------------- #
def _header(result: JobResult) -> list[str]:
    processing = result.processing
    engine = (
        f"{processing.engine} {processing.model} | device={processing.device} "
        f"| compute_type={processing.compute_type}"
    )
    return [
        _H1,
        "VELLUM — RELATÓRIO DE MÍDIA",
        _H1,
        _kv("Arquivo", result.source.name),
        _kv("SHA-256", result.source.sha256),
        _kv("Processado em", processing.finished_at),
        _kv("Engine", engine),
        _H2,
    ]


def _section_identity(result: JobResult) -> list[str]:
    source = result.source
    processing = result.processing
    lines = _section(1, "Identidade do arquivo")
    lines += [
        _kv("Nome", source.name),
        _kv("Caminho", source.path),
        # O replace só pode tocar no separador de milhar; size_human já vem
        # com vírgula decimal (438,96 KB) e não pode ser convertido de volta.
        _kv(
            "Tamanho",
            f"{source.size_bytes:,}".replace(",", ".") + f" bytes ({source.size_human})",
        ),
        _kv("SHA-256", source.sha256),
        _kv("Modificado em", source.modified_at),
        _kv("Processado em", processing.finished_at),
        "",
        _kv("Aplicação", f"{processing.app_name} {processing.app_version}"),
        _kv("Engine STT", f"{processing.engine} {processing.engine_version}"),
        _kv("Modelo", processing.model),
        _kv("Device", f"{processing.device} ({processing.device_name or 'desconhecido'})"),
        _kv("compute_type", processing.compute_type),
        _kv(
            "Modo",
            f"rápido (lotes de {processing.batch_size})"
            if processing.batch_size
            else "sequencial (trechos curtos)",
        ),
        _kv("Python", processing.python_version),
        _kv("Plataforma", processing.platform),
        _kv("ffmpeg", processing.ffmpeg_version),
    ]
    return lines


def _video_block(stream: VideoStreamInfo) -> list[str]:
    indent = "  "
    resolution = (
        f"{stream.width}x{stream.height}" if stream.width and stream.height else "—"
    )
    coded = (
        f"{stream.coded_width}x{stream.coded_height}"
        if stream.coded_width and stream.coded_height
        else "—"
    )
    return [
        f"{indent}Stream de vídeo #{stream.index}",
        _kv("codec", f"{stream.codec} ({stream.codec_long or 'sem descrição'})", indent=indent + "  "),
        _kv("perfil", stream.profile, indent=indent + "  "),
        _kv("resolução", resolution, indent=indent + "  "),
        _kv("coded", coded, indent=indent + "  "),
        _kv("SAR / DAR", f"{stream.sample_aspect_ratio or '—'} / {stream.display_aspect_ratio or '—'}", indent=indent + "  "),
        _kv("fps", f"{_fmt_float(stream.fps, decimals=3)} (média {_fmt_float(stream.avg_fps, decimals=3)})", indent=indent + "  "),
        _kv("bitrate", _fmt_bitrate(stream.bit_rate), indent=indent + "  "),
        _kv("pix_fmt", stream.pix_fmt, indent=indent + "  "),
        _kv("cor", f"space={stream.color_space or '—'} primaries={stream.color_primaries or '—'} transfer={stream.color_transfer or '—'}", indent=indent + "  "),
        _kv("HDR", "sim" if stream.is_hdr else "não", indent=indent + "  "),
        _kv("rotação", f"{stream.rotation}°" if stream.rotation is not None else "0°", indent=indent + "  "),
        _kv("nb_frames", stream.nb_frames, indent=indent + "  "),
        _kv("idioma", stream.language, indent=indent + "  "),
    ]


def _audio_block(stream: AudioStreamInfo) -> list[str]:
    indent = "  "
    return [
        f"{indent}Stream de áudio #{stream.index}",
        _kv("codec", f"{stream.codec} ({stream.codec_long or 'sem descrição'})", indent=indent + "  "),
        _kv("perfil", stream.profile, indent=indent + "  "),
        _kv("sample_rate", f"{stream.sample_rate} Hz" if stream.sample_rate else "—", indent=indent + "  "),
        _kv("canais", f"{stream.channels} ({stream.channel_layout or 'layout desconhecido'})" if stream.channels else "—", indent=indent + "  "),
        _kv("bitrate", _fmt_bitrate(stream.bit_rate), indent=indent + "  "),
        _kv("bits/amostra", stream.bits_per_sample, indent=indent + "  "),
        _kv("duração", format_timestamp(stream.duration) if stream.duration else "—", indent=indent + "  "),
        _kv("idioma", stream.language, indent=indent + "  "),
        _kv("título", stream.title, indent=indent + "  "),
    ]


def _section_metadata(result: JobResult) -> list[str]:
    probe = result.probe
    lines = _section(2, "Metadados técnicos")
    lines += [
        "  Container",
        _kv("formato", f"{probe.format_name} ({probe.format_long_name or 'sem descrição'})", indent="    "),
        _kv("duração", f"{format_timestamp(probe.duration)}  ({_fmt_float(probe.duration, ' s')})", indent="    "),
        _kv("bitrate", _fmt_bitrate(probe.bit_rate), indent="    "),
        _kv("streams", probe.nb_streams, indent="    "),
    ]

    lines.append("")
    if probe.video:
        for video in probe.video:
            lines += _video_block(video)
            lines.append("")
    else:
        lines += ["  Stream de vídeo : nenhum", ""]

    if probe.audio:
        for audio in probe.audio:
            lines += _audio_block(audio)
            lines.append("")
    else:
        lines += ["  Stream de áudio : nenhum", ""]

    if probe.subtitles:
        lines.append("  Legendas embutidas")
        for subtitle in probe.subtitles:
            lines.append(
                f"    #{subtitle.index}: {subtitle.codec or '—'} "
                f"[{subtitle.language or 'idioma não declarado'}] {subtitle.title or ''}".rstrip()
            )
        lines.append("")

    lines.append("  Tags do container")
    if probe.tags:
        shown = False
        for key in sorted(probe.tags):
            label = _TAG_LABELS.get(key, key)
            value = probe.tags[key]
            for index, chunk in enumerate(wrap_text(value, width=WIDTH - 24) or ["—"]):
                lines.append(_kv(label if index == 0 else "", chunk, indent="    "))
            shown = True
        if not shown:  # pragma: no cover - defensivo
            lines.append("    (nenhuma)")
    else:
        lines.append("    (nenhuma)")

    lines.append("")
    lines.append("  Capítulos")
    if probe.chapters:
        for chapter in probe.chapters:
            lines.append(
                f"    [{format_timestamp(chapter.start)} → {format_timestamp(chapter.end)}] "
                f"{chapter.title or '(sem título)'}"
            )
    else:
        lines.append("    (nenhum)")

    return lines


def _section_quality(result: JobResult) -> list[str]:
    diagnostics = result.diagnostics
    processing = result.processing
    lines = _section(3, "Qualidade e diagnóstico")
    lines += [
        _kv("Trilha de áudio", "sim" if result.probe.has_audio else "não"),
        _kv(
            "Fala detectada",
            "—" if diagnostics.speech_detected is None else ("sim" if diagnostics.speech_detected else "não"),
        ),
        _kv("Volume médio", _fmt_float(diagnostics.mean_volume_db, " dB", 1)),
        _kv("Pico", _fmt_float(diagnostics.max_volume_db, " dB", 1)),
        _kv("Clipping", "suspeito" if diagnostics.clipping_suspected else "não detectado"),
        _kv(
            "Silêncio",
            f"{format_duration_human(diagnostics.silence_seconds)} "
            f"({_fmt_float((diagnostics.silence_ratio or 0) * 100, '%', 1)} do arquivo)",
        ),
        _kv(
            "Fala",
            f"{format_duration_human(diagnostics.speech_seconds)} "
            f"({_fmt_float((diagnostics.speech_ratio or 0) * 100, '%', 1)} do arquivo)"
            if diagnostics.speech_seconds is not None
            else "—",
        ),
        _kv("Segmentos VAD", diagnostics.vad_segments),
        "",
        _kv("Tempo total", f"{_fmt_float(processing.elapsed_seconds, ' s', 1)}"),
        _kv(
            "Velocidade",
            f"{_fmt_float(processing.realtime_factor, 'x tempo real', 2)}"
            if processing.realtime_factor
            else "—",
        ),
    ]

    if processing.stages:
        lines.append("")
        lines.append("  Tempo por etapa")
        for stage in processing.stages:
            lines.append(
                f"    {stage.name:<12} {_fmt_float(stage.seconds, ' s', 2):>12}   [{stage.status}]"
            )

    lines.append("")
    lines.append("  Avisos")
    if diagnostics.warnings:
        for warning in diagnostics.warnings:
            lines += wrap_bullet(warning, width=WIDTH)
    else:
        lines.append("    (nenhum)")
    return lines


def _section_language(result: JobResult) -> list[str]:
    language = result.language
    lines = _section(4, "Idioma")
    if not language.code:
        return lines + _unavailable("Idioma", "não houve transcrição para detectar o idioma.")
    origem = "detectado automaticamente" if language.source == "auto" else "definido pelo usuário"
    lines += [
        _kv("Idioma", language.code),
        _kv("Origem", origem),
        _kv(
            "Confiança",
            _fmt_float((language.probability or 0) * 100, "%", 1) if language.probability else "—",
        ),
    ]
    return lines


def _paragraphs(segments: list[SegmentInfo], gap: float = 1.5, max_chars: int = 700) -> list[str]:
    """Agrupa segmentos em parágrafos por pausa longa ou tamanho máximo."""
    paragraphs: list[str] = []
    buffer: list[str] = []
    previous_end: float | None = None
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        long_pause = previous_end is not None and (segment.start - previous_end) > gap
        too_long = sum(len(part) for part in buffer) > max_chars
        if buffer and (long_pause or too_long):
            paragraphs.append(" ".join(buffer))
            buffer = []
        buffer.append(text)
        previous_end = segment.end
    if buffer:
        paragraphs.append(" ".join(buffer))
    return paragraphs


def _coverage_block(result: JobResult) -> list[str]:
    """Quanto da linha do tempo virou texto — e o que ficou de fora.

    Fica dentro da seção 5, e não numa seção nova, porque a ordem das nove
    seções do relatório é fixa desde o primeiro dia.
    """
    cobertura = result.coverage
    if not cobertura.analyzed:
        return _unavailable("Cobertura", cobertura.reason or "não foi possível medir.")

    lines = ["[BLOCO A2] Cobertura da linha do tempo", ""]
    lines.append(_kv("Transcrito", f"{(cobertura.ratio or 0) * 100:.1f}% do arquivo"))
    lines.append(
        _kv("Com fala", f"{_fmt_float(cobertura.covered_seconds, ' s')}"
                       f" de {_fmt_float(cobertura.duration, ' s')}")
    )
    lines.append(_kv("Silêncio medido", _fmt_float(cobertura.silence_seconds, " s")))

    if not cobertura.gaps:
        lines.append(_kv("Sem texto", "nenhum trecho fora do silêncio"))
        lines.append("")
        return lines

    lines.append(
        _kv(
            "Sem texto",
            f"{len(cobertura.gaps)} trecho(s), somando "
            f"{_fmt_float(cobertura.gap_seconds, ' s')}",
        )
    )
    lines.append("")
    lines.append("  Onde o áudio não é silêncio e mesmo assim não virou texto:")
    for inicio, fim in cobertura.gaps[:20]:
        lines.append(
            f"    {format_timestamp(inicio)} → {format_timestamp(fim)}"
            f"  ({fim - inicio:.1f} s)"
        )
    if len(cobertura.gaps) > 20:
        lines.append(f"    ... e mais {len(cobertura.gaps) - 20}.")
    lines.append("")
    return lines


def _section_transcript(result: JobResult) -> list[str]:
    lines = _section(5, "Transcrição completa")
    if not result.segments:
        return lines + _unavailable(
            "Transcrição", "nenhum segmento de fala foi produzido para este arquivo."
        )

    lines += ["[BLOCO A] Texto corrido", ""]
    for paragraph in _paragraphs(result.segments):
        lines += wrap_text(paragraph, width=WIDTH)
        lines.append("")

    lines += _coverage_block(result)

    lines += ["[BLOCO B] Segmentos com timestamps", ""]
    has_speakers = any(segment.speaker for segment in result.segments)
    for segment in result.segments:
        stamp = f"[{format_timestamp(segment.start)} → {format_timestamp(segment.end)}]"
        speaker = f" {segment.speaker or 'SPEAKER_??'}:" if has_speakers else ""
        prefix = f"{stamp}{speaker} "
        wrapped = wrap_text(segment.text, width=WIDTH - len(prefix)) or [""]
        lines.append(prefix + wrapped[0])
        for extra in wrapped[1:]:
            lines.append(" " * len(prefix) + extra)

    if result.processing.word_timestamps:
        lines += ["", "[BLOCO C] Timestamps por palavra", ""]
        any_words = False
        for segment in result.segments:
            if not segment.words:
                continue
            any_words = True
            lines.append(f"  Segmento #{segment.id} [{format_timestamp(segment.start)}]")
            for word in segment.words:
                confidence = (
                    f"  p={word.probability:.2f}".replace(".", ",")
                    if word.probability is not None
                    else ""
                )
                lines.append(
                    f"    {format_timestamp(word.start)} → {format_timestamp(word.end)}  "
                    f"{word.word.strip()}{confidence}"
                )
        if not any_words:
            lines += _unavailable(
                "Timestamps por palavra", "a engine não retornou marcação em nível de palavra."
            )
    return lines


def _section_diarization(result: JobResult) -> list[str]:
    lines = _section(6, "Diarização")
    diarization = result.diarization
    if not diarization.available:
        lines += _unavailable("Diarização", diarization.reason or "motivo não informado.")
        lines.append("")
        lines += wrap_text(
            "A transcrição acima segue válida; apenas a atribuição de falantes não foi feita.",
            width=WIDTH,
        )
        return lines

    lines += [
        _kv("Backend", diarization.backend),
        _kv("Falantes", diarization.speaker_count),
        "",
        "  Tempo de fala por falante",
    ]
    for stat in diarization.speakers:
        share = _fmt_float(stat.ratio * 100, "%", 1).rjust(6)
        lines.append(
            f"    {stat.speaker:<14} {format_duration_human(stat.seconds):>12}  "
            f"({share})  {stat.segments} segmento(s)"
        )
    return lines


def _section_structure(result: JobResult) -> list[str]:
    stats = result.stats
    lines = _section(7, "Estrutura e resumo local")
    lines += [
        _kv("Palavras", f"{stats.words:,}".replace(",", ".")),
        _kv("Palavras únicas", f"{stats.unique_words:,}".replace(",", ".")),
        _kv("Caracteres", f"{stats.characters:,}".replace(",", ".")),
        _kv("Sem espaços", f"{stats.characters_no_spaces:,}".replace(",", ".")),
        _kv("Segmentos", stats.segments),
        _kv("Ritmo", f"{_fmt_float(stats.words_per_minute, ' palavras/min', 1)}"),
        "",
        "  Palavras mais frequentes"
        + (
            f" (stopwords de '{stats.stopwords_language}' removidas)"
            if stats.stopwords_language
            else " (sem lista de stopwords para este idioma)"
        ),
    ]
    if stats.top_words:
        for position, (word, count) in enumerate(stats.top_words, start=1):
            lines.append(f"    {position:>2}. {word:<24} {count:>5}")
    else:
        lines.append("    (nenhuma)")

    lines.append("")
    summary = result.summary
    if summary.available:
        lines.append(f"  Resumo local ({summary.provider} / {summary.model})")
        for paragraph in (summary.summary or "").split("\n"):
            lines += wrap_text(paragraph, width=WIDTH - 4, indent="    ")
        if summary.topics:
            lines += ["", "  Tópicos"]
            lines += [f"    - {topic}" for topic in summary.topics]
        if summary.action_items:
            lines += ["", "  Itens de ação"]
            lines += [f"    - {item}" for item in summary.action_items]
        if summary.quotes:
            lines += ["", "  Citações"]
            lines += [f"    - {quote}" for quote in summary.quotes]
    else:
        lines += _unavailable("Resumo com LLM local", summary.reason or "bloco desativado.")
    return lines


def _section_visual(result: JobResult) -> list[str]:
    lines = _section(8, "Camada visual")
    visual = result.visual
    if not visual.enabled:
        return lines + _unavailable("Camada visual", visual.reason or "desligada (use --visual).")

    lines += [
        _kv("Res. codificada", visual.effective_resolution),
        _kv("Res. exibida", visual.display_resolution),
        _kv(
            "Cortes de cena",
            f"{visual.scene_cuts} (limiar {_fmt_float(visual.scene_threshold)})",
        ),
        _kv("Thumbnails", f"{len(visual.thumbnails)} a cada {visual.thumbnail_interval:.0f} s"),
    ]
    if visual.thumbnails:
        lines.append("")
        lines.append("  Arquivos gerados (pasta sidecar)")
        for name in visual.thumbnails[:40]:
            lines.append(f"    {name}")
        if len(visual.thumbnails) > 40:
            lines.append(f"    … e mais {len(visual.thumbnails) - 40} arquivo(s)")
    if visual.reason:
        lines.append("")
        lines += wrap_text(f"Observação: {visual.reason}", width=WIDTH)
    return lines


def _section_footer(result: JobResult) -> list[str]:
    lines = _section(9, "Rodapé")
    lines.append("  Arquivos gerados")
    if result.outputs:
        for kind in sorted(result.outputs):
            lines.append(f"    {kind:<15} {result.outputs[kind]}")
    else:
        lines.append("    (nenhum)")

    # Por que a legenda ficou com esse ritmo: a resposta tem de estar aqui, não
    # só na tela de quem rodou.
    if any(tipo in result.outputs for tipo in ("srt", "vtt")):
        alvos = {
            "curta": "curta (1 a 2 s por legenda)",
            "equilibrada": "equilibrada (5 a 8 s por legenda)",
            "longa": "longa (blocos de até 1 min)",
        }
        densidade = result.processing.subtitle_density
        if densidade:
            lines.append("")
            lines.append(_kv("Tamanho das legendas", alvos.get(densidade, densidade)))

    lines += [
        "",
        _kv("Pasta de saída", str(Path(next(iter(result.outputs.values()), ".")).parent)),
        _kv("Modelos", result.processing.model_path or "—"),
        "",
        "  Erros parciais",
    ]
    if result.partial_failures:
        for failure in result.partial_failures:
            lines += wrap_bullet(failure, width=WIDTH)
    else:
        lines.append("    (nenhum)")

    lines += [
        "",
        _H2,
        "Processamento 100% local. Nenhum byte deste arquivo saiu desta máquina.",
        _H1,
    ]
    return lines


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #
def render_report(result: JobResult) -> str:
    """Monta o relatório completo. Determinístico para a mesma entrada."""
    lines: list[str] = []
    lines += _header(result)
    lines += _section_identity(result)
    lines += _section_metadata(result)
    lines += _section_quality(result)
    lines += _section_language(result)
    lines += _section_transcript(result)
    lines += _section_diarization(result)
    lines += _section_structure(result)
    lines += _section_visual(result)
    lines += _section_footer(result)
    return "\n".join(lines).rstrip() + "\n"


def render_plain_transcript(result: JobResult) -> str:
    """Texto corrido puro, sem cabeçalhos — o `.transcript.txt`."""
    paragraphs = _paragraphs(result.segments)
    if not paragraphs:
        return ""
    blocks = ["\n".join(wrap_text(paragraph, width=WIDTH)) for paragraph in paragraphs]
    return "\n\n".join(blocks) + "\n"


def write_report(path: Path, result: JobResult) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(result), encoding="utf-8", newline="\n")
    return path


def write_plain_transcript(path: Path, result: JobResult) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_plain_transcript(result), encoding="utf-8", newline="\n")
    return path
