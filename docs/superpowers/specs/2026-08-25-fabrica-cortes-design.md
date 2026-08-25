# Fábrica de Cortes — Design

**Data:** 2026-08-25
**Status:** aguardando revisão

## 1. Objetivo

Esteira automatizada que transforma episódios longos de podcast em cortes
verticais legendados e os publica no YouTube, com aprovação humana antes de
cada publicação.

Entrada: um link do YouTube.
Saída: N cortes de 30-90s, legendados, publicados no canal configurado.

**Sucesso:** rodar agendada, produzir cortes aproveitáveis sem edição manual, e
nunca publicar nada sem o operador aprovar.

## 2. Restrição fundamental — autorização da fonte

Todo material processado pertence a terceiros. O sistema **só processa fontes
com autorização registrada**. Isto não é uma recomendação no README: é uma
trava no código.

Cada fonte (canal de podcast) tem um registro obrigatório:

```yaml
# fontes/nome_do_podcast.yaml
canal_origem: "https://youtube.com/@exemplo"
autorizacao:
  tipo: publica            # publica | email | contrato
  evidencia: "https://youtube.com/@exemplo/about"
  captura: provas/exemplo-2026-08-25.png
  verificado_em: 2026-08-25
  observacao: "Descrição do canal autoriza cortes com crédito e link."
credito_obrigatorio: true
```

O pipeline recusa (`ERRO_SEM_AUTORIZACAO`) qualquer job cuja fonte não tenha
registro válido. Se `credito_obrigatorio`, a descrição do vídeo recebe crédito e
link do episódio original automaticamente — sem isso o upload não acontece.

**Fora de escopo:** avaliar se uma autorização é juridicamente suficiente. O
sistema registra e aplica o que o operador declarou.

## 3. Arquitetura

Processo Python único. Estado em SQLite. O núcleo é uma **CLI pura** — não sabe
quem a chamou.

```
                  ┌──────────────┐
   scheduler ────►│              │
   CLI       ────►│  pipeline.py │◄──── bot telegram (aprovação)
   (futuro CI)───►│              │
                  └──────┬───────┘
                         │  lê/grava estado
                  ┌──────▼───────┐
                  │  SQLite      │
                  └──────────────┘
```

Essa separação é deliberada: migrar para GitHub Actions depois é escrever um
`.yml` que chama a mesma CLI, sem tocar no código.

### Máquina de estados

São **dois níveis**: o episódio e cada corte extraído dele.

**Job (episódio):**

```
NOVO
 └─► BAIXADO        yt-dlp trouxe vídeo + áudio
      └─► TRANSCRITO     Whisper, com tempo por palavra
           └─► SEGMENTADO    LLM escolheu os trechos
                └─► RENDERIZADO   todos os cortes gerados
                     └─► CONCLUIDO    nenhum corte pendente de decisão
```

**Corte (filho do job), a partir de `RENDERIZADO`:**

```
AGUARDANDO_APROVACAO
 ├─► APROVADO ──► PUBLICADO      (upload imediato, se houver quota)
 │        └────► ERRO_UPLOAD     (retentável)
 ├─► REJEITADO
 └─► REFAZER ──► volta ao job em SEGMENTADO, só para este corte
```

O job chega a `CONCLUIDO` quando nenhum corte está em
`AGUARDANDO_APROVACAO` nem em `APROVADO`.

Cada transição é uma função `(entidade, workdir) -> novo_estado`, idempotente e
retomável. Queda de energia no meio do render: o job retoma de `SEGMENTADO`, e
os cortes já renderizados não são refeitos.

## 4. Componentes

```
main.py                 CLI: ingest, run, schedule, bot, fontes, canais
vidbot/
  db.py                 SQLite: jobs, cortes, fontes, canais, uploads
  config.py             .env + validação de credenciais
  fontes.py             Carrega e valida registros de autorização
  perfis.py             YAML por canal de destino
  pipeline.py           Máquina de estados. Conhece a ordem, não o "como"
  llm.py           ✅   Gemini / Groq / Ollama com fallback (escrito)
  plan.py          ✅   Validação defensiva de saída do LLM (adaptar schema)
  download.py           yt-dlp: vídeo, áudio, metadados do episódio
  transcribe.py         Whisper (Groq API ou faster-whisper local)
  segment.py            Transcrição → trechos candidatos (LLM + heurísticas)
  reframe.py            16:9 → 9:16 (centro, rosto ou split)
  subtitles.py          Trecho + estilo → arquivo .ass
  render.py             ffmpeg: corte, reenquadre, legenda queimada
  youtube.py            Upload multi-canal, um token OAuth por canal
  scheduler.py          Cadências → jobs
  bot.py                Telegram: aprovação com botões inline
fontes/                 Registros de autorização (§2)
perfis/                 Canais de destino
tokens/                 OAuth por canal (gitignored)
```

`plan.py` e `llm.py` já existem e são reaproveitados; o schema validado em
`plan.py` muda de "plano de vídeo" para "estilo de legenda + metadados".

## 5. Seleção de trechos (`segment.py`)

O passo que define a qualidade do produto.

**Entrada:** transcrição com timestamps por palavra, mais metadados do episódio.

**Processo:** a transcrição é dividida em janelas sobrepostas que cabem no
contexto do modelo. Para cada janela, o LLM recebe instrução de identificar
momentos autocontidos — uma ideia que se entende sem o resto do episódio, com
começo e fim naturais. Devolve, para cada candidato:

```json
{
  "inicio": 1834.5, "fim": 1902.0,
  "gancho": "primeira frase, que precisa prender em 3s",
  "titulo": "...", "nota": 0-100, "motivo": "..."
}
```

**Pós-processamento determinístico** (não confiar em nota de LLM sozinha):

- Ajustar bordas para o silêncio mais próximo, evitando cortar no meio da palavra
- Descartar duração fora de 20-90s
- Descartar sobreposição > 30% com candidato de nota maior
- Ordenar por nota e cortar no `max_cortes` do perfil

**Regra de conteúdo:** o corte preserva o trecho como foi dito, sem recontextualizar
de forma enganosa. Título e descrição refletem o que o trecho de fato diz.

## 6. Reenquadramento (`reframe.py`)

Três estratégias, escolhidas no perfil:

| Estratégia | Como | Quando |
|---|---|---|
| `centro` | crop central | Padrão. Rápido, sem dependência |
| `rosto` | OpenCV detecta e segue o rosto dominante | Uma pessoa em cena |
| `split` | dois rostos empilhados | Entrevista com dois |

`rosto` e `split` usam OpenCV (CPU, sem GPU). Amostram um quadro a cada N
segundos e suavizam o movimento para evitar tremor. Falha na detecção cai
silenciosamente para `centro` — degradar é melhor que falhar.

## 7. Legendas (`subtitles.py`)

Gera arquivo `.ass`, queimado pelo ffmpeg. Estilo vem do perfil do canal e é
validado com clamp e whitelist antes de virar arquivo (o LLM nunca escreve ASS
diretamente).

Modo padrão: karaokê, 1-3 palavras por vez, palavra ativa destacada — sincronizado
pelos timestamps por palavra do Whisper.

Parâmetros: fonte, tamanho, cor primária, cor de destaque, contorno, posição,
caixa de fundo, maiúsculas, palavras por cue.

## 8. Publicação (`youtube.py`)

Um arquivo de token OAuth por canal de destino. O perfil aponta qual usar.

**Quota:** 10.000 unidades/dia por projeto, 1.600 por upload → ~6 uploads/dia.
O sistema mantém um contador diário no banco. Ao esgotar, os cortes permanecem
em `APROVADO` e o scheduler os drena no dia seguinte, na ordem em que foram
aprovados — aprovação nunca se perde por falta de quota.

Descrição montada automaticamente: texto do perfil + crédito e link do episódio
original quando `credito_obrigatorio`.

Privacidade padrão: `unlisted`. Publicar como `public` é opção explícita do perfil.

## 9. Aprovação (`bot.py`)

Terminado o render, o bot envia cada corte ao operador:

```
✂️ job #58 · corte 3/12 — @exemplo
"O erro que quase me custou a empresa"  0:47
[▶ vídeo]

[✅ Publicar] [🔄 Refazer] [❌ Descartar]
```

Nada sobe sem toque humano. O bot só aceita comandos dos IDs em
`TELEGRAM_ALLOWED_USER_IDS`. Cortes acima de 50MB vão como link para arquivo
local em vez de upload ao Telegram.

## 10. Tratamento de erro

| Falha | Resposta |
|---|---|
| Fonte sem autorização | `ERRO_SEM_AUTORIZACAO`, para antes de baixar |
| yt-dlp falha / vídeo privado | 3 tentativas com backoff, depois avisa no Telegram |
| Whisper falha | Fallback nuvem ↔ local |
| LLM devolve JSON inválido | Reparo por extração; 2ª falha usa heurística sem LLM |
| Nenhum trecho aprovado no filtro | Job termina em `SEM_CORTES`, avisa |
| ffmpeg falha num corte | Corte marcado `ERRO`; os demais seguem |
| Quota do YouTube esgotada | Reagenda para o dia seguinte, mantém aprovação |
| Token OAuth expirado | Refresh automático; se falhar, pede reautorização no Telegram |
| Job travado > 6h | Alerta no Telegram |

Princípio: **falha de um corte nunca derruba o episódio**. Erros são registrados
no banco com mensagem, não apenas logados.

## 11. Testes

- **Máquina de estados** — transições e retomada, com plugins falsos. Sem rede, sem ffmpeg.
- **Seleção de trechos** — transcrições fixas em fixtures; testa o pós-processamento
  determinístico (bordas, sobreposição, duração), não a criatividade do LLM.
- **Validação** — saídas malformadas de LLM não produzem ASS nem comando ffmpeg inválido.
- **Autorização** — fonte sem registro é recusada; crédito obrigatório ausente bloqueia upload.
- **Render** — teste de fumaça com 2s de vídeo sintético gerado pelo próprio ffmpeg.
- **Rede** — respostas gravadas em fixtures. A suíte roda offline.

## 12. Custos

| Item | Custo |
|---|---|
| yt-dlp, ffmpeg, OpenCV, SQLite | $0 |
| Whisper | Groq free tier, ou local |
| LLM (seleção, títulos) | Gemini + Groq free tier |
| YouTube API | $0 |
| **Total corrente** | **$0** |

Sem GPU. Sem modelo local obrigatório. Roda em qualquer máquina com CPU.

## 13. Fora de escopo (YAGNI)

Não entram nesta versão: interface web, geração de thumbnail, publicação em
TikTok/Instagram, análise de desempenho dos vídeos, tradução, dublagem, camada
multi-cliente com cobrança, e reenquadramento com tracking por ML pesado.

O plugin de fonte permite adicionar livros ou outras origens depois; nada aqui
impede isso.
