# Licenças

## Este projeto

Vellum é distribuído sob a licença **MIT**.

## Dependências Python

| Pacote | Licença | Observação |
|---|---|---|
| faster-whisper | MIT | wrapper do Whisper sobre CTranslate2 |
| ctranslate2 | MIT | runtime de inferência (CPU/CUDA) |
| av (PyAV) | BSD-3-Clause | binding do FFmpeg usado pelo faster-whisper |
| onnxruntime | MIT | executa o Silero VAD |
| huggingface-hub | Apache-2.0 | download e cache dos pesos |
| tokenizers | Apache-2.0 | tokenização |
| numpy | BSD-3-Clause | dependência do CTranslate2 |
| typer / click | MIT / BSD-3-Clause | CLI |
| rich | MIT | terminal |
| python-dotenv | BSD-3-Clause | `.env` |
| pytest | MIT | testes |

## Dependências opcionais (Fase 3+)

| Pacote | Licença | Observação |
|---|---|---|
| torch / torchaudio | BSD-3-Clause | necessário para a diarização |
| speechbrain | Apache-2.0 | backend ECAPA de diarização (sem token) |
| pyannote.audio | MIT (código) | **os pesos têm termos próprios**, ver abaixo |
| gradio | Apache-2.0 | interface local |
| nvidia-cublas-cu12 / nvidia-cudnn-cu12 | NVIDIA EULA proprietária | bibliotecas CUDA opcionais, redistribuídas pela NVIDIA no PyPI |

## Dependência de sistema

**FFmpeg** — licença **LGPL-2.1+** ou **GPL-2.0+**, dependendo de como o build
foi compilado (builds com `--enable-gpl`, como os do Gyan.dev, são GPL). Este
projeto **não redistribui** o FFmpeg: ele apenas chama o binário que você
instalou. A licença aplicável é a do build presente na sua máquina.

## Pesos dos modelos

- **Whisper (OpenAI)** — pesos oficiais publicados sob **MIT**, incluindo
  `large-v3` e `large-v3-turbo`. As conversões para CTranslate2 usadas pelo
  faster-whisper (Systran, mobiuslabsgmbh e afins) mantêm a licença MIT dos
  pesos originais.
- **Silero VAD** — MIT.
- **speechbrain/spkrec-ecapa-voxceleb** — Apache-2.0, sem restrição de acesso.
  Treinado no VoxCeleb, cujo uso é destinado a pesquisa.
- **pyannote/speaker-diarization-3.1** e **pyannote/segmentation-3.0** — código
  MIT, mas os pesos são **gated** no Hugging Face: exigem conta, aceite dos
  termos de uso e são de uso livre para pesquisa e uso comercial mediante
  aceite. Leia os termos no card de cada modelo antes de usar em produção.

Nenhum modelo aqui envia dados para servidores externos em tempo de execução; o
único acesso à rede é o download inicial dos pesos.
