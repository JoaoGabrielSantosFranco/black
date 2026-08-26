# Fábrica de cortes

Você cadastra os canais do YouTube que quer observar. O sistema descobre os
vídeos novos, lê a transcrição, usa uma IA para achar os melhores trechos,
gera os Shorts em 9:16 com legenda queimada e deixa cada corte esperando sua
aprovação no Telegram — ou publica sozinho, se o canal estiver configurado
para isso.

```
canal monitorado → vídeo novo → transcrição → IA escolhe trechos
      → render 9:16 + legenda → aprovação no Telegram → YouTube
```

## Instalação

```bash
sudo apt install -y ffmpeg
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
```

A qualquer momento, `doctor` diz exatamente o que ainda falta:

```bash
.venv/bin/python main.py doctor
```

## Configuração

### 1. Chave do LLM

No `.env`, preencha `GROQ_API_KEY` (ou `GEMINI_API_KEY` com
`LLM_PROVIDER=gemini`). É a IA que escolhe os trechos e escreve título e
descrição.

### 2. Telegram (opcional, mas é como você aprova os cortes)

Crie um bot com o [@BotFather](https://t.me/BotFather) e preencha no `.env`:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_USER_IDS=123456789
```

`TELEGRAM_ALLOWED_USER_IDS` é a lista de quem pode operar o bot — sem ela
ninguém entra. Descubra seu id conversando com o [@userinfobot](https://t.me/userinfobot).

### 3. Perfil do canal de destino

Um YAML por canal em `perfis/`. Veja `perfis/cortes_br.yaml`: ele define
duração dos cortes, reenquadre, estilo da legenda, privacidade, os
`criterios` que a IA deve seguir naquele canal e se ele publica sozinho
(`auto_publicar`).

### 4. Token do YouTube

No [Google Cloud Console](https://console.cloud.google.com): ative a
**YouTube Data API v3** e crie uma credencial OAuth do tipo **App para
computador**. Baixe o JSON como `client_secrets.json` na raiz do projeto.

```bash
.venv/bin/python main.py autorizar cortes_br
```

Abre o navegador para você entrar na conta do canal e salva o token em
`tokens/`. Rode uma vez por canal.

> Servidor sem tela? O fluxo antigo de colar código no terminal foi desligado
> pelo Google em 2022. Rode o comando na sua máquina e copie o arquivo gerado
> para `tokens/`, ou use encaminhamento de porta por SSH.

## Uso

```bash
# passa a observar um canal
python main.py canais add @leon -p cortes_br
python main.py canais                  # lista, com status e última varredura

# a fábrica inteira: descobre, processa e publica
python main.py ciclo

# sobe o bot para aprovar os cortes
python main.py bot
```

No cron, a cada 30 minutos:

```
*/30 * * * * cd /caminho/para/black && .venv/bin/python main.py ciclo >> ciclo.log 2>&1
```

### Comandos

| comando | o que faz |
|---|---|
| `doctor` | confere dependências, credenciais e tokens |
| `canais add/rm/on/off` | gerencia os canais monitorados |
| `descobrir` | procura vídeos novos (sem processar) |
| `run` | avança um job até onde der |
| `ciclo` | descobrir + processar + publicar |
| `publicar` | drena a fila de aprovados que ficaram sem cota |
| `bot` | sobe o bot do Telegram |
| `autorizar <perfil>` | gera o token OAuth do canal |
| `jobs` | lista os jobs recentes |
| `limpar` | apaga workdirs de jobs encerrados |

### No Telegram

`/cortes` traz cada corte pendente como vídeo, com título, descrição, janela
de tempo, nota e origem, mais os botões **Publicar**, **Refazer** e
**Descartar**. `/status` mostra o panorama da fábrica, `/canais` o que está
sendo monitorado e `/fila` os aprovados aguardando upload.

## Como funciona por dentro

Cada vídeo vira um **job** que caminha por uma máquina de estados
(`vidbot/estados.py`), com o progresso em SQLite. O processo é **retomável**:
se cair no meio do render, a próxima execução continua de onde parou, sem
refazer download nem transcrição.

Cada corte tem seu próprio ciclo de vida — um render que falha vira
`ERRO_RENDER` sem derrubar os outros cortes do mesmo vídeo.

O YouTube permite 6 uploads por dia na cota padrão. Quando ela acaba, os
cortes aprovados **esperam** em `APROVADO` e sobem no próximo `ciclo`, em vez
de se perderem.

Nenhuma etapa do pipeline publica: só uma decisão humana no Telegram ou o
`auto_publicar` explícito do perfil levam um corte a `PUBLICADO`.

```
vidbot/
  canais.py     cadastro dos canais e descoberta de vídeos novos
  captions.py   legendas do YouTube (json3/vtt) → transcrição
  segment.py    IA escolhe os trechos + filtro determinístico
  subtitles.py  legenda .ass a partir do estilo do perfil
  reframe.py    16:9 → 9:16 (centro ou rosto)
  render.py     ffmpeg: recorta, reenquadra e queima a legenda
  youtube.py    upload, cota diária e OAuth
  bot.py        Telegram: aprovação e publicação
  pipeline.py   máquina de estados retomável
  etapas.py     liga tudo
```

## Testes

```bash
.venv/bin/python -m pytest
```

Todas as bordas externas (yt-dlp, LLM, ffmpeg, YouTube, Telegram) são
injetáveis, então a suíte roda sem rede. Dois testes de fumaça usam o ffmpeg
de verdade, com um vídeo sintético.
