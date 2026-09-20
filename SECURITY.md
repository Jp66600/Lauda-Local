# Segurança

## Como relatar uma falha

**Não abra uma issue pública.** Use o
[Security Advisory privado](https://github.com/Jp66600/vellum/security/advisories/new)
do GitHub — só o mantenedor enxerga.

Diga o que você conseguiu fazer, com que arquivo ou entrada, e em qual versão
(ela aparece no alto de qualquer laudo, na linha `Aplicação`). Resposta em até
uma semana; este é um projeto pequeno, feito nas horas vagas.

## Versões

Só a última versão recebe correção. O projeto está em beta.

| Versão | Suportada |
|---|---|
| 0.9.x-beta | sim |
| anteriores | não |

## O modelo de ameaça

O aplicativo roda com os privilégios do usuário, na máquina dele, sobre arquivos
que ele mesmo escolheu. O que o projeto **garante**:

- **Nenhum byte do seu arquivo sai da máquina.** Não há upload, telemetria nem
  API paga. O único acesso à rede é o download dos modelos, na primeira vez, do
  Hugging Face — e depois disso ele funciona offline para sempre.
- **O arquivo de mídia nunca é executado.** Ele é lido pelo ffmpeg, sempre
  invocado por lista de argumentos, nunca por shell — não há interpolação de
  nome de arquivo em linha de comando.
- **O `.data.json` e o laudo não carregam segredo.** O `HF_TOKEN` é removido
  antes de o trabalho atravessar para o processo filho, porque esse dicionário
  vira arquivo temporário em disco.
- **O Ollama, quando ligado, só fala com `127.0.0.1`** e o esquema da URL é
  validado.

O que o projeto **não** protege:

- Da sua própria máquina. Se ela estiver comprometida, o laudo em disco também
  está.
- Dos modelos que você baixa. Eles vêm do Hugging Face; o projeto não os audita.
- Do conteúdo do que você processa. O laudo tem a transcrição inteira em texto
  puro — trate a pasta de saída com o mesmo cuidado que trataria o vídeo.

Detalhamento completo na seção 7 de `docs/Vellum-Decisoes-Tecnicas.pdf`.

## Fora de escopo

- O instalador não tem assinatura digital (custa centenas de dólares por ano).
  O SmartScreen do Windows vai avisar, e isso é esperado.
- Ataques que exigem acesso físico ou conta de administrador na máquina.
