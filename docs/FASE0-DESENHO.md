# Fase 0 — Desenho

Documento de referência do contrato interno. Se mudar aqui, muda no código.

## Contratos das funções (assinaturas estáveis)

```python
# probe.py
probe_media(path: Path) -> ProbeResult                    # levanta ProbeError

# extract.py
temp_wav_path(prefix: str, keep: bool) -> ContextManager[Path]   # apaga no finally
extract_audio(source: Path, destination: Path, *, probe, stream_index, timeout) -> Path

# audio_stats.py
analyze_audio(wav: Path, *, duration: float | None) -> AudioDiagnostics
apply_speech_stats(diag, segments, duration) -> AudioDiagnostics
build_warnings(diag, probe, *, vad_enabled: bool) -> list[str]

# hardware.py
detect_hardware() -> HardwareInfo
memory_budget_gb(hw: HardwareInfo, device: str) -> float | None
select_runtime(*, requested_device, requested_compute_type, requested_model, hardware) -> RuntimeChoice
cpu_fallback(choice: RuntimeChoice, reason: str) -> RuntimeChoice

# transcribe.py
transcribe_audio(wav: Path, options: JobOptions, *, progress, media_duration) -> TranscriptionOutput

# align.py
refine_segment_boundaries(segments) -> int                 # nº de limites ajustados

# diarize.py
check_readiness(options) -> DiarizationReadiness           # qual backend dá para usar
diarize(wav, options, *, segments) -> DiarizationInfo      # nunca levanta
assign_speakers(segments, turns) -> int                    # maior sobreposição
renumber_speakers(segments) -> dict[str, str]              # SPEAKER_00, 01, …
speaker_stats(segments, duration) -> list[SpeakerStat]

# summarize.py / visual.py (opcionais, nunca levantam)
ollama_available(options) -> tuple[bool, str]
summarize_transcript(text, options) -> SummaryInfo
analyze_video(source, probe, options, *, output_dir) -> VisualInfo

# textstats.py
compute_stats(text, segments, *, language, duration, top_n) -> TextStats

# subtitles.py / report.py / serialize.py
render_srt(segments, *, with_speaker) -> str
render_vtt(segments, *, with_speaker) -> str
render_report(result: JobResult) -> str                    # determinístico
render_plain_transcript(result: JobResult) -> str
to_json_dict(result: JobResult) -> dict

# pipeline.py
process_media(options: JobOptions, progress: ProgressFn | None) -> JobResult

# ui.py
build_interface() -> gr.Blocks
launch(share: bool, port: int) -> None
```

`ProgressFn = Callable[[stage: str, fraction: float, message: str], None]`, com
`stage` em `probe | extract | vad | asr | align | diarize | render`.

## Regras de erro

| Situação | Comportamento |
|---|---|
| ffmpeg ausente | `FFmpegNotFoundError` — aborta com instruções de instalação |
| arquivo ilegível / vazio | `ProbeError` — aborta, exit code 2 |
| sem trilha de áudio | segue: relatório de metadados + `[INDISPONÍVEL] Transcrição` |
| GPU sem cuDNN / sem VRAM | fallback automático para CPU, nota no relatório |
| GPU falha no meio da transcrição | refaz tudo na CPU automaticamente |
| diarização/resumo/visual falham | `partial_failures`, pipeline continua |
| nenhum backend de diarização | `[INDISPONÍVEL] Diarização: <motivo>` |

## Schema do `.data.json`

```jsonc
{
  "schema_version": 1,
  "source":   { "name", "path", "size_bytes", "size_human", "sha256", "modified_at" },
  "probe":    { "format_name", "duration", "bit_rate", "tags", "video": [], "audio": [],
                "subtitles": [], "chapters": [], "raw": { /* ffprobe cru */ } },
  "processing": { "app_version", "engine", "engine_version", "model", "device",
                  "compute_type", "elapsed_seconds", "realtime_factor", "stages": [] },
  "language": { "code", "probability", "source": "auto|manual" },
  "speakers": [ { "speaker", "seconds", "ratio", "segments" } ],
  "diarization": { "available", "backend", "speaker_count", "reason" },
  "text": "…",
  "segments": [
    { "id": 0, "start": 0.0, "end": 1.2, "speaker": null, "text": "…",
      "words": [ { "start", "end", "word", "probability" } ],
      "avg_logprob", "no_speech_prob", "compression_ratio" }
  ],
  "stats": { "words", "unique_words", "characters", "segments", "words_per_minute", "top_words" },
  "summary": { "available", "provider", "model", "summary", "topics", "action_items", "quotes" },
  "visual": { "enabled", "scene_cuts", "thumbnails", "effective_resolution" },
  "diagnostics": { "mean_volume_db", "max_volume_db", "clipping_suspected",
                   "silence_ratio", "speech_ratio", "speech_detected", "warnings" },
  "partial_failures": [],
  "outputs": {}
}
```

## Template do `.report.txt`

Largura de 78 colunas, separadores `=` (nível 1) e `-` (nível 2), rótulos com
16 caracteres. Ordem fixa e obrigatória:

```
CABEÇALHO          arquivo, sha, data, engine
1. IDENTIDADE DO ARQUIVO
2. METADADOS TÉCNICOS         container, vídeo, áudio, legendas, tags, capítulos
3. QUALIDADE E DIAGNÓSTICO    volume, silêncio, fala, tempos por etapa, avisos
4. IDIOMA
5. TRANSCRIÇÃO COMPLETA       Bloco A (corrido), B (segmentos), C (palavras)
6. DIARIZAÇÃO
7. ESTRUTURA E RESUMO LOCAL   contagens, top-N, resumo Ollama
8. CAMADA VISUAL
9. RODAPÉ                     arquivos gerados, modelos, erros parciais
```

Bloco indisponível nunca some: vira `[INDISPONÍVEL] <bloco>: <motivo>`.

## Determinismo

Mesmo arquivo + mesmos parâmetros produzem o mesmo layout. Ordenações fixas:
tags por chave, top-words por `(-frequência, alfabética)`, falantes por
`(-tempo, nome)`, saídas por tipo. Variam apenas timestamps de execução e
tempos medidos.
