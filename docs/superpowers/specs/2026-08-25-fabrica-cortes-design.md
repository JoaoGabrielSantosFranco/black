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
   CLI       ────►│  pipeline.py │◄──► bot telegram
   bot       ────►│              │     (dispara, acompanha, aprova)
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
 ├─► SEM_LEGENDA       vídeo sem faixa de legenda: encerra, nenhum corte
 └─► LEGENDA_OBTIDA    faixas do YouTube, sem baixar mídia
      └─► SEGMENTADO       LLM escolheu os trechos
           └─► RENDERIZADO     todos os cortes gerados
                └─► CONCLUIDO      nenhum corte pendente de decisão
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
                        (a CLI segue completa; o bot é outro cliente dela)
vidbot/
  db.py                 SQLite: jobs, cortes, fontes, canais, uploads
  config.py             .env + validação de credenciais
  fontes.py             Carrega e valida registros de autorização
  perfis.py             YAML por canal de destino
  pipeline.py           Máquina de estados. Conhece a ordem, não o "como"
  llm.py                Gemini / Groq / Ollama com fallback
  validate.py           Validação defensiva de toda saída de LLM
  download.py           yt-dlp: vídeo, áudio, metadados do episódio
  captions.py           Faixas de legenda do YouTube: texto + sincronia
  segment.py            Transcrição → trechos candidatos (LLM + heurísticas)
  reframe.py            16:9 → 9:16 (centro, rosto ou split)
  subtitles.py          Trecho + estilo → arquivo .ass
  render.py             ffmpeg: corte, reenquadre, legenda queimada
  youtube.py            Upload multi-canal, um token OAuth por canal
  scheduler.py          Cadências → jobs
  bot.py                Telegram: entrada por link, status e aprovação
fontes/                 Registros de autorização (§2)
perfis/                 Canais de destino
tokens/                 OAuth por canal (gitignored)
```

Nada disso existe ainda: o repositório contém apenas este documento.

## 4.1 Aquisição em duas fases (`download.py`)

**Não há transcrição própria.** O YouTube já publica as faixas de legenda de
cada vídeo, e elas bastam. Vídeo sem legenda não vira corte.

### Fase 0 — a legenda que já existe

```python
info = ydl.extract_info(url, download=False)   # nenhuma midia baixada
info["subtitles"]           # enviadas pelo autor
info["automatic_captions"]  # ASR do YouTube, formato json3
```

Custo: **um arquivo de texto, segundos**. Nada de áudio, nada de API, nada de
modelo.

**Duas faixas, dois papéis.** Elas costumam coexistir, e cada uma é melhor numa
coisa:

| Faixa | Texto | Tempo | Papel |
|---|---|---|---|
| ASR do YouTube (`json3`) | Sem pontuação | **Por palavra** | Sincronia da legenda |
| Legenda do autor | Boa, pontuada | Por linha | Texto exibido e seleção |

Quando as duas existem, o texto vem da do autor e a sincronia do ASR. Quando só
há ASR, um passo de repontuação por LLM roda antes da seleção — o `segment.py`
identifica limites de ideia muito melhor enxergando onde as frases terminam.
Quando só há a do autor, o karaokê degrada para destaque **por linha** em vez de
por palavra; continua legível, apenas menos vistoso.

**Sem nenhuma faixa**, o job termina em `SEM_LEGENDA` e o bot avisa. Nenhum
corte é produzido: transcrever por conta própria custaria mais tempo do que o
episódio vale, e há sempre outro episódio.

### Fase 1 — apenas os trechos aprovados

```
--download-sections "*1834-1902"  (um por corte)
--force-keyframes-at-cuts
```

Requisições HTTP com `Range` trazem só os segundos necessários: 12 cortes de 60s
≈ 200MB, contra 1-3GB do episódio completo. O episódio inteiro nunca existe na
máquina.

`--force-keyframes-at-cuts` reencoda as bordas para o corte cair no ponto que a
legenda indicou; sem isso o vídeo começa no keyframe anterior, até 5s antes.

### Decisões

- yt-dlp entra como **biblioteca Python**, não subprocess — os `progress_hooks`
  alimentam o progresso no Telegram (§9) sem parsing de texto
- Formato preferido **H.264 ≤1080p + m4a**. VP9/AV1 economizam banda mas custam
  muito mais CPU no encode, e CPU é o gargalo da máquina alvo
- Formato sem suporte a range → **fallback para download completo**
- Os **capítulos** vindos do metadata alimentam `segment.py`: capítulo marcado
  pelo autor costuma ser um bloco temático autocontido
- O `--download-sections` depende de ffmpeg, já exigido pelo projeto

**Risco concentrado:** sem transcrição própria, a Fase 0 é ponto único de falha —
se o acesso às legendas quebrar, a fábrica para. É uma troca deliberada de
robustez por simplicidade e velocidade. `vidbot doctor` confere a versão do
yt-dlp e avisa quando estiver defasada, que é a mitigação disponível.

A aquisição só ocorre para fontes com autorização registrada (§2).

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

## 9. Interface Telegram (`bot.py`)

O Telegram é a interface completa da fábrica: **dispara, acompanha e aprova**.
O operador não precisa de terminal.

### Entrada

O operador manda um link do YouTube ao bot. O bot:

1. Extrai o ID do vídeo e consulta os metadados (canal de origem, duração, título)
2. **Verifica a autorização** da fonte (§2). Sem registro, recusa e oferece
   registrar ali mesmo, guiando pelos campos obrigatórios
3. Pergunta o canal de destino, se houver mais de um perfil
4. Cria o job em `NOVO` e devolve o número

```
Operador: https://youtube.com/watch?v=XXXX

Bot: 🎙 "Episódio 148 — título" · @exemplo · 1h52
     ✅ Fonte autorizada (pública, verificada em 2026-08-25)
     Publicar em qual canal?
     [cortes_br]  [cortes_en]

Operador: [cortes_br]

Bot: ▶️ job #58 na fila. Aviso quando terminar.
```

Envio de **arquivo de vídeo** também é aceito, limitado a 20MB pela Bot API —
suficiente para testes, não para episódios. O link é o caminho normal.

### Acompanhamento

Numa máquina modesta um episódio leva de 20 a 60 minutos. O silêncio nesse
intervalo é inaceitável — o operador precisa saber que está vivo e quanto falta.

**Uma única mensagem** é criada ao aceitar o job e **editada** ao longo de todo
o processamento, em vez de encher a conversa:

```
🎬 job #58 · @exemplo · decorrido 12min

✅ baixado         1.8 GB · 4min
✅ transcrito      1h52 de áudio · 3min
✅ trechos         12 escolhidos de 47 candidatos
⏳ renderizando    4/12 ······· ~18min restantes
```

Origem de cada número:

- **Download** — `progress_hooks` do yt-dlp dão bytes e percentual
- **Render** — `ffmpeg -progress pipe:1` dá `out_time`, comparado à duração alvo
- **Restante** — extrapolado do tempo médio dos cortes já concluídos; só aparece
  depois do primeiro, quando a estimativa passa a ter base

**Limitação de taxa:** a Bot API pune edições frequentes. As atualizações são
represadas a no mínimo 5s de intervalo e só são enviadas quando o texto muda de
fato. Um `429` nunca derruba o job — o feedback é acessório, o processamento não
depende dele.

**Ao falhar**, a mesma mensagem vira o relato do erro, com a etapa que quebrou e
o que fazer:

```
🎬 job #58 · @exemplo
✅ baixado   ✅ transcrito   ❌ renderizando

Corte 5/12 falhou: ffmpeg encerrou com código 1
Os outros 11 seguiram normalmente.
[🔄 Refazer o corte 5]  [📄 Ver log]
```

### Aprovação

Terminado o render, cada corte chega individualmente:

```
✂️ job #58 · corte 3/12 — @exemplo
"O erro que quase me custou a empresa"  0:47
[▶ vídeo]

[✅ Publicar] [🔄 Refazer] [❌ Descartar]
```

Nada sobe sem toque humano. Publicado, o bot responde com o link do YouTube.

### Regras

- Só responde aos IDs em `TELEGRAM_ALLOWED_USER_IDS`
- Cortes acima de 50MB (limite de envio da Bot API) vão como caminho de arquivo
  local em vez de anexo
- Comandos auxiliares: `/jobs` (em andamento), `/fontes` (autorizações),
  `/cancelar <id>`
- O bot **enfileira**; não processa dentro do handler. Handler que renderiza
  vídeo trava o bot inteiro
- **Fora de escopo:** servidor Bot API local para arquivos até 2GB

## 10. Tratamento de erro

| Falha | Resposta |
|---|---|
| Fonte sem autorização | `ERRO_SEM_AUTORIZACAO`, para antes de baixar |
| Link inválido ou não suportado | Bot recusa na entrada, sem criar job |
| Arquivo enviado > 20MB | Bot explica o limite e pede o link |
| yt-dlp falha / vídeo privado | 3 tentativas com backoff, depois avisa no Telegram |
| Vídeo sem faixa de legenda | Job encerra em `SEM_LEGENDA`, bot avisa |
| Só há legenda do autor | Karaokê degrada para destaque por linha |
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
| Legendas | Faixas do próprio YouTube — sem transcrição |
| LLM (seleção, títulos) | Gemini + Groq free tier |
| YouTube API | $0 |
| **Total corrente** | **$0** |

Sem GPU. Sem modelo local obrigatório. Roda em qualquer máquina com CPU.

## 13. Requisitos de máquina

Alvo declarado: **notebook com 4GB de RAM**. O desenho cabe nisso porque as
etapas pesadas de memória rodam na nuvem.

| Recurso | Mínimo | Observação |
|---|---|---|
| RAM | 2GB livres | Pico ~800MB (yt-dlp + ffmpeg + bot) |
| Disco | 3GB livres por job | Download em duas fases (§4.1) evita baixar o episódio inteiro |
| CPU | qualquer | Define o tempo, não a viabilidade |
| GPU | não usada | — |

**Nenhum modelo roda localmente.** Sem Whisper e sem GPU: a legenda vem pronta
do YouTube e o LLM é API. O único processo pesado é o ffmpeg, que é CPU.

O workdir de cada job é apagado ao chegar em `CONCLUIDO` ou `REJEITADO`. Um
`vidbot limpar` remove órfãos de jobs interrompidos.

**`vidbot doctor`** — comando de diagnóstico que confere antes de aceitar
trabalho: ffmpeg presente, disco livre suficiente, chaves de API válidas, token
OAuth de cada canal, quota restante do dia. O bot roda isso na inicialização e
avisa no Telegram se algo estiver faltando.

## 14. Fora de escopo (YAGNI)

Não entram nesta versão: interface web, geração de thumbnail, publicação em
TikTok/Instagram, análise de desempenho dos vídeos, tradução, dublagem, camada
multi-cliente com cobrança, e reenquadramento com tracking por ML pesado.

O plugin de fonte permite adicionar livros ou outras origens depois; nada aqui
impede isso.
