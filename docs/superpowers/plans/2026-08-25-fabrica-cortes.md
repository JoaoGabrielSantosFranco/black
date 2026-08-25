# Fábrica de Cortes — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Esteira que recebe um link de podcast no YouTube, escolhe os melhores trechos usando as legendas que o YouTube já publica, renderiza cortes verticais legendados e os publica após aprovação humana no Telegram.

**Architecture:** Processo Python único com estado durável em SQLite. O núcleo é uma CLI pura (`main.py`) que não sabe quem a chamou; scheduler, bot e um futuro CI são apenas clientes dela. O `pipeline.py` conhece a ordem das etapas mas não o "como" — cada etapa é uma função `(job, workdir) -> None` injetada, o que torna a máquina de estados testável sem rede e sem ffmpeg.

**Tech Stack:** Python 3.12, SQLite (stdlib), yt-dlp (biblioteca), ffmpeg (subprocess), OpenCV (reenquadre opcional), python-telegram-bot, google-api-python-client, Groq/Gemini via HTTP.

**Spec:** `docs/superpowers/specs/2026-08-25-fabrica-cortes-design.md`

## Global Constraints

- **Python 3.12**, venv em `.venv/`. Todo comando roda com `.venv/bin/python`.
- **Custo corrente zero.** Nenhum serviço pago. LLM só em free tier (Groq, Gemini).
- **Nenhum modelo roda localmente.** Sem Whisper, sem GPU. Legenda vem do YouTube.
- **Máquina alvo: 4GB de RAM.** Pico aceitável ~800MB. Nunca carregar o episódio inteiro em memória.
- **A suíte de testes roda offline.** Toda resposta de rede vem de fixture. Nenhum teste chama YouTube, Groq, Gemini ou Telegram.
- **ffmpeg é dependência externa.** Ainda NÃO está instalado nesta máquina; exige `sudo apt install -y ffmpeg`. Tarefas 1–8 não dependem dele. A Tarefa 9 é a primeira que precisa — o executor deve pedir ao operador antes de começá-la.
- **Nada é publicado sem aprovação humana explícita.** Nenhum caminho de código chama upload sem passar por `APROVADO`.
- **Toda saída de LLM é validada** com clamp e whitelist antes de virar arquivo ou argumento de comando. O LLM nunca escreve ASS nem linha de ffmpeg diretamente.
- **Mensagens ao usuário em português.** Nomes de código, estados e commits em português sem acento (ex: `LEGENDA_OBTIDA`, `transicionar_job`).
- **Commits em português**, prefixados `feat:`, `test:`, `fix:` ou `chore:`.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | CLI: `ingest`, `run`, `jobs`, `doctor`, `limpar`, `bot`, `schedule` |
| `vidbot/estados.py` | Constantes de estado e o mapa de transições permitidas |
| `vidbot/db.py` | Schema SQLite, CRUD de job/corte, transições atômicas, quota |
| `vidbot/config.py` | Leitura do `.env` e validação de credenciais |
| `vidbot/perfis.py` | Carrega e valida os YAML de canal de destino |
| `vidbot/pipeline.py` | Máquina de estados: ordem das etapas, retomada, isolamento de erro |
| `vidbot/llm.py` | Groq / Gemini / Ollama com fallback entre provedores |
| `vidbot/validate.py` | Coerção defensiva de qualquer dicionário vindo de LLM |
| `vidbot/captions.py` | Busca e normaliza as faixas de legenda do YouTube |
| `vidbot/segment.py` | Transcrição → trechos candidatos → filtro determinístico |
| `vidbot/download.py` | yt-dlp: metadados e download por seções |
| `vidbot/reframe.py` | 16:9 → 9:16 (centro, rosto, split) |
| `vidbot/subtitles.py` | Trechos + estilo do perfil → arquivo `.ass` |
| `vidbot/render.py` | ffmpeg: corte, reenquadre, legenda queimada |
| `vidbot/youtube.py` | Upload multi-canal e contador de quota |
| `vidbot/bot.py` | Telegram: entrada, progresso, aprovação |
| `vidbot/scheduler.py` | Cadências dos perfis → jobs |

Regra de tamanho: nenhum módulo passa de ~250 linhas. Se passar, tem responsabilidade demais.

---

### Task 1: Esqueleto, configuração e `doctor`

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.env.example`, `pytest.ini`
- Create: `vidbot/__init__.py`, `vidbot/config.py`, `main.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nada (primeira tarefa)
- Produces:
  - `config.carregar() -> Config` — dataclass com `llm_provider: str`, `groq_api_key: str|None`, `gemini_api_key: str|None`, `telegram_token: str|None`, `telegram_ids: list[int]`, `db_path: Path`, `work_dir: Path`
  - `config.Config.faltando(*campos: str) -> list[str]` — nomes das variáveis exigidas que estão vazias
  - `config.diagnosticar(cfg: Config) -> list[tuple[str, bool, str]]` — linhas `(nome, ok, detalhe)` para o `doctor`

- [ ] **Step 1: Criar venv e dependências**

```bash
cd /home/jfranco/code/black
python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
cat > requirements.txt <<'EOF'
yt-dlp>=2024.8.6
python-telegram-bot>=21.4
google-api-python-client>=2.140
google-auth-oauthlib>=1.2
google-auth-httplib2>=0.2
requests>=2.32
PyYAML>=6.0
opencv-python-headless>=4.10
pytest>=8.3
EOF
.venv/bin/python -m pip install -q -r requirements.txt
```

- [ ] **Step 2: Arquivos de apoio**

```bash
cat > .gitignore <<'EOF'
.venv/
work/
output/
__pycache__/
*.pyc
.pytest_cache/
.env
tokens/
perfis/*.local.yaml
EOF
cat > pytest.ini <<'EOF'
[pytest]
testpaths = tests
addopts = -q
EOF
mkdir -p tests vidbot perfis tokens
touch vidbot/__init__.py tests/__init__.py
```

- [ ] **Step 3: Escrever o teste que falha**

```python
# tests/test_config.py
from pathlib import Path
from vidbot import config


def _env(**extra):
    base = {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "k", "TELEGRAM_ALLOWED_USER_IDS": "7, 9"}
    base.update(extra)
    return base


def test_carrega_ids_do_telegram_como_inteiros():
    cfg = config.carregar(_env())
    assert cfg.telegram_ids == [7, 9]


def test_ids_vazios_viram_lista_vazia():
    cfg = config.carregar(_env(TELEGRAM_ALLOWED_USER_IDS=""))
    assert cfg.telegram_ids == []


def test_id_nao_numerico_e_ignorado():
    cfg = config.carregar(_env(TELEGRAM_ALLOWED_USER_IDS="7, abc, 9"))
    assert cfg.telegram_ids == [7, 9]


def test_faltando_aponta_campo_vazio():
    cfg = config.carregar(_env(GROQ_API_KEY=""))
    assert cfg.faltando("groq_api_key") == ["GROQ_API_KEY"]


def test_faltando_nao_aponta_campo_preenchido():
    cfg = config.carregar(_env())
    assert cfg.faltando("groq_api_key") == []


def test_provider_desconhecido_vira_groq():
    cfg = config.carregar(_env(LLM_PROVIDER="magica"))
    assert cfg.llm_provider == "groq"


def test_diagnostico_reprova_sem_chave():
    cfg = config.carregar(_env(GROQ_API_KEY=""))
    linhas = dict((nome, ok) for nome, ok, _ in config.diagnosticar(cfg))
    assert linhas["chave do LLM"] is False
```

- [ ] **Step 4: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.config'`

- [ ] **Step 5: Implementar `vidbot/config.py`**

```python
"""Leitura do .env e diagnostico de credenciais."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

PROVEDORES = {"groq", "gemini", "ollama"}
RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    llm_provider: str
    groq_api_key: str
    gemini_api_key: str
    telegram_token: str
    telegram_ids: list[int]
    db_path: Path
    work_dir: Path

    _ENV = {
        "groq_api_key": "GROQ_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "telegram_token": "TELEGRAM_BOT_TOKEN",
    }

    def faltando(self, *campos: str) -> list[str]:
        return [self._ENV[c] for c in campos if not getattr(self, c, "")]


def _ler_ids(bruto: str) -> list[int]:
    ids = []
    for parte in bruto.split(","):
        parte = parte.strip()
        if parte.isdigit():
            ids.append(int(parte))
    return ids


def carregar(env: dict | None = None) -> Config:
    e = dict(os.environ if env is None else env)
    provider = e.get("LLM_PROVIDER", "groq").strip().lower()
    if provider not in PROVEDORES:
        provider = "groq"
    return Config(
        llm_provider=provider,
        groq_api_key=e.get("GROQ_API_KEY", "").strip(),
        gemini_api_key=e.get("GEMINI_API_KEY", "").strip(),
        telegram_token=e.get("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_ids=_ler_ids(e.get("TELEGRAM_ALLOWED_USER_IDS", "")),
        db_path=Path(e.get("VIDBOT_DB", RAIZ / "vidbot.sqlite3")),
        work_dir=Path(e.get("VIDBOT_WORK", RAIZ / "work")),
    )


def diagnosticar(cfg: Config) -> list[tuple[str, bool, str]]:
    """Linhas (nome, ok, detalhe) para o comando doctor."""
    chave = cfg.groq_api_key if cfg.llm_provider == "groq" else cfg.gemini_api_key
    ffmpeg = shutil.which("ffmpeg")
    livre_gb = shutil.disk_usage(cfg.work_dir.parent).free / 1024**3
    return [
        ("chave do LLM", bool(chave) or cfg.llm_provider == "ollama", cfg.llm_provider),
        ("ffmpeg", ffmpeg is not None, ffmpeg or "nao encontrado — sudo apt install ffmpeg"),
        ("token do Telegram", bool(cfg.telegram_token), "opcional ate a Tarefa 11"),
        ("operadores autorizados", bool(cfg.telegram_ids), f"{len(cfg.telegram_ids)} id(s)"),
        ("disco livre", livre_gb >= 3, f"{livre_gb:.1f} GB (minimo 3)"),
    ]
```

- [ ] **Step 6: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Esperado: 7 passed

- [ ] **Step 7: `.env.example` e o comando `doctor`**

```bash
cat > .env.example <<'EOF'
# LLM: groq (recomendado) | gemini | ollama
LLM_PROVIDER=groq
GROQ_API_KEY=
GEMINI_API_KEY=

# Telegram (necessario a partir da Tarefa 11)
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
EOF
```

```python
# main.py
"""CLI da fabrica de cortes. Nucleo puro: nao sabe quem o chamou."""
from __future__ import annotations

import argparse
import sys

from vidbot import config


def cmd_doctor(_args) -> int:
    cfg = config.carregar()
    problemas = 0
    for nome, ok, detalhe in config.diagnosticar(cfg):
        print(f"{'OK  ' if ok else 'FALTA'} {nome}: {detalhe}")
        problemas += 0 if ok else 1
    print("\ntudo pronto" if not problemas else f"\n{problemas} pendencia(s)")
    return 0 if not problemas else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vidbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="confere dependencias e credenciais")
    args = parser.parse_args(argv)
    return {"doctor": cmd_doctor}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Verificar o doctor na mão**

Run: `.venv/bin/python main.py doctor`
Esperado: imprime as 5 linhas. `ffmpeg` aparece como FALTA (esperado — só a Tarefa 9 precisa dele).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: esqueleto do projeto, config e comando doctor"
```

---

### Task 2: Estados e banco (`estados.py`, `db.py`)

O coração do sistema. Um corte espera aprovação por dias — mais que a vida de qualquer processo —, então o estado precisa ser durável e cada transição precisa ser atômica.

**Files:**
- Create: `vidbot/estados.py`, `vidbot/db.py`
- Test: `tests/test_estados.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `estados.TRANSICOES_JOB: dict[str, set[str]]`, `estados.TRANSICOES_CORTE: dict[str, set[str]]`
  - `estados.pode(mapa, de: str, para: str) -> bool`
  - `db.conectar(caminho: Path) -> sqlite3.Connection` — já cria o schema e liga WAL
  - `db.criar_job(con, url, video_id, titulo, canal_origem, duracao_s, perfil) -> int`
  - `db.obter_job(con, job_id) -> Job | None` (dataclass: `id, url, video_id, titulo, canal_origem, duracao_s, perfil, estado, erro, criado_em`)
  - `db.proximo_job(con, estados: list[str]) -> Job | None`
  - `db.transicionar_job(con, job_id, de, para, erro=None) -> bool`
  - `db.criar_corte(con, job_id, inicio_s, fim_s, titulo, nota) -> int`
  - `db.obter_corte(con, corte_id) -> Corte | None` (dataclass: `id, job_id, inicio_s, fim_s, titulo, nota, estado, caminho, youtube_id, erro`)
  - `db.cortes_do_job(con, job_id) -> list[Corte]`
  - `db.transicionar_corte(con, corte_id, de, para, erro=None) -> bool`
  - `db.definir_caminho_corte(con, corte_id, caminho: str) -> None`
  - `db.registrar_upload(con, corte_id, youtube_id: str, dia: str) -> None`
  - `db.uploads_no_dia(con, dia: str) -> int`

- [ ] **Step 1: Escrever `tests/test_estados.py` (falha)**

```python
from vidbot import estados as e


def test_job_novo_pode_ir_para_legenda_obtida():
    assert e.pode(e.TRANSICOES_JOB, e.NOVO, e.LEGENDA_OBTIDA)


def test_job_novo_pode_encerrar_sem_legenda():
    assert e.pode(e.TRANSICOES_JOB, e.NOVO, e.SEM_LEGENDA)


def test_job_nao_pula_direto_para_renderizado():
    assert not e.pode(e.TRANSICOES_JOB, e.NOVO, e.RENDERIZADO)


def test_estado_final_nao_transiciona():
    assert not e.pode(e.TRANSICOES_JOB, e.CONCLUIDO, e.SEGMENTADO)


def test_refazer_corte_devolve_o_job_para_segmentado():
    assert e.pode(e.TRANSICOES_JOB, e.RENDERIZADO, e.SEGMENTADO)


def test_corte_aprovado_publica():
    assert e.pode(e.TRANSICOES_CORTE, e.APROVADO, e.PUBLICADO)


def test_corte_com_erro_de_upload_retenta():
    assert e.pode(e.TRANSICOES_CORTE, e.ERRO_UPLOAD, e.APROVADO)


def test_corte_nao_publica_sem_passar_por_aprovado():
    assert not e.pode(e.TRANSICOES_CORTE, e.AGUARDANDO_APROVACAO, e.PUBLICADO)
```

O último teste é o mais importante do arquivo: ele trava, na estrutura, a regra de que nada é publicado sem aprovação humana.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_estados.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.estados'`

- [ ] **Step 3: Implementar `vidbot/estados.py`**

```python
"""Estados e transicoes permitidas. Dois niveis: job e corte."""
from __future__ import annotations

# --- job (um episodio)
NOVO = "NOVO"
SEM_LEGENDA = "SEM_LEGENDA"
LEGENDA_OBTIDA = "LEGENDA_OBTIDA"
SEGMENTADO = "SEGMENTADO"
SEM_CORTES = "SEM_CORTES"
RENDERIZADO = "RENDERIZADO"
CONCLUIDO = "CONCLUIDO"
ERRO = "ERRO"

# --- corte (um trecho; N por job)
AGUARDANDO_APROVACAO = "AGUARDANDO_APROVACAO"
APROVADO = "APROVADO"
PUBLICADO = "PUBLICADO"
ERRO_UPLOAD = "ERRO_UPLOAD"
REJEITADO = "REJEITADO"
REFAZER = "REFAZER"
ERRO_RENDER = "ERRO_RENDER"

TRANSICOES_JOB: dict[str, set[str]] = {
    NOVO: {LEGENDA_OBTIDA, SEM_LEGENDA, ERRO},
    LEGENDA_OBTIDA: {SEGMENTADO, SEM_CORTES, ERRO},
    SEGMENTADO: {RENDERIZADO, ERRO},
    RENDERIZADO: {CONCLUIDO, SEGMENTADO, ERRO},
    ERRO: {NOVO},
    SEM_LEGENDA: set(),
    SEM_CORTES: set(),
    CONCLUIDO: set(),
}

TRANSICOES_CORTE: dict[str, set[str]] = {
    AGUARDANDO_APROVACAO: {APROVADO, REJEITADO, REFAZER},
    APROVADO: {PUBLICADO, ERRO_UPLOAD},
    ERRO_UPLOAD: {APROVADO, REJEITADO},
    REFAZER: {AGUARDANDO_APROVACAO, ERRO_RENDER},
    ERRO_RENDER: {REFAZER, REJEITADO},
    PUBLICADO: set(),
    REJEITADO: set(),
}

JOB_FINAIS = {SEM_LEGENDA, SEM_CORTES, CONCLUIDO}
CORTE_PENDENTES = {AGUARDANDO_APROVACAO, APROVADO, ERRO_UPLOAD, REFAZER}


def pode(mapa: dict[str, set[str]], de: str, para: str) -> bool:
    return para in mapa.get(de, set())
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_estados.py -v`
Esperado: 8 passed

- [ ] **Step 5: Escrever `tests/test_db.py` (falha)**

```python
import pytest

from vidbot import db, estados as e


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _job(con):
    return db.criar_job(con, url="https://y/w?v=A", video_id="A", titulo="Ep 1",
                        canal_origem="@x", duracao_s=6000, perfil="cortes_br")


def test_job_nasce_em_novo(con):
    j = db.obter_job(con, _job(con))
    assert j.estado == e.NOVO and j.video_id == "A"


def test_transicao_valida_muda_o_estado(con):
    jid = _job(con)
    assert db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA) is True
    assert db.obter_job(con, jid).estado == e.LEGENDA_OBTIDA


def test_transicao_proibida_e_recusada(con):
    jid = _job(con)
    with pytest.raises(db.TransicaoInvalida):
        db.transicionar_job(con, jid, e.NOVO, e.RENDERIZADO)


def test_transicao_com_estado_de_origem_errado_nao_aplica(con):
    """Protege contra dois processos transicionando o mesmo job."""
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    assert db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA) is False


def test_proximo_job_respeita_ordem_de_criacao(con):
    primeiro = _job(con)
    _job(con)
    assert db.proximo_job(con, [e.NOVO]).id == primeiro


def test_proximo_job_ignora_estados_nao_pedidos(con):
    _job(con)
    assert db.proximo_job(con, [e.RENDERIZADO]) is None


def test_erro_fica_gravado_no_job(con):
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.ERRO, erro="yt-dlp caiu")
    assert db.obter_job(con, jid).erro == "yt-dlp caiu"


def test_cortes_saem_na_ordem_do_tempo(con):
    jid = _job(con)
    db.criar_corte(con, jid, 300.0, 340.0, "B", 70)
    db.criar_corte(con, jid, 100.0, 160.0, "A", 90)
    assert [c.titulo for c in db.cortes_do_job(con, jid)] == ["A", "B"]


def test_corte_nasce_aguardando_aprovacao(con):
    jid = _job(con)
    cid = db.criar_corte(con, jid, 10.0, 40.0, "T", 80)
    assert db.obter_corte(con, cid).estado == e.AGUARDANDO_APROVACAO


def test_contador_de_upload_e_por_dia(con):
    jid = _job(con)
    cid = db.criar_corte(con, jid, 10.0, 40.0, "T", 80)
    db.registrar_upload(con, cid, "yt123", "2026-08-25")
    assert db.uploads_no_dia(con, "2026-08-25") == 1
    assert db.uploads_no_dia(con, "2026-08-26") == 0
```

- [ ] **Step 6: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.db'`

- [ ] **Step 7: Implementar `vidbot/db.py`**

```python
"""Estado duravel em SQLite. Toda transicao e atomica e validada."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import estados as e

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    video_id      TEXT NOT NULL,
    titulo        TEXT NOT NULL DEFAULT '',
    canal_origem  TEXT NOT NULL DEFAULT '',
    duracao_s     INTEGER NOT NULL DEFAULT 0,
    perfil        TEXT NOT NULL,
    estado        TEXT NOT NULL,
    erro          TEXT,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now')),
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS cortes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    inicio_s   REAL NOT NULL,
    fim_s      REAL NOT NULL,
    titulo     TEXT NOT NULL DEFAULT '',
    nota       INTEGER NOT NULL DEFAULT 0,
    estado     TEXT NOT NULL,
    caminho    TEXT,
    youtube_id TEXT,
    erro       TEXT
);
CREATE TABLE IF NOT EXISTS uploads (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    corte_id INTEGER NOT NULL REFERENCES cortes(id),
    youtube_id TEXT NOT NULL,
    dia      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_jobs_estado ON jobs(estado);
CREATE INDEX IF NOT EXISTS ix_cortes_job ON cortes(job_id);
CREATE INDEX IF NOT EXISTS ix_uploads_dia ON uploads(dia);
"""


class TransicaoInvalida(ValueError):
    """Transicao que o mapa de estados nao permite. Sempre um bug, nunca dado ruim."""


@dataclass
class Job:
    id: int
    url: str
    video_id: str
    titulo: str
    canal_origem: str
    duracao_s: int
    perfil: str
    estado: str
    erro: str | None
    criado_em: str


@dataclass
class Corte:
    id: int
    job_id: int
    inicio_s: float
    fim_s: float
    titulo: str
    nota: int
    estado: str
    caminho: str | None
    youtube_id: str | None
    erro: str | None

    @property
    def duracao_s(self) -> float:
        return self.fim_s - self.inicio_s


def conectar(caminho: Path) -> sqlite3.Connection:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    return con


# ---------------------------------------------------------------- jobs

def criar_job(con, url, video_id, titulo, canal_origem, duracao_s, perfil) -> int:
    cur = con.execute(
        "INSERT INTO jobs (url, video_id, titulo, canal_origem, duracao_s, perfil, estado)"
        " VALUES (?,?,?,?,?,?,?)",
        (url, video_id, titulo, canal_origem, duracao_s, perfil, e.NOVO),
    )
    return cur.lastrowid


def obter_job(con, job_id: int) -> Job | None:
    r = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _job(r) if r else None


def proximo_job(con, estados: list[str]) -> Job | None:
    marc = ",".join("?" * len(estados))
    r = con.execute(
        f"SELECT * FROM jobs WHERE estado IN ({marc}) ORDER BY id LIMIT 1", estados
    ).fetchone()
    return _job(r) if r else None


def transicionar_job(con, job_id: int, de: str, para: str, erro: str | None = None) -> bool:
    """True se aplicou. False se o job ja nao estava em `de` (outro processo mexeu)."""
    if not e.pode(e.TRANSICOES_JOB, de, para):
        raise TransicaoInvalida(f"job: {de} -> {para}")
    cur = con.execute(
        "UPDATE jobs SET estado=?, erro=?, atualizado_em=datetime('now')"
        " WHERE id=? AND estado=?",
        (para, erro, job_id, de),
    )
    return cur.rowcount == 1


# ---------------------------------------------------------------- cortes

def criar_corte(con, job_id, inicio_s, fim_s, titulo, nota) -> int:
    cur = con.execute(
        "INSERT INTO cortes (job_id, inicio_s, fim_s, titulo, nota, estado)"
        " VALUES (?,?,?,?,?,?)",
        (job_id, float(inicio_s), float(fim_s), titulo, int(nota), e.AGUARDANDO_APROVACAO),
    )
    return cur.lastrowid


def obter_corte(con, corte_id: int) -> Corte | None:
    r = con.execute("SELECT * FROM cortes WHERE id=?", (corte_id,)).fetchone()
    return _corte(r) if r else None


def cortes_do_job(con, job_id: int) -> list[Corte]:
    rs = con.execute(
        "SELECT * FROM cortes WHERE job_id=? ORDER BY inicio_s", (job_id,)
    ).fetchall()
    return [_corte(r) for r in rs]


def transicionar_corte(con, corte_id: int, de: str, para: str, erro: str | None = None) -> bool:
    if not e.pode(e.TRANSICOES_CORTE, de, para):
        raise TransicaoInvalida(f"corte: {de} -> {para}")
    cur = con.execute(
        "UPDATE cortes SET estado=?, erro=? WHERE id=? AND estado=?",
        (para, erro, corte_id, de),
    )
    return cur.rowcount == 1


def definir_caminho_corte(con, corte_id: int, caminho: str) -> None:
    con.execute("UPDATE cortes SET caminho=? WHERE id=?", (caminho, corte_id))


# ---------------------------------------------------------------- quota

def registrar_upload(con, corte_id: int, youtube_id: str, dia: str) -> None:
    con.execute(
        "INSERT INTO uploads (corte_id, youtube_id, dia) VALUES (?,?,?)",
        (corte_id, youtube_id, dia),
    )
    con.execute("UPDATE cortes SET youtube_id=? WHERE id=?", (youtube_id, corte_id))


def uploads_no_dia(con, dia: str) -> int:
    return con.execute("SELECT COUNT(*) c FROM uploads WHERE dia=?", (dia,)).fetchone()["c"]


# ---------------------------------------------------------------- helpers

def _job(r) -> Job:
    return Job(r["id"], r["url"], r["video_id"], r["titulo"], r["canal_origem"],
               r["duracao_s"], r["perfil"], r["estado"], r["erro"], r["criado_em"])


def _corte(r) -> Corte:
    return Corte(r["id"], r["job_id"], r["inicio_s"], r["fim_s"], r["titulo"],
                 r["nota"], r["estado"], r["caminho"], r["youtube_id"], r["erro"])
```

- [ ] **Step 8: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 25 passed

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: estados e banco SQLite com transicoes atomicas"
```

---

### Task 3: Máquina de estados (`pipeline.py`)

O `pipeline` conhece a **ordem** das etapas, nunca o "como". As etapas são injetadas, então esta tarefa se testa inteira com funções falsas — sem rede, sem ffmpeg.

**Files:**
- Create: `vidbot/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `db.*`, `estados.*` (Tarefa 2)
- Produces:
  - `pipeline.Etapa = Callable[[db.Job, Path], None]`
  - `pipeline.Passo` — dataclass `(etapa: Etapa, proximo: str)`
  - `pipeline.PulaPara(Exception)` — etapa desvia para um estado final (`.estado`)
  - `pipeline.executar_job(con, job_id: int, passos: dict[str, Passo], raiz: Path) -> str` — roda até um estado sem passo; devolve o estado final
  - `pipeline.workdir_de(raiz: Path, job_id: int) -> Path`

- [ ] **Step 1: Escrever `tests/test_pipeline.py` (falha)**

```python
from pathlib import Path

import pytest

from vidbot import db, estados as e, pipeline


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _job(con):
    return db.criar_job(con, "https://y/w?v=A", "A", "Ep", "@x", 600, "p")


def _passos(registro, pula_em=None):
    def faz(nome):
        def etapa(job, workdir):
            registro.append(nome)
            if pula_em == nome:
                raise pipeline.PulaPara(e.SEM_LEGENDA)
        return etapa
    return {
        e.NOVO: pipeline.Passo(faz("legenda"), e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(faz("segmenta"), e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(faz("render"), e.RENDERIZADO),
    }


def test_roda_as_etapas_na_ordem(con, tmp_path):
    reg = []
    final = pipeline.executar_job(con, _job(con), _passos(reg), tmp_path)
    assert reg == ["legenda", "segmenta", "render"]
    assert final == e.RENDERIZADO


def test_retoma_do_estado_atual_sem_refazer_o_que_ja_passou(con, tmp_path):
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    reg = []
    pipeline.executar_job(con, jid, _passos(reg), tmp_path)
    assert reg == ["segmenta", "render"]


def test_pula_para_encerra_no_estado_pedido(con, tmp_path):
    reg = []
    final = pipeline.executar_job(con, _job(con), _passos(reg, pula_em="legenda"), tmp_path)
    assert final == e.SEM_LEGENDA
    assert reg == ["legenda"]


def test_excecao_leva_o_job_para_erro_com_a_mensagem(con, tmp_path):
    def explode(job, workdir):
        raise RuntimeError("yt-dlp caiu")

    jid = _job(con)
    final = pipeline.executar_job(
        con, jid, {e.NOVO: pipeline.Passo(explode, e.LEGENDA_OBTIDA)}, tmp_path
    )
    assert final == e.ERRO
    assert "yt-dlp caiu" in db.obter_job(con, jid).erro


def test_workdir_existe_quando_a_etapa_roda(con, tmp_path):
    visto = {}

    def etapa(job, workdir):
        visto["existe"] = workdir.is_dir()

    pipeline.executar_job(
        con, _job(con), {e.NOVO: pipeline.Passo(etapa, e.LEGENDA_OBTIDA)}, tmp_path
    )
    assert visto["existe"] is True


def test_estado_sem_passo_encerra_sem_erro(con, tmp_path):
    jid = _job(con)
    db.transicionar_job(con, jid, e.NOVO, e.LEGENDA_OBTIDA)
    assert pipeline.executar_job(con, jid, {}, tmp_path) == e.LEGENDA_OBTIDA
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.pipeline'`

- [ ] **Step 3: Implementar `vidbot/pipeline.py`**

```python
"""Maquina de estados do job. Conhece a ordem, nunca o 'como'."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import db, estados as e

Etapa = Callable[[db.Job, Path], None]


@dataclass
class Passo:
    etapa: Etapa
    proximo: str


class PulaPara(Exception):
    """Etapa desviou para um estado final (ex.: SEM_LEGENDA)."""

    def __init__(self, estado: str):
        super().__init__(estado)
        self.estado = estado


def workdir_de(raiz: Path, job_id: int) -> Path:
    d = Path(raiz) / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def executar_job(con, job_id: int, passos: dict[str, Passo], raiz: Path) -> str:
    """Avanca o job ate um estado sem passo. Devolve o estado final.

    Retomavel: comeca do estado atual, nao do inicio. Se cair no meio do
    render, a proxima execucao recomeca de SEGMENTADO.
    """
    while True:
        job = db.obter_job(con, job_id)
        if job is None:
            raise ValueError(f"job {job_id} nao existe")
        passo = passos.get(job.estado)
        if passo is None:
            return job.estado

        origem = job.estado
        try:
            passo.etapa(job, workdir_de(raiz, job_id))
        except PulaPara as desvio:
            db.transicionar_job(con, job_id, origem, desvio.estado)
            return desvio.estado
        except Exception as erro:  # noqa: BLE001 - a mensagem vai para o banco
            db.transicionar_job(con, job_id, origem, e.ERRO, erro=str(erro)[:500])
            return e.ERRO

        if not db.transicionar_job(con, job_id, origem, passo.proximo):
            # Outro processo mexeu no job. Reavalia do zero em vez de assumir.
            continue
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Esperado: 6 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: maquina de estados retomavel com etapas injetadas"
```

---

### Task 4: CLI (`urls.py`, comandos `ingest`, `jobs`, `run`)

**Files:**
- Create: `vidbot/urls.py`
- Modify: `main.py`
- Test: `tests/test_urls.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `db.*`, `pipeline.*`, `config.*`
- Produces:
  - `urls.extrair_video_id(url: str) -> str | None`
  - `main.cmd_ingest`, `main.cmd_jobs`, `main.cmd_run`
  - `main.PASSOS: dict[str, pipeline.Passo]` — montado por `main.montar_passos()`; as tarefas seguintes preenchem as etapas reais

- [ ] **Step 1: Escrever `tests/test_urls.py` (falha)**

```python
import pytest

from vidbot.urls import extrair_video_id


@pytest.mark.parametrize("url,esperado", [
    ("https://www.youtube.com/watch?v=EDmsbELe9Ic", "EDmsbELe9Ic"),
    ("https://youtu.be/EDmsbELe9Ic", "EDmsbELe9Ic"),
    ("https://youtu.be/EDmsbELe9Ic?t=42", "EDmsbELe9Ic"),
    ("https://www.youtube.com/watch?v=EDmsbELe9Ic&list=PL1", "EDmsbELe9Ic"),
    ("https://www.youtube.com/shorts/EDmsbELe9Ic", "EDmsbELe9Ic"),
    ("https://m.youtube.com/watch?v=EDmsbELe9Ic", "EDmsbELe9Ic"),
    ("https://www.youtube.com/live/EDmsbELe9Ic", "EDmsbELe9Ic"),
])
def test_extrai_id_das_formas_conhecidas(url, esperado):
    assert extrair_video_id(url) == esperado


@pytest.mark.parametrize("url", [
    "https://vimeo.com/12345",
    "https://www.youtube.com/@canal",
    "nao e url",
    "",
])
def test_recusa_o_que_nao_e_video_do_youtube(url):
    assert extrair_video_id(url) is None
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_urls.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.urls'`

- [ ] **Step 3: Implementar `vidbot/urls.py`**

```python
"""Extracao do id de video a partir das formas de URL do YouTube."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

ID = r"[A-Za-z0-9_-]{11}"
CAMINHO = re.compile(rf"^/(?:shorts|live|embed|v)/({ID})")
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def extrair_video_id(url: str) -> str | None:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    if p.netloc in {"youtu.be", "www.youtu.be"}:
        candidato = p.path.lstrip("/")
        return candidato if re.fullmatch(ID, candidato) else None
    if p.netloc not in HOSTS:
        return None
    if p.path == "/watch":
        v = parse_qs(p.query).get("v", [""])[0]
        return v if re.fullmatch(ID, v) else None
    m = CAMINHO.match(p.path)
    return m.group(1) if m else None
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_urls.py -v`
Esperado: 11 passed

- [ ] **Step 5: Escrever `tests/test_cli.py` (falha)**

```python
import main
from vidbot import db, estados as e


def _argv(tmp_path, *args):
    return ["--db", str(tmp_path / "t.sqlite3"), *args]


def test_ingest_cria_job_e_imprime_o_numero(tmp_path, capsys):
    code = main.main(_argv(tmp_path, "ingest", "https://youtu.be/EDmsbELe9Ic", "-p", "cortes_br"))
    assert code == 0
    assert "#1" in capsys.readouterr().out


def test_ingest_recusa_link_que_nao_e_video(tmp_path, capsys):
    code = main.main(_argv(tmp_path, "ingest", "https://vimeo.com/1", "-p", "cortes_br"))
    assert code == 1
    assert "nao reconhecido" in capsys.readouterr().out


def test_ingest_grava_o_video_id_extraido(tmp_path):
    main.main(_argv(tmp_path, "ingest", "https://youtu.be/EDmsbELe9Ic", "-p", "cortes_br"))
    con = db.conectar(tmp_path / "t.sqlite3")
    assert db.obter_job(con, 1).video_id == "EDmsbELe9Ic"
    con.close()


def test_jobs_lista_o_que_existe(tmp_path, capsys):
    main.main(_argv(tmp_path, "ingest", "https://youtu.be/EDmsbELe9Ic", "-p", "cortes_br"))
    main.main(_argv(tmp_path, "jobs"))
    saida = capsys.readouterr().out
    assert "#1" in saida and e.NOVO in saida


def test_jobs_sem_nada_avisa(tmp_path, capsys):
    main.main(_argv(tmp_path, "jobs"))
    assert "nenhum job" in capsys.readouterr().out
```

- [ ] **Step 6: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Esperado: FAIL — o subcomando `ingest` não existe

- [ ] **Step 7: Reescrever `main.py`**

```python
"""CLI da fabrica de cortes. Nucleo puro: nao sabe quem o chamou."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vidbot import config, db, estados as e, pipeline
from vidbot.urls import extrair_video_id


def montar_passos() -> dict[str, pipeline.Passo]:
    """Etapas reais do pipeline. Preenchido pelas tarefas 5 em diante."""
    return {}


def _con(args):
    caminho = Path(args.db) if args.db else config.carregar().db_path
    return db.conectar(caminho)


def cmd_doctor(_args) -> int:
    cfg = config.carregar()
    problemas = 0
    for nome, ok, detalhe in config.diagnosticar(cfg):
        print(f"{'OK  ' if ok else 'FALTA'} {nome}: {detalhe}")
        problemas += 0 if ok else 1
    print("\ntudo pronto" if not problemas else f"\n{problemas} pendencia(s)")
    return 0 if not problemas else 1


def cmd_ingest(args) -> int:
    video_id = extrair_video_id(args.url)
    if video_id is None:
        print(f"link nao reconhecido como video do YouTube: {args.url}")
        return 1
    con = _con(args)
    try:
        job_id = db.criar_job(con, args.url, video_id, "", "", 0, args.perfil)
        print(f"job #{job_id} criado ({video_id}, perfil {args.perfil})")
        return 0
    finally:
        con.close()


def cmd_jobs(args) -> int:
    con = _con(args)
    try:
        linhas = con.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 20").fetchall()
        if not linhas:
            print("nenhum job")
            return 0
        for r in linhas:
            titulo = r["titulo"] or r["video_id"]
            print(f"#{r['id']:>4} {r['estado']:<20} {r['perfil']:<12} {titulo}")
        return 0
    finally:
        con.close()


def cmd_run(args) -> int:
    con = _con(args)
    try:
        cfg = config.carregar()
        passos = montar_passos()
        pendentes = [s for s in passos] or [e.NOVO]
        job = (db.obter_job(con, args.job) if args.job
               else db.proximo_job(con, pendentes))
        if job is None:
            print("nada a fazer")
            return 0
        final = pipeline.executar_job(con, job.id, passos, cfg.work_dir)
        print(f"job #{job.id} terminou em {final}")
        return 0 if final != e.ERRO else 1
    finally:
        con.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vidbot")
    parser.add_argument("--db", help="caminho do SQLite (padrao: .env)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="confere dependencias e credenciais")
    sub.add_parser("jobs", help="lista os jobs recentes")

    p_in = sub.add_parser("ingest", help="cria um job a partir de um link")
    p_in.add_argument("url")
    p_in.add_argument("-p", "--perfil", required=True)

    p_run = sub.add_parser("run", help="avanca um job ate onde der")
    p_run.add_argument("--job", type=int, help="id; sem isso pega o proximo")

    args = parser.parse_args(argv)
    return {
        "doctor": cmd_doctor, "ingest": cmd_ingest,
        "jobs": cmd_jobs, "run": cmd_run,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Rodar a suíte inteira**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 42 passed

- [ ] **Step 9: Conferir na mão**

```bash
.venv/bin/python main.py --db /tmp/vb.sqlite3 ingest https://youtu.be/EDmsbELe9Ic -p cortes_br
.venv/bin/python main.py --db /tmp/vb.sqlite3 jobs
```
Esperado: cria `job #1` e depois lista `#1 NOVO cortes_br EDmsbELe9Ic`

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: CLI com ingest, jobs e run"
```

---

### Task 5: Legendas do YouTube (`captions.py`)

Substitui a transcrição própria. Toda a rede fica isolada numa única função injetável, então os testes rodam offline.

**Files:**
- Create: `vidbot/captions.py`, `tests/fixtures/asr.json3.json`, `tests/fixtures/autor.vtt`
- Test: `tests/test_captions.py`

**Interfaces:**
- Consumes: nada dos módulos anteriores
- Produces:
  - `captions.Palavra` — dataclass `(texto: str, inicio_s: float, fim_s: float)`
  - `captions.Transcricao` — dataclass `(palavras: list[Palavra], origem: str, idioma: str)`; `origem` é `"asr"` ou `"autor"`; propriedade `.texto -> str`; `.por_palavra -> bool` (True só quando `origem == "asr"`)
  - `captions.parse_json3(dados: dict) -> list[Palavra]`
  - `captions.parse_vtt(texto: str) -> list[Palavra]` — uma "palavra" por linha de legenda quando não há tempo por palavra
  - `captions.escolher_faixa(info: dict, idiomas: list[str]) -> tuple[str, str, str] | None` — devolve `(url, origem, idioma)`
  - `captions.obter(info: dict, baixar: Callable[[str], str], idiomas: list[str]) -> Transcricao | None`

- [ ] **Step 1: Criar as fixtures**

```bash
mkdir -p tests/fixtures
cat > tests/fixtures/asr.json3.json <<'EOF'
{"events": [
  {"tStartMs": 1000, "dDurationMs": 1600, "segs": [
    {"utf8": "o", "tOffsetMs": 0},
    {"utf8": " erro", "tOffsetMs": 300},
    {"utf8": " que", "tOffsetMs": 900}
  ]},
  {"tStartMs": 2600, "dDurationMs": 1200, "segs": [
    {"utf8": " quase", "tOffsetMs": 0},
    {"utf8": " me", "tOffsetMs": 500}
  ]},
  {"tStartMs": 4000, "dDurationMs": 500, "segs": [{"utf8": "\n"}]}
]}
EOF
cat > tests/fixtures/autor.vtt <<'EOF'
WEBVTT

00:00:01.000 --> 00:00:03.500
O erro que quase me custou

00:00:03.500 --> 00:00:06.000
a empresa inteira.
EOF
```

- [ ] **Step 2: Escrever `tests/test_captions.py` (falha)**

```python
import json
from pathlib import Path

from vidbot import captions

FIX = Path(__file__).parent / "fixtures"


def test_json3_da_tempo_por_palavra():
    ps = captions.parse_json3(json.loads((FIX / "asr.json3.json").read_text()))
    assert [p.texto for p in ps] == ["o", "erro", "que", "quase", "me"]
    assert ps[0].inicio_s == 1.0
    assert ps[1].inicio_s == 1.3


def test_json3_ignora_segmentos_so_de_quebra_de_linha():
    ps = captions.parse_json3(json.loads((FIX / "asr.json3.json").read_text()))
    assert all(p.texto.strip() for p in ps)


def test_json3_fecha_a_palavra_no_inicio_da_seguinte():
    ps = captions.parse_json3(json.loads((FIX / "asr.json3.json").read_text()))
    assert ps[0].fim_s == ps[1].inicio_s


def test_vtt_vira_uma_entrada_por_linha():
    ps = captions.parse_vtt((FIX / "autor.vtt").read_text())
    assert len(ps) == 2
    assert ps[0].texto == "O erro que quase me custou"
    assert ps[0].inicio_s == 1.0 and ps[0].fim_s == 3.5


def test_prefere_a_faixa_do_autor_no_idioma_pedido():
    info = {
        "subtitles": {"pt": [{"ext": "vtt", "url": "u-autor"}]},
        "automatic_captions": {"pt": [{"ext": "json3", "url": "u-asr"}]},
    }
    assert captions.escolher_faixa(info, ["pt"]) == ("u-autor", "autor", "pt")


def test_cai_para_o_asr_quando_nao_ha_faixa_do_autor():
    info = {"subtitles": {}, "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}
    assert captions.escolher_faixa(info, ["pt"]) == ("u", "asr", "pt")


def test_respeita_a_ordem_de_preferencia_de_idioma():
    info = {"subtitles": {"en": [{"ext": "vtt", "url": "u-en"}],
                          "pt": [{"ext": "vtt", "url": "u-pt"}]},
            "automatic_captions": {}}
    assert captions.escolher_faixa(info, ["pt", "en"])[2] == "pt"


def test_sem_nenhuma_faixa_devolve_none():
    assert captions.escolher_faixa({"subtitles": {}, "automatic_captions": {}}, ["pt"]) is None


def test_obter_monta_a_transcricao_a_partir_do_asr():
    info = {"subtitles": {}, "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}
    conteudo = (FIX / "asr.json3.json").read_text()
    t = captions.obter(info, baixar=lambda _url: conteudo, idiomas=["pt"])
    assert t.origem == "asr" and t.por_palavra is True
    assert t.texto.startswith("o erro que")


def test_obter_marca_legenda_do_autor_como_sem_tempo_por_palavra():
    info = {"subtitles": {"pt": [{"ext": "vtt", "url": "u"}]}, "automatic_captions": {}}
    conteudo = (FIX / "autor.vtt").read_text()
    t = captions.obter(info, baixar=lambda _url: conteudo, idiomas=["pt"])
    assert t.origem == "autor" and t.por_palavra is False
```

- [ ] **Step 3: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_captions.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.captions'`

- [ ] **Step 4: Implementar `vidbot/captions.py`**

```python
"""Faixas de legenda do YouTube. Substitui transcricao propria.

ASR (json3) tem tempo por palavra e serve a sincronia da legenda.
A faixa do autor tem texto pontuado e serve a leitura e a selecao.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

TEMPO = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")


@dataclass
class Palavra:
    texto: str
    inicio_s: float
    fim_s: float


@dataclass
class Transcricao:
    palavras: list[Palavra]
    origem: str   # "asr" | "autor"
    idioma: str

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in self.palavras)

    @property
    def por_palavra(self) -> bool:
        return self.origem == "asr"


def parse_json3(dados: dict) -> list[Palavra]:
    """json3 do ASR: tStartMs por evento, tOffsetMs por palavra."""
    brutas: list[Palavra] = []
    for ev in dados.get("events", []):
        base = ev.get("tStartMs", 0) / 1000.0
        fim_ev = base + ev.get("dDurationMs", 0) / 1000.0
        for seg in ev.get("segs", []):
            texto = seg.get("utf8", "").strip()
            if not texto:
                continue
            brutas.append(Palavra(texto, base + seg.get("tOffsetMs", 0) / 1000.0, fim_ev))
    for atual, seguinte in zip(brutas, brutas[1:]):
        atual.fim_s = seguinte.inicio_s
    return brutas


def _segundos(m: re.Match) -> float:
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000.0


def parse_vtt(texto: str) -> list[Palavra]:
    """VTT/SRT: sem tempo por palavra, entao cada linha vira uma entrada."""
    saida: list[Palavra] = []
    blocos = re.split(r"\n\s*\n", texto.strip())
    for bloco in blocos:
        linhas = [l for l in bloco.splitlines() if l.strip()]
        marca = next((l for l in linhas if "-->" in l), None)
        if marca is None:
            continue
        tempos = list(TEMPO.finditer(marca))
        if len(tempos) < 2:
            continue
        corpo = " ".join(l.strip() for l in linhas[linhas.index(marca) + 1:])
        corpo = re.sub(r"<[^>]+>", "", corpo).strip()
        if corpo:
            saida.append(Palavra(corpo, _segundos(tempos[0]), _segundos(tempos[1])))
    return saida


def _melhor(faixas: list[dict]) -> str | None:
    for ext in ("json3", "vtt", "srv3", "srt"):
        for f in faixas:
            if f.get("ext") == ext and f.get("url"):
                return f["url"]
    return None


def escolher_faixa(info: dict, idiomas: list[str]) -> tuple[str, str, str] | None:
    """(url, origem, idioma). Autor antes de ASR; idioma na ordem pedida."""
    for origem, chave in (("autor", "subtitles"), ("asr", "automatic_captions")):
        disponiveis = info.get(chave) or {}
        for idioma in idiomas:
            for codigo, faixas in disponiveis.items():
                if codigo == idioma or codigo.startswith(f"{idioma}-"):
                    url = _melhor(faixas)
                    if url:
                        return url, origem, codigo
    return None


def obter(info: dict, baixar: Callable[[str], str],
          idiomas: list[str]) -> Transcricao | None:
    escolha = escolher_faixa(info, idiomas)
    if escolha is None:
        return None
    url, origem, idioma = escolha
    conteudo = baixar(url)
    try:
        palavras = parse_json3(json.loads(conteudo))
    except (json.JSONDecodeError, TypeError):
        palavras = parse_vtt(conteudo)
    return Transcricao(palavras, origem, idioma) if palavras else None
```

- [ ] **Step 5: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_captions.py -v`
Esperado: 10 passed

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: leitura das faixas de legenda do YouTube"
```

---

### Task 6: LLM e validação defensiva (`llm.py`, `validate.py`)

Modelos pequenos alucinam e free tiers caem. Nada que vem do LLM chega cru a um arquivo ou a uma linha de comando.

**Files:**
- Create: `vidbot/llm.py`, `vidbot/validate.py`
- Test: `tests/test_validate.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `config.*`
- Produces:
  - `validate.extrair_json(texto: str) -> dict` — aceita prosa em volta e cercas ```` ```json ````; levanta `validate.SaidaInvalida`
  - `validate.numero(v, lo, hi, padrao, *, cast=int)`, `validate.texto(v, padrao="", limite=200)`, `validate.escolha(v, permitidos: set[str], padrao)`, `validate.flag(v, padrao: bool)`, `validate.cor_hex(v, padrao)`
  - `llm.perguntar_json(prompt: str, sistema: str, cfg, provedores: list[str] | None = None) -> dict`
  - `llm.SemProvedor(RuntimeError)`

- [ ] **Step 1: Escrever `tests/test_validate.py` (falha)**

```python
import pytest

from vidbot import validate as v


def test_extrai_json_puro():
    assert v.extrair_json('{"a": 1}') == {"a": 1}


def test_extrai_json_dentro_de_cerca():
    assert v.extrair_json('bla\n```json\n{"a": 1}\n```\nfim') == {"a": 1}


def test_extrai_json_com_prosa_em_volta():
    assert v.extrair_json('Claro! {"a": 1} espero ter ajudado') == {"a": 1}


def test_sem_json_levanta():
    with pytest.raises(v.SaidaInvalida):
        v.extrair_json("nao tem json aqui")


def test_numero_fora_da_faixa_e_grampeado():
    assert v.numero(999, 0, 100, 50) == 100
    assert v.numero(-5, 0, 100, 50) == 0


def test_numero_invalido_usa_o_padrao():
    assert v.numero("abc", 0, 100, 50) == 50
    assert v.numero(None, 0, 100, 50) == 50


def test_escolha_fora_da_whitelist_usa_o_padrao():
    assert v.escolha("magica", {"centro", "rosto"}, "centro") == "centro"
    assert v.escolha("ROSTO", {"centro", "rosto"}, "centro") == "rosto"


def test_cor_aceita_com_e_sem_cerquilha():
    assert v.cor_hex("FFD400", "#FFFFFF") == "#FFD400"
    assert v.cor_hex("#ffd400", "#FFFFFF") == "#FFD400"


def test_cor_invalida_usa_o_padrao():
    assert v.cor_hex("amarelo", "#FFFFFF") == "#FFFFFF"


def test_texto_e_truncado_e_limpo():
    assert v.texto("  oi  ", limite=10) == "oi"
    assert len(v.texto("x" * 500, limite=10)) == 10
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_validate.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.validate'`

- [ ] **Step 3: Implementar `vidbot/validate.py`**

```python
"""Coercao defensiva de tudo que vem de LLM.

Nada daqui confia na saida do modelo: numero e grampeado, escolha passa por
whitelist, cor casa com regex. O pior caso e um padrao feio, nunca um arquivo
invalido ou um argumento perigoso de linha de comando.
"""
from __future__ import annotations

import json
import re

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
CERCA = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class SaidaInvalida(ValueError):
    """O modelo nao devolveu JSON aproveitavel."""


def extrair_json(texto: str) -> dict:
    bruto = (texto or "").strip()
    cerca = CERCA.search(bruto)
    if cerca:
        bruto = cerca.group(1).strip()
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError:
        ini, fim = bruto.find("{"), bruto.rfind("}")
        if ini == -1 or fim <= ini:
            raise SaidaInvalida(f"sem JSON: {bruto[:200]}") from None
        try:
            dados = json.loads(bruto[ini:fim + 1])
        except json.JSONDecodeError as erro:
            raise SaidaInvalida(str(erro)) from None
    if not isinstance(dados, dict):
        raise SaidaInvalida("JSON nao e objeto")
    return dados


def numero(valor, lo, hi, padrao, *, cast=int):
    try:
        return cast(min(hi, max(lo, cast(float(valor)))))
    except (TypeError, ValueError):
        return cast(padrao)


def texto(valor, padrao: str = "", limite: int = 200) -> str:
    if not isinstance(valor, str) or not valor.strip():
        return padrao[:limite]
    return valor.strip()[:limite]


def escolha(valor, permitidos: set[str], padrao: str) -> str:
    if isinstance(valor, str) and valor.strip().lower() in permitidos:
        return valor.strip().lower()
    return padrao


def flag(valor, padrao: bool) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().lower() in {"true", "sim", "yes", "1"}
    return padrao


def cor_hex(valor, padrao: str) -> str:
    if isinstance(valor, str):
        candidato = valor.strip()
        if not candidato.startswith("#"):
            candidato = "#" + candidato
        if HEX.match(candidato):
            return candidato.upper()
    return padrao
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_validate.py -v`
Esperado: 10 passed

- [ ] **Step 5: Escrever `tests/test_llm.py` (falha)**

```python
import pytest

from vidbot import config, llm


def _cfg(**e):
    base = {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "g", "GEMINI_API_KEY": "m"}
    base.update(e)
    return config.carregar(base)


def test_usa_o_provedor_configurado(monkeypatch):
    monkeypatch.setattr(llm, "_CHAMADAS", {"groq": lambda *_: '{"ok": 1}'})
    assert llm.perguntar_json("p", "s", _cfg()) == {"ok": 1}


def test_cai_para_o_proximo_provedor_quando_o_primeiro_falha(monkeypatch):
    def quebra(*_):
        raise RuntimeError("429 free tier")

    monkeypatch.setattr(llm, "_CHAMADAS", {
        "groq": quebra,
        "gemini": lambda *_: '{"ok": 2}',
    })
    assert llm.perguntar_json("p", "s", _cfg()) == {"ok": 2}


def test_json_sujo_ainda_e_aproveitado(monkeypatch):
    monkeypatch.setattr(llm, "_CHAMADAS", {"groq": lambda *_: 'claro:\n```json\n{"ok": 3}\n```'})
    assert llm.perguntar_json("p", "s", _cfg()) == {"ok": 3}


def test_todos_falhando_levanta_sem_provedor(monkeypatch):
    def quebra(*_):
        raise RuntimeError("caiu")

    monkeypatch.setattr(llm, "_CHAMADAS", {"groq": quebra, "gemini": quebra})
    with pytest.raises(llm.SemProvedor):
        llm.perguntar_json("p", "s", _cfg())


def test_provedor_sem_chave_e_pulado(monkeypatch):
    monkeypatch.setattr(llm, "_CHAMADAS", {
        "groq": lambda *_: (_ for _ in ()).throw(AssertionError("nao deveria chamar")),
        "gemini": lambda *_: '{"ok": 4}',
    })
    assert llm.perguntar_json("p", "s", _cfg(GROQ_API_KEY="")) == {"ok": 4}
```

- [ ] **Step 6: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.llm'`

- [ ] **Step 7: Implementar `vidbot/llm.py`**

```python
"""LLM com fallback entre provedores. Free tier cai; a esteira nao pode parar."""
from __future__ import annotations

import logging

import requests

from .validate import extrair_json

log = logging.getLogger(__name__)
TIMEOUT = 120


class SemProvedor(RuntimeError):
    """Todos os provedores falharam."""


def _groq(prompt: str, sistema: str, cfg) -> str:
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg.groq_api_key}"},
        json={"model": "llama-3.3-70b-versatile",
              "messages": [{"role": "system", "content": sistema},
                           {"role": "user", "content": prompt}],
              "temperature": 0.4,
              "response_format": {"type": "json_object"}},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _gemini(prompt: str, sistema: str, cfg) -> str:
    r = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash:generateContent",
        headers={"x-goog-api-key": cfg.gemini_api_key},
        json={"system_instruction": {"parts": [{"text": sistema}]},
              "contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.4,
                                   "responseMimeType": "application/json"}},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _ollama(prompt: str, sistema: str, _cfg) -> str:
    r = requests.post(
        "http://localhost:11434/api/chat",
        json={"model": "llama3.2:3b", "stream": False, "format": "json",
              "messages": [{"role": "system", "content": sistema},
                           {"role": "user", "content": prompt}]},
        timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["message"]["content"]


_CHAMADAS = {"groq": _groq, "gemini": _gemini, "ollama": _ollama}
_CHAVE = {"groq": "groq_api_key", "gemini": "gemini_api_key"}


def _tem_chave(nome: str, cfg) -> bool:
    campo = _CHAVE.get(nome)
    return True if campo is None else bool(getattr(cfg, campo, ""))


def perguntar_json(prompt: str, sistema: str, cfg,
                   provedores: list[str] | None = None) -> dict:
    """Tenta o provedor configurado e depois os demais. Devolve dict."""
    ordem = provedores or [cfg.llm_provider] + [
        p for p in _CHAMADAS if p != cfg.llm_provider
    ]
    problemas = []
    for nome in ordem:
        chamada = _CHAMADAS.get(nome)
        if chamada is None or not _tem_chave(nome, cfg):
            continue
        try:
            return extrair_json(chamada(prompt, sistema, cfg))
        except Exception as erro:  # noqa: BLE001 - queremos tentar o proximo
            log.warning("provedor %s falhou: %s", nome, erro)
            problemas.append(f"{nome}: {erro}")
    raise SemProvedor("; ".join(problemas) or "nenhum provedor com chave")
```

- [ ] **Step 8: Rodar a suíte**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 67 passed

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: LLM com fallback entre provedores e validacao defensiva"
```

---

### Task 7: Seleção de trechos (`segment.py`)

O LLM sugere; o filtro determinístico decide. Os testes cobrem o filtro — não a criatividade do modelo.

**Files:**
- Create: `vidbot/segment.py`
- Test: `tests/test_segment.py`

**Interfaces:**
- Consumes: `captions.Palavra`, `captions.Transcricao`, `llm.perguntar_json`, `validate.*`
- Produces:
  - `segment.Candidato` — dataclass `(inicio_s: float, fim_s: float, titulo: str, gancho: str, nota: int)`; propriedade `.duracao_s`
  - `segment.coagir(bruto: dict) -> list[Candidato]`
  - `segment.ajustar_bordas(c: Candidato, palavras: list[Palavra]) -> Candidato`
  - `segment.filtrar(cands, *, min_s=20.0, max_s=90.0, max_cortes=12, sobrep_max=0.3) -> list[Candidato]`
  - `segment.janelas(palavras, *, max_chars=12000, sobrep_chars=1000) -> list[list[Palavra]]`
  - `segment.escolher(t: Transcricao, meta: dict, cfg, perguntar=llm.perguntar_json) -> list[Candidato]`

- [ ] **Step 1: Escrever `tests/test_segment.py` (falha)**

```python
from vidbot.captions import Palavra, Transcricao
from vidbot import segment as s


def _c(ini, fim, nota=50, titulo="t"):
    return s.Candidato(ini, fim, titulo, "gancho", nota)


def test_descarta_curto_demais():
    assert s.filtrar([_c(0, 5)]) == []


def test_descarta_longo_demais():
    assert s.filtrar([_c(0, 200)]) == []


def test_mantem_dentro_da_faixa():
    assert len(s.filtrar([_c(0, 40)])) == 1


def test_sobreposicao_grande_mantem_o_de_nota_maior():
    fraco, forte = _c(100, 160, nota=40, titulo="fraco"), _c(110, 170, nota=90, titulo="forte")
    assert [c.titulo for c in s.filtrar([fraco, forte])] == ["forte"]


def test_sobreposicao_pequena_mantem_os_dois():
    assert len(s.filtrar([_c(0, 60, nota=90), _c(55, 115, nota=80)])) == 2


def test_respeita_o_limite_de_cortes():
    muitos = [_c(i * 100, i * 100 + 40, nota=i) for i in range(20)]
    assert len(s.filtrar(muitos, max_cortes=5)) == 5


def test_ordena_por_nota_decrescente():
    r = s.filtrar([_c(0, 40, nota=10), _c(100, 140, nota=99)])
    assert [c.nota for c in r] == [99, 10]


def test_ajusta_a_borda_para_o_inicio_da_palavra_mais_proxima():
    palavras = [Palavra("a", 10.0, 10.5), Palavra("b", 10.5, 11.0), Palavra("c", 40.0, 40.4)]
    ajustado = s.ajustar_bordas(_c(10.3, 40.2), palavras)
    assert ajustado.inicio_s == 10.5
    assert ajustado.fim_s == 40.4


def test_ajuste_sem_palavras_nao_quebra():
    assert s.ajustar_bordas(_c(1.0, 2.0), []).inicio_s == 1.0


def test_coagir_grampeia_nota_e_ignora_item_sem_tempo():
    bruto = {"trechos": [
        {"inicio": 10, "fim": 50, "titulo": "ok", "gancho": "g", "nota": 999},
        {"titulo": "sem tempo"},
    ]}
    cands = s.coagir(bruto)
    assert len(cands) == 1 and cands[0].nota == 100


def test_coagir_descarta_intervalo_invertido():
    assert s.coagir({"trechos": [{"inicio": 90, "fim": 10, "nota": 50}]}) == []


def test_coagir_aceita_lista_na_raiz():
    assert len(s.coagir({"trechos": []})) == 0


def test_janelas_cobrem_todas_as_palavras():
    palavras = [Palavra("p" * 10, i, i + 1) for i in range(300)]
    js = s.janelas(palavras, max_chars=500, sobrep_chars=100)
    assert len(js) > 1
    assert js[0][0].texto == palavras[0].texto
    assert js[-1][-1].texto == palavras[-1].texto


def test_escolher_junta_as_janelas_e_filtra(monkeypatch):
    palavras = [Palavra("x", i, i + 1) for i in range(200)]
    t = Transcricao(palavras, "asr", "pt")

    def falso(prompt, sistema, cfg, **kw):
        return {"trechos": [{"inicio": 10, "fim": 50, "titulo": "a", "gancho": "g", "nota": 80}]}

    r = s.escolher(t, {"titulo": "Ep"}, cfg=None, perguntar=falso)
    assert len(r) == 1 and r[0].titulo == "a"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_segment.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.segment'`

- [ ] **Step 3: Implementar `vidbot/segment.py`**

```python
"""Transcricao -> trechos candidatos -> filtro deterministico.

O LLM sugere e da nota; quem decide e o filtro. Nota de modelo sozinha nao
basta: duracao, sobreposicao e bordas sao regra, nao opiniao.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, replace

from . import llm, validate as v
from .captions import Palavra, Transcricao

SISTEMA = """Voce escolhe trechos de podcast que funcionam como video curto.
Responda SOMENTE JSON: {"trechos": [{"inicio": s, "fim": s, "titulo": "...",
"gancho": "primeira frase", "nota": 0-100, "motivo": "..."}]}

Um bom trecho: e uma ideia autocontida, entendida sem o resto do episodio;
tem comeco e fim naturais; prende nos 3 primeiros segundos; dura 20 a 90s.
Use os tempos exatos da transcricao. Nao invente falas."""


@dataclass
class Candidato:
    inicio_s: float
    fim_s: float
    titulo: str
    gancho: str
    nota: int

    @property
    def duracao_s(self) -> float:
        return self.fim_s - self.inicio_s


def coagir(bruto: dict) -> list[Candidato]:
    saida = []
    for item in bruto.get("trechos") or []:
        if not isinstance(item, dict):
            continue
        ini = v.numero(item.get("inicio"), 0, 86400, -1, cast=float)
        fim = v.numero(item.get("fim"), 0, 86400, -1, cast=float)
        if ini < 0 or fim <= ini:
            continue
        saida.append(Candidato(
            ini, fim,
            v.texto(item.get("titulo"), "sem titulo", 95),
            v.texto(item.get("gancho"), "", 200),
            v.numero(item.get("nota"), 0, 100, 50),
        ))
    return saida


def ajustar_bordas(c: Candidato, palavras: list[Palavra]) -> Candidato:
    """Encosta as bordas nos limites de palavra para nao cortar no meio."""
    if not palavras:
        return c
    inicios = [p.inicio_s for p in palavras]
    i = min(bisect.bisect_left(inicios, c.inicio_s), len(palavras) - 1)
    j = min(bisect.bisect_left(inicios, c.fim_s), len(palavras) - 1)
    return replace(c, inicio_s=palavras[i].inicio_s, fim_s=palavras[j].fim_s)


def _sobreposicao(a: Candidato, b: Candidato) -> float:
    comum = min(a.fim_s, b.fim_s) - max(a.inicio_s, b.inicio_s)
    menor = min(a.duracao_s, b.duracao_s)
    return max(0.0, comum) / menor if menor > 0 else 0.0


def filtrar(cands: list[Candidato], *, min_s: float = 20.0, max_s: float = 90.0,
            max_cortes: int = 12, sobrep_max: float = 0.3) -> list[Candidato]:
    validos = [c for c in cands if min_s <= c.duracao_s <= max_s]
    validos.sort(key=lambda c: c.nota, reverse=True)
    escolhidos: list[Candidato] = []
    for c in validos:
        if any(_sobreposicao(c, j) > sobrep_max for j in escolhidos):
            continue
        escolhidos.append(c)
        if len(escolhidos) >= max_cortes:
            break
    return escolhidos


def janelas(palavras: list[Palavra], *, max_chars: int = 12000,
            sobrep_chars: int = 1000) -> list[list[Palavra]]:
    """Fatia a transcricao em janelas sobrepostas que cabem no contexto."""
    if not palavras:
        return []
    saida, atual, tamanho = [], [], 0
    for p in palavras:
        atual.append(p)
        tamanho += len(p.texto) + 1
        if tamanho >= max_chars:
            saida.append(atual)
            recuo, acumulado = [], 0
            for anterior in reversed(atual):
                recuo.insert(0, anterior)
                acumulado += len(anterior.texto) + 1
                if acumulado >= sobrep_chars:
                    break
            atual, tamanho = list(recuo), acumulado
    if atual and (not saida or atual is not saida[-1]):
        saida.append(atual)
    return saida


def _transcrever_janela(janela: list[Palavra]) -> str:
    return "\n".join(f"[{p.inicio_s:.1f}] {p.texto}" for p in janela)


def escolher(t: Transcricao, meta: dict, cfg,
             perguntar=llm.perguntar_json, **opcoes) -> list[Candidato]:
    """Percorre as janelas, junta os candidatos e aplica o filtro."""
    brutos: list[Candidato] = []
    for janela in janelas(t.palavras):
        prompt = (f"Episodio: {meta.get('titulo', '')}\n"
                  f"Transcricao (segundo entre colchetes):\n"
                  f"{_transcrever_janela(janela)}")
        try:
            brutos.extend(coagir(perguntar(prompt, SISTEMA, cfg)))
        except Exception:  # noqa: BLE001 - uma janela ruim nao derruba o episodio
            continue
    ajustados = [ajustar_bordas(c, t.palavras) for c in brutos]
    return filtrar(ajustados, **opcoes)
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_segment.py -v`
Esperado: 13 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: selecao de trechos com filtro deterministico"
```

---

### Task 8: Legendas em ASS (`perfis.py`, `subtitles.py`)

**Files:**
- Create: `vidbot/perfis.py`, `vidbot/subtitles.py`, `perfis/cortes_br.yaml`
- Test: `tests/test_perfis.py`, `tests/test_subtitles.py`

**Interfaces:**
- Consumes: `validate.*`, `captions.Palavra`
- Produces:
  - `perfis.Perfil` — dataclass `(nome, canal_token, reenquadre, max_cortes, min_s, max_s, privacidade, creditar_origem, idiomas: list[str], estilo: dict, cadencia: str)`
  - `perfis.carregar(caminho: Path) -> Perfil`, `perfis.carregar_todos(dir: Path) -> dict[str, Perfil]`
  - `subtitles.cor_ass(hex_rgb: str) -> str` — `#RRGGBB` → `&H00BBGGRR`
  - `subtitles.agrupar(palavras, por_cue: int) -> list[list[Palavra]]`
  - `subtitles.tempo_ass(segundos: float) -> str` — `3661.25` → `"1:01:01.25"`
  - `subtitles.gerar_ass(palavras, estilo: dict, *, karaoke: bool) -> str`

- [ ] **Step 1: Escrever `tests/test_perfis.py` e `tests/test_subtitles.py` (falham)**

```python
# tests/test_perfis.py
from vidbot import perfis


def _escrever(tmp_path, corpo):
    p = tmp_path / "x.yaml"
    p.write_text(corpo, encoding="utf-8")
    return p


def test_carrega_campos_declarados(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, """
nome: cortes_br
canal_token: cortes_br.json
reenquadre: rosto
max_cortes: 8
"""))
    assert p.nome == "cortes_br" and p.reenquadre == "rosto" and p.max_cortes == 8


def test_aplica_padroes_quando_o_yaml_e_minimo(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\n"))
    assert p.reenquadre == "centro"
    assert p.privacidade == "unlisted"
    assert p.idiomas == ["pt", "en"]


def test_reenquadre_invalido_cai_para_centro(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\nreenquadre: holograma\n"))
    assert p.reenquadre == "centro"


def test_privacidade_invalida_cai_para_unlisted(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\nprivacidade: secreto\n"))
    assert p.privacidade == "unlisted"


def test_estilo_tem_cores_validas(tmp_path):
    p = perfis.carregar(_escrever(tmp_path, "nome: x\nestilo:\n  cor_destaque: amarelo\n"))
    assert p.estilo["cor_destaque"].startswith("#")
```

```python
# tests/test_subtitles.py
from vidbot.captions import Palavra
from vidbot import subtitles as sub

ESTILO = {"fonte": "DejaVu Sans", "tamanho": 72, "cor_texto": "#FFFFFF",
          "cor_destaque": "#FFD400", "cor_contorno": "#000000", "contorno": 4,
          "posicao": "centro", "maiusculas": True, "caixa": False, "palavras_por_cue": 2}


def _ps():
    return [Palavra("um", 0.0, 0.5), Palavra("dois", 0.5, 1.0),
            Palavra("tres", 1.0, 1.6), Palavra("quatro", 1.6, 2.0)]


def test_cor_ass_inverte_para_bgr():
    assert sub.cor_ass("#FFD400") == "&H0000D4FF"


def test_cor_ass_aceita_preto():
    assert sub.cor_ass("#000000") == "&H00000000"


def test_agrupa_pelo_tamanho_pedido():
    grupos = sub.agrupar(_ps(), 2)
    assert [len(g) for g in grupos] == [2, 2]


def test_agrupamento_nao_perde_palavra():
    grupos = sub.agrupar(_ps(), 3)
    assert sum(len(g) for g in grupos) == 4


def test_ass_tem_cabecalho_e_eventos():
    texto = sub.gerar_ass(_ps(), ESTILO, karaoke=True)
    assert "[Script Info]" in texto and "[V4+ Styles]" in texto
    assert texto.count("Dialogue:") == 2


def test_maiusculas_sao_aplicadas():
    assert "UM DOIS" in sub.gerar_ass(_ps(), ESTILO, karaoke=False)


def test_karaoke_gera_marcacao_k():
    assert "\\k" in sub.gerar_ass(_ps(), ESTILO, karaoke=True)


def test_sem_karaoke_nao_gera_marcacao_k():
    assert "\\k" not in sub.gerar_ass(_ps(), ESTILO, karaoke=False)


def test_estilo_hostil_nao_quebra_o_arquivo():
    ruim = dict(ESTILO, tamanho=99999, cor_texto="rm -rf /", posicao="diagonal")
    texto = sub.gerar_ass(_ps(), ruim, karaoke=True)
    assert "[Script Info]" in texto and "rm -rf" not in texto


def test_tempo_formatado_no_padrao_ass():
    assert sub.tempo_ass(3661.25) == "1:01:01.25"
```

- [ ] **Step 2: Rodar e confirmar as falhas**

Run: `.venv/bin/python -m pytest tests/test_perfis.py tests/test_subtitles.py -v`
Esperado: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `vidbot/perfis.py`**

```python
"""Um YAML por canal de destino. Tudo validado na entrada."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import validate as v

REENQUADRES = {"centro", "rosto"}  # `split` do spec §5 fica para depois
PRIVACIDADES = {"private", "unlisted", "public"}
POSICOES = {"topo", "centro", "base"}


@dataclass
class Perfil:
    nome: str
    canal_token: str = ""
    reenquadre: str = "centro"
    max_cortes: int = 12
    min_s: float = 20.0
    max_s: float = 90.0
    privacidade: str = "unlisted"
    creditar_origem: bool = True
    cadencia: str = ""
    idiomas: list[str] = field(default_factory=lambda: ["pt", "en"])
    estilo: dict = field(default_factory=dict)


def _estilo(bruto) -> dict:
    b = bruto if isinstance(bruto, dict) else {}
    return {
        "fonte": v.texto(b.get("fonte"), "DejaVu Sans", 60),
        "tamanho": v.numero(b.get("tamanho"), 20, 130, 72),
        "cor_texto": v.cor_hex(b.get("cor_texto"), "#FFFFFF"),
        "cor_destaque": v.cor_hex(b.get("cor_destaque"), "#FFD400"),
        "cor_contorno": v.cor_hex(b.get("cor_contorno"), "#000000"),
        "contorno": v.numero(b.get("contorno"), 0, 8, 4),
        "posicao": v.escolha(b.get("posicao"), POSICOES, "centro"),
        "maiusculas": v.flag(b.get("maiusculas"), True),
        "caixa": v.flag(b.get("caixa"), False),
        "palavras_por_cue": v.numero(b.get("palavras_por_cue"), 1, 8, 3),
    }


def carregar(caminho: Path) -> Perfil:
    dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    idiomas = dados.get("idiomas")
    return Perfil(
        nome=v.texto(dados.get("nome"), Path(caminho).stem, 60),
        canal_token=v.texto(dados.get("canal_token"), "", 120),
        reenquadre=v.escolha(dados.get("reenquadre"), REENQUADRES, "centro"),
        max_cortes=v.numero(dados.get("max_cortes"), 1, 30, 12),
        min_s=v.numero(dados.get("min_s"), 5, 120, 20, cast=float),
        max_s=v.numero(dados.get("max_s"), 10, 180, 90, cast=float),
        privacidade=v.escolha(dados.get("privacidade"), PRIVACIDADES, "unlisted"),
        creditar_origem=v.flag(dados.get("creditar_origem"), True),
        cadencia=v.texto(dados.get("cadencia"), "", 40),
        idiomas=[str(i)[:5] for i in idiomas] if isinstance(idiomas, list) and idiomas
                else ["pt", "en"],
        estilo=_estilo(dados.get("estilo")),
    )


def carregar_todos(diretorio: Path) -> dict[str, Perfil]:
    saida = {}
    for arq in sorted(Path(diretorio).glob("*.yaml")):
        p = carregar(arq)
        saida[p.nome] = p
    return saida
```

- [ ] **Step 4: Implementar `vidbot/subtitles.py`**

```python
"""Trechos + estilo do perfil -> arquivo .ass queimado pelo ffmpeg.

O LLM nunca escreve ASS. O estilo vem do perfil e passa por clamp e whitelist
antes de virar texto: estilo hostil produz um arquivo feio, nunca invalido.
"""
from __future__ import annotations

from . import validate as v
from .captions import Palavra
from .perfis import POSICOES

ALINHAMENTO = {"topo": 8, "centro": 5, "base": 2}

CABECALHO = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: P,{fonte},{tamanho},{cor_texto},{cor_destaque},{cor_contorno},&H80000000,-1,0,{borda},{contorno},1,{alinhamento},60,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def cor_ass(hex_rgb: str) -> str:
    """#RRGGBB -> &H00BBGGRR (ASS usa BGR com alfa na frente)."""
    seguro = v.cor_hex(hex_rgb, "#FFFFFF").lstrip("#")
    r, g, b = seguro[0:2], seguro[2:4], seguro[4:6]
    return f"&H00{b}{g}{r}".upper()


def tempo_ass(segundos: float) -> str:
    s = max(0.0, float(segundos))
    h, resto = divmod(s, 3600)
    m, seg = divmod(resto, 60)
    return f"{int(h)}:{int(m):02d}:{seg:05.2f}"


def agrupar(palavras: list[Palavra], por_cue: int) -> list[list[Palavra]]:
    n = max(1, int(por_cue))
    return [palavras[i:i + n] for i in range(0, len(palavras), n)]


def _linha(grupo: list[Palavra], maiusculas: bool, karaoke: bool) -> str:
    if karaoke:
        partes = []
        for p in grupo:
            centesimos = max(1, round((p.fim_s - p.inicio_s) * 100))
            texto = p.texto.upper() if maiusculas else p.texto
            partes.append(f"{{\\k{centesimos}}}{texto}")
        return " ".join(partes)
    texto = " ".join(p.texto for p in grupo)
    return texto.upper() if maiusculas else texto


def gerar_ass(palavras: list[Palavra], estilo: dict, *, karaoke: bool) -> str:
    cabecalho = CABECALHO.format(
        fonte=v.texto(estilo.get("fonte"), "DejaVu Sans", 60),
        tamanho=v.numero(estilo.get("tamanho"), 20, 130, 72),
        cor_texto=cor_ass(estilo.get("cor_texto")),
        cor_destaque=cor_ass(estilo.get("cor_destaque")),
        cor_contorno=cor_ass(estilo.get("cor_contorno")),
        contorno=v.numero(estilo.get("contorno"), 0, 8, 4),
        borda=3 if v.flag(estilo.get("caixa"), False) else 1,
        alinhamento=ALINHAMENTO[v.escolha(estilo.get("posicao"), POSICOES, "centro")],
    )
    maiusculas = v.flag(estilo.get("maiusculas"), True)
    por_cue = v.numero(estilo.get("palavras_por_cue"), 1, 8, 3)

    eventos = []
    for grupo in agrupar(palavras, por_cue):
        if not grupo:
            continue
        texto = _linha(grupo, maiusculas, karaoke).replace("\n", " ")
        eventos.append(
            f"Dialogue: 0,{tempo_ass(grupo[0].inicio_s)},{tempo_ass(grupo[-1].fim_s)},"
            f"P,,0,0,0,,{texto}"
        )
    return cabecalho + "\n".join(eventos) + "\n"
```

- [ ] **Step 5: Criar o perfil de exemplo**

```bash
cat > perfis/cortes_br.yaml <<'EOF'
nome: cortes_br
canal_token: cortes_br.json
reenquadre: centro
max_cortes: 12
min_s: 20
max_s: 90
privacidade: unlisted
creditar_origem: true
cadencia: "0 9 * * *"
idiomas: [pt, en]
estilo:
  fonte: DejaVu Sans
  tamanho: 84
  cor_texto: "#FFFFFF"
  cor_destaque: "#FFD400"
  cor_contorno: "#000000"
  contorno: 5
  posicao: centro
  maiusculas: true
  caixa: false
  palavras_por_cue: 2
EOF
```

- [ ] **Step 6: Rodar a suíte**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 94 passed

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: perfis de canal e geracao de legenda ASS"
```

---

### Task 9: Download por seções e render (`download.py`, `reframe.py`, `render.py`)

> **PARE ANTES DE COMEÇAR.** Esta é a primeira tarefa que precisa de ffmpeg, que **não está instalado**. Peça ao operador para rodar, no terminal dele:
> ```
> sudo apt update && sudo apt install -y ffmpeg
> ```
> Confirme com `.venv/bin/python main.py doctor` (a linha `ffmpeg` deve sair `OK`) antes do Step 1.

**Files:**
- Create: `vidbot/download.py`, `vidbot/reframe.py`, `vidbot/render.py`
- Test: `tests/test_download.py`, `tests/test_reframe.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `captions.*`, `segment.Candidato`, `perfis.Perfil`
- Produces:
  - `download.opcoes_metadados() -> dict` e `download.opcoes_secao(inicio_s, fim_s, destino: Path) -> dict` — dicionários de opções do yt-dlp
  - `download.metadados(url: str, ydl=None) -> dict` — `{video_id, titulo, canal, duracao_s, capitulos, subtitles, automatic_captions}`
  - `download.baixar_secao(url, inicio_s, fim_s, destino: Path, ydl=None, progresso=None) -> Path`
  - `reframe.filtro_vertical(estrategia: str, largura: int, altura: int) -> str` — cadeia de filtros ffmpeg
  - `reframe.detectar_rosto_x(video: Path, largura: int) -> float | None` — fração 0..1 do centro horizontal; `None` se não achar
  - `render.montar_comando(entrada: Path, ass: Path, saida: Path, filtro: str) -> list[str]`
  - `render.renderizar(entrada, ass, saida, filtro, progresso=None) -> Path` — levanta `render.FalhaFFmpeg`

- [ ] **Step 1: Escrever `tests/test_download.py` e `tests/test_reframe.py` (falham)**

```python
# tests/test_download.py
from pathlib import Path

from vidbot import download as d


def test_metadados_nao_baixa_midia():
    assert d.opcoes_metadados()["skip_download"] is True


def test_secao_pede_apenas_o_intervalo():
    op = d.opcoes_secao(100.0, 160.0, Path("/tmp/x.mp4"))
    assert op["download_ranges"] is not None
    assert op["force_keyframes_at_cuts"] is True


def test_formato_prefere_h264_ate_1080p():
    assert "avc1" in d.opcoes_secao(0, 10, Path("/tmp/x.mp4"))["format"]
    assert "1080" in d.opcoes_secao(0, 10, Path("/tmp/x.mp4"))["format"]


def test_metadados_normaliza_o_dicionario_do_ytdlp():
    class FalsoYdl:
        def extract_info(self, url, download=False):
            return {"id": "A", "title": "Ep", "channel": "@x", "duration": 6000,
                    "chapters": [{"title": "c1", "start_time": 0}],
                    "subtitles": {}, "automatic_captions": {"pt": []}}

    m = d.metadados("https://youtu.be/A", ydl=FalsoYdl())
    assert m["video_id"] == "A" and m["duracao_s"] == 6000
    assert m["capitulos"][0]["title"] == "c1"


def test_metadados_tolera_campos_ausentes():
    class Magro:
        def extract_info(self, url, download=False):
            return {"id": "A"}

    m = d.metadados("https://youtu.be/A", ydl=Magro())
    assert m["titulo"] == "" and m["duracao_s"] == 0 and m["capitulos"] == []
```

```python
# tests/test_reframe.py
from vidbot import reframe as r


def test_centro_recorta_para_9x16():
    f = r.filtro_vertical("centro", 1920, 1080)
    assert "crop=" in f and "scale=1080:1920" in f


def test_estrategia_desconhecida_cai_para_centro():
    assert r.filtro_vertical("holograma", 1920, 1080) == r.filtro_vertical("centro", 1920, 1080)


def test_split_ainda_nao_implementado_cai_para_centro():
    """Documenta a lacuna: o spec preve `split`, esta versao nao o implementa."""
    assert r.filtro_vertical("split", 1920, 1080) == r.filtro_vertical("centro", 1920, 1080)


def test_rosto_desloca_o_recorte_horizontalmente():
    f = r.filtro_vertical("rosto", 1920, 1080, centro_x=0.25)
    assert "crop=" in f and ":0" in f


def test_recorte_nunca_sai_da_imagem():
    f = r.filtro_vertical("rosto", 1920, 1080, centro_x=0.99)
    largura_recorte = round(1080 * 9 / 16)
    x = int(f.split("crop=")[1].split(":")[2])
    assert 0 <= x <= 1920 - largura_recorte
```

- [ ] **Step 2: Rodar e confirmar as falhas**

Run: `.venv/bin/python -m pytest tests/test_download.py tests/test_reframe.py -v`
Esperado: FAIL com `ModuleNotFoundError`

- [ ] **Step 3: Implementar `vidbot/download.py`**

```python
"""yt-dlp como biblioteca. Duas fases: metadados/legendas, depois so os trechos."""
from __future__ import annotations

from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func

FORMATO = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/b[height<=1080]/b"


def opcoes_metadados() -> dict:
    return {"skip_download": True, "quiet": True, "no_warnings": True,
            "writesubtitles": False, "writeautomaticsub": False}


def opcoes_secao(inicio_s: float, fim_s: float, destino: Path,
                 progresso=None) -> dict:
    op = {
        "format": FORMATO,
        "outtmpl": str(destino),
        "quiet": True,
        "no_warnings": True,
        "download_ranges": download_range_func(None, [(float(inicio_s), float(fim_s))]),
        "force_keyframes_at_cuts": True,
    }
    if progresso is not None:
        op["progress_hooks"] = [progresso]
    return op


def metadados(url: str, ydl=None) -> dict:
    """Normaliza o dicionario do yt-dlp no formato que o pipeline usa."""
    if ydl is None:
        with YoutubeDL(opcoes_metadados()) as y:
            bruto = y.extract_info(url, download=False)
    else:
        bruto = ydl.extract_info(url, download=False)
    return {
        "video_id": bruto.get("id", ""),
        "titulo": bruto.get("title", "") or "",
        "canal": bruto.get("channel", "") or bruto.get("uploader", "") or "",
        "duracao_s": int(bruto.get("duration") or 0),
        "capitulos": bruto.get("chapters") or [],
        "url_original": bruto.get("webpage_url", url),
        "subtitles": bruto.get("subtitles") or {},
        "automatic_captions": bruto.get("automatic_captions") or {},
    }


def baixar_secao(url: str, inicio_s: float, fim_s: float, destino: Path,
                 ydl=None, progresso=None) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    opcoes = opcoes_secao(inicio_s, fim_s, destino, progresso)
    if ydl is None:
        with YoutubeDL(opcoes) as y:
            y.download([url])
    else:
        ydl.download([url])
    return destino
```

- [ ] **Step 4: Implementar `vidbot/reframe.py`**

```python
"""16:9 -> 9:16. Centro por padrao; rosto quando o perfil pedir.

Falha de deteccao cai para centro em silencio: degradar e melhor que falhar.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import validate as v

log = logging.getLogger(__name__)
# `split` (dois rostos empilhados) esta no spec §5 mas NAO foi implementado aqui:
# fica fora da whitelist de proposito, para cair em `centro` de forma previsivel
# em vez de aceitar o valor e ignorar o efeito.
ESTRATEGIAS = {"centro", "rosto"}
SAIDA_L, SAIDA_A = 1080, 1920


def filtro_vertical(estrategia: str, largura: int, altura: int,
                    centro_x: float | None = None) -> str:
    """Cadeia de filtros ffmpeg que leva o quadro para 1080x1920."""
    modo = v.escolha(estrategia, ESTRATEGIAS, "centro")
    recorte_l = min(largura, round(altura * 9 / 16))
    if modo == "rosto" and centro_x is not None:
        alvo = v.numero(centro_x, 0.0, 1.0, 0.5, cast=float)
        x = int(round(alvo * largura - recorte_l / 2))
        x = max(0, min(x, largura - recorte_l))
    else:
        x = (largura - recorte_l) // 2
    return f"crop={recorte_l}:{altura}:{x}:0,scale={SAIDA_L}:{SAIDA_A}"


def detectar_rosto_x(video: Path, largura: int, amostras: int = 5) -> float | None:
    """Fracao horizontal do rosto dominante, ou None. Nunca levanta."""
    try:
        import cv2
    except ImportError:
        return None
    try:
        cascata = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        captura = cv2.VideoCapture(str(video))
        total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        centros = []
        for i in range(amostras):
            captura.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / amostras))
            ok, quadro = captura.read()
            if not ok:
                continue
            cinza = cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY)
            rostos = cascata.detectMultiScale(cinza, 1.2, 5)
            if len(rostos):
                x, _, w, _ = max(rostos, key=lambda r: r[2] * r[3])
                centros.append((x + w / 2) / largura)
        captura.release()
        return sum(centros) / len(centros) if centros else None
    except Exception as erro:  # noqa: BLE001 - deteccao e opcional
        log.warning("deteccao de rosto falhou, usando centro: %s", erro)
        return None
```

- [ ] **Step 5: Rodar e confirmar que passam**

Run: `.venv/bin/python -m pytest tests/test_download.py tests/test_reframe.py -v`
Esperado: 9 passed

- [ ] **Step 6: Escrever `tests/test_render.py` (falha)**

```python
import shutil
from pathlib import Path

import pytest

from vidbot import render

sem_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg ausente")


def test_comando_queima_a_legenda_e_usa_h264():
    cmd = render.montar_comando(Path("e.mp4"), Path("l.ass"), Path("s.mp4"), "crop=1:2:3:0")
    linha = " ".join(cmd)
    assert "ass=" in linha and "libx264" in linha and cmd[0] == "ffmpeg"


def test_comando_passa_o_filtro_recebido():
    cmd = render.montar_comando(Path("e.mp4"), Path("l.ass"), Path("s.mp4"), "crop=9:9:9:0")
    assert "crop=9:9:9:0" in " ".join(cmd)


def test_comando_sobrescreve_sem_perguntar():
    assert "-y" in render.montar_comando(Path("e"), Path("l"), Path("s"), "f")


@sem_ffmpeg
def test_fumaca_gera_um_mp4_de_verdade(tmp_path):
    """Vídeo sintético de 2s criado pelo próprio ffmpeg — sem rede, sem fixture pesada."""
    entrada = render.gerar_video_de_teste(tmp_path / "e.mp4", segundos=2)
    ass = tmp_path / "l.ass"
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: P,DejaVu Sans,72\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:00.00,0:00:02.00,P,,0,0,0,,OI\n", encoding="utf-8")
    saida = render.renderizar(entrada, ass, tmp_path / "s.mp4", "scale=1080:1920")
    assert saida.exists() and saida.stat().st_size > 1000


@sem_ffmpeg
def test_entrada_invalida_levanta_falha_com_a_saida_do_ffmpeg(tmp_path):
    ruim = tmp_path / "nao_e_video.mp4"
    ruim.write_bytes(b"nada")
    with pytest.raises(render.FalhaFFmpeg):
        render.renderizar(ruim, tmp_path / "x.ass", tmp_path / "s.mp4", "scale=1080:1920")
```

- [ ] **Step 7: Implementar `vidbot/render.py`**

```python
"""ffmpeg: aplica o reenquadre e queima a legenda."""
from __future__ import annotations

import subprocess
from pathlib import Path


class FalhaFFmpeg(RuntimeError):
    """ffmpeg terminou com codigo diferente de zero. Carrega o stderr."""


def montar_comando(entrada: Path, ass: Path, saida: Path, filtro: str) -> list[str]:
    escapado = str(ass).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(entrada),
        "-vf", f"{filtro},ass='{escapado}'",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(saida),
    ]


def renderizar(entrada: Path, ass: Path, saida: Path, filtro: str,
               progresso=None) -> Path:
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    cmd = montar_comando(Path(entrada), Path(ass), saida, filtro)
    if progresso is not None:
        cmd[1:1] = ["-progress", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FalhaFFmpeg(f"codigo {proc.returncode}: {proc.stderr.strip()[:400]}")
    return saida


def gerar_video_de_teste(destino: Path, segundos: int = 2) -> Path:
    """Video sintetico para o teste de fumaca. Nao usado em producao."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size=1920x1080:rate=30:duration={segundos}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-shortest", str(destino),
    ], check=True, capture_output=True)
    return destino
```

- [ ] **Step 8: Rodar a suíte**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 103 passed (os dois testes de fumaça rodam de verdade agora que o ffmpeg existe)

- [ ] **Step 9: Retentativa do yt-dlp (spec §9)**

Adicionar a `vidbot/download.py` e o teste correspondente em `tests/test_download.py`:

```python
def com_retentativa(chamada, tentativas: int = 3, espera=time.sleep):
    """3 tentativas com backoff. Video privado ou removido nao melhora
    esperando, entao so erro transitorio e retentado."""
    ultimo = None
    for n in range(tentativas):
        try:
            return chamada()
        except Exception as erro:  # noqa: BLE001
            texto = str(erro).lower()
            if any(m in texto for m in ("private", "unavailable", "removed", "members-only")):
                raise
            ultimo = erro
            if n < tentativas - 1:
                espera(2 ** n)
    raise ultimo
```

```python
def test_retenta_erro_transitorio_e_sucede():
    chamadas = []

    def instavel():
        chamadas.append(1)
        if len(chamadas) < 3:
            raise RuntimeError("connection reset")
        return "ok"

    assert d.com_retentativa(instavel, espera=lambda _s: None) == "ok"
    assert len(chamadas) == 3


def test_nao_retenta_video_privado():
    def privado():
        raise RuntimeError("Video is private")

    with pytest.raises(RuntimeError):
        d.com_retentativa(privado, tentativas=3, espera=lambda _s: None)
```

Lembre de `import time` e `import pytest` nos respectivos arquivos, e de envolver a chamada real em `baixar_secao` com `com_retentativa`.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: download por secoes, reenquadre 9x16 e render com ffmpeg"
```

---

### Task 10: Publicação no YouTube (`youtube.py`)

**Files:**
- Create: `vidbot/youtube.py`
- Test: `tests/test_youtube.py`

**Interfaces:**
- Consumes: `db.*`, `perfis.Perfil`
- Produces:
  - `youtube.QUOTA_DIARIA = 10000`, `youtube.CUSTO_UPLOAD = 1600`
  - `youtube.uploads_restantes(con, dia: str) -> int`
  - `youtube.tem_quota(con, dia: str) -> bool`
  - `youtube.montar_descricao(perfil, meta: dict, corte) -> str`
  - `youtube.publicar(con, corte, perfil, meta, servico, dia: str) -> str` — devolve o id do vídeo; levanta `youtube.SemQuota`

- [ ] **Step 1: Escrever `tests/test_youtube.py` (falha)**

```python
import pytest

from vidbot import db, estados as e, perfis, youtube as yt


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


@pytest.fixture
def corte(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 10.0, 50.0, "Titulo do corte", 90)
    db.transicionar_corte(con, cid, e.AGUARDANDO_APROVACAO, e.APROVADO)
    return db.obter_corte(con, cid)


class ServicoFalso:
    def __init__(self, video_id="yt-abc"):
        self.video_id = video_id
        self.chamadas = []

    def inserir(self, corpo, caminho):
        self.chamadas.append((corpo, caminho))
        return self.video_id


def _perfil(**kw):
    return perfis.Perfil(nome="p", **kw)


def test_quota_comeca_cheia(con):
    assert yt.uploads_restantes(con, "2026-08-25") == 6


def test_cada_upload_consome_uma_vaga(con, corte):
    db.registrar_upload(con, corte.id, "x", "2026-08-25")
    assert yt.uploads_restantes(con, "2026-08-25") == 5


def test_quota_zera_e_bloqueia(con, corte):
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", "2026-08-25")
    assert yt.tem_quota(con, "2026-08-25") is False


def test_quota_do_dia_seguinte_esta_livre(con, corte):
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", "2026-08-25")
    assert yt.tem_quota(con, "2026-08-26") is True


def test_publicar_sem_quota_levanta_e_mantem_aprovado(con, corte):
    for i in range(6):
        db.registrar_upload(con, corte.id, f"x{i}", "2026-08-25")
    with pytest.raises(yt.SemQuota):
        yt.publicar(con, corte, _perfil(), {"url_original": "u"}, ServicoFalso(), "2026-08-25")
    assert db.obter_corte(con, corte.id).estado == e.APROVADO


def test_publicar_marca_como_publicado(con, corte):
    yt.publicar(con, corte, _perfil(), {"url_original": "u"}, ServicoFalso(), "2026-08-25")
    atualizado = db.obter_corte(con, corte.id)
    assert atualizado.estado == e.PUBLICADO and atualizado.youtube_id == "yt-abc"


def test_publicar_recusa_corte_nao_aprovado(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    cid = db.criar_corte(con, jid, 0.0, 30.0, "t", 50)
    pendente = db.obter_corte(con, cid)
    with pytest.raises(yt.NaoAprovado):
        yt.publicar(con, pendente, _perfil(), {"url_original": "u"}, ServicoFalso(), "2026-08-25")


def test_descricao_credita_a_origem_quando_o_perfil_pede(con, corte):
    texto = yt.montar_descricao(_perfil(creditar_origem=True),
                                {"url_original": "https://y/w?v=A", "canal": "@x"}, corte)
    assert "https://y/w?v=A" in texto and "@x" in texto


def test_descricao_sem_credito_nao_traz_o_link(con, corte):
    texto = yt.montar_descricao(_perfil(creditar_origem=False),
                                {"url_original": "https://y/w?v=A", "canal": "@x"}, corte)
    assert "https://y/w?v=A" not in texto


def test_privacidade_do_perfil_vai_no_corpo(con, corte):
    servico = ServicoFalso()
    yt.publicar(con, corte, _perfil(privacidade="public"), {"url_original": "u"},
                servico, "2026-08-25")
    corpo, _ = servico.chamadas[0]
    assert corpo["status"]["privacyStatus"] == "public"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `.venv/bin/python -m pytest tests/test_youtube.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'vidbot.youtube'`

- [ ] **Step 3: Implementar `vidbot/youtube.py`**

```python
"""Upload multi-canal com contador de quota.

Quota esgotada nao perde aprovacao: o corte fica em APROVADO e o scheduler
o drena no dia seguinte.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from . import db, estados as e

QUOTA_DIARIA = 10000
CUSTO_UPLOAD = 1600


class SemQuota(RuntimeError):
    """A quota do dia acabou. O corte continua APROVADO."""


class NaoAprovado(RuntimeError):
    """Tentativa de publicar corte que nao passou por aprovacao humana."""


def hoje() -> str:
    return date.today().isoformat()


def uploads_restantes(con, dia: str) -> int:
    usados = db.uploads_no_dia(con, dia)
    return max(0, QUOTA_DIARIA // CUSTO_UPLOAD - usados)


def tem_quota(con, dia: str) -> bool:
    return uploads_restantes(con, dia) > 0


def montar_descricao(perfil, meta: dict, corte) -> str:
    partes = [corte.titulo]
    if perfil.creditar_origem:
        partes.append(
            f"\nTrecho do episodio original de {meta.get('canal', '')}:\n"
            f"{meta.get('url_original', '')}"
        )
    return "\n".join(p for p in partes if p).strip()


def publicar(con, corte, perfil, meta: dict, servico, dia: str | None = None) -> str:
    """Sobe o corte. `servico.inserir(corpo, caminho) -> video_id`."""
    dia = dia or hoje()
    if corte.estado != e.APROVADO:
        raise NaoAprovado(f"corte {corte.id} esta em {corte.estado}")
    if not tem_quota(con, dia):
        raise SemQuota(f"quota de {dia} esgotada")

    corpo = {
        "snippet": {
            "title": corte.titulo[:95],
            "description": montar_descricao(perfil, meta, corte)[:4900],
            "categoryId": "22",
        },
        "status": {"privacyStatus": perfil.privacidade,
                   "selfDeclaredMadeForKids": False},
    }
    video_id = servico.inserir(corpo, str(corte.caminho or ""))
    db.registrar_upload(con, corte.id, video_id, dia)
    db.transicionar_corte(con, corte.id, e.APROVADO, e.PUBLICADO)
    return video_id


def servico_real(token_path: Path):
    """Cliente autenticado da YouTube Data API. Nao usado em teste."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    cred = Credentials.from_authorized_user_file(
        str(token_path), ["https://www.googleapis.com/auth/youtube.upload"])
    if cred.expired and cred.refresh_token:
        cred.refresh(Request())
    api = build("youtube", "v3", credentials=cred, cache_discovery=False)

    class Servico:
        def inserir(self, corpo, caminho):
            midia = MediaFileUpload(caminho, chunksize=-1, resumable=True)
            req = api.videos().insert(part="snippet,status", body=corpo, media_body=midia)
            return req.execute()["id"]

    return Servico()
```

- [ ] **Step 4: Rodar a suíte**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 113 passed

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: upload no YouTube com controle de quota diaria"
```

---

### Task 11: Telegram (`progresso.py`, `bot.py`)

A formatação e o represamento do progresso são lógica pura e vão num módulo próprio, testável sem rede. O `bot.py` fica só com a cola do Telegram.

**Files:**
- Create: `vidbot/progresso.py`, `vidbot/bot.py`
- Test: `tests/test_progresso.py`, `tests/test_bot.py`

**Interfaces:**
- Consumes: `db.*`, `estados.*`, `config.Config`, `urls.extrair_video_id`
- Produces:
  - `progresso.Painel` — `(job_id: int, canal: str, inicio: float)`; métodos `marcar(etapa: str, detalhe: str)`, `andamento(etapa, feitos, total)`, `falhar(etapa, mensagem)`, `texto() -> str`, `deve_enviar(agora: float) -> bool`
  - `progresso.INTERVALO_MINIMO = 5.0`
  - `bot.autorizado(user_id: int, cfg) -> bool`
  - `bot.ler_callback(dado: str) -> tuple[str, int] | None` — `"aprovar:12"` → `("aprovar", 12)`
  - `bot.decidir_corte(con, acao: str, corte_id: int) -> str` — aplica a transição e devolve o novo estado

- [ ] **Step 1: Escrever `tests/test_progresso.py` (falha)**

```python
from vidbot import progresso as p


def _painel():
    return p.Painel(job_id=58, canal="@x", inicio=1000.0)


def test_texto_traz_o_numero_do_job():
    assert "#58" in _painel().texto()


def test_etapa_concluida_aparece_com_visto():
    painel = _painel()
    painel.marcar("baixado", "1.8 GB")
    assert "baixado" in painel.texto() and "1.8 GB" in painel.texto()


def test_andamento_mostra_feitos_e_total():
    painel = _painel()
    painel.andamento("renderizando", 4, 12)
    assert "4/12" in painel.texto()


def test_estimativa_so_aparece_depois_do_primeiro_item():
    painel = _painel()
    painel.andamento("renderizando", 0, 12)
    assert "restante" not in painel.texto()


def test_estimativa_aparece_com_base_no_ritmo(monkeypatch):
    painel = _painel()
    monkeypatch.setattr(p, "agora", lambda: 1120.0)  # 2 min decorridos
    painel.andamento("renderizando", 2, 12)
    assert "restante" in painel.texto()


def test_falha_mostra_a_etapa_e_a_mensagem():
    painel = _painel()
    painel.marcar("baixado", "")
    painel.falhar("renderizando", "ffmpeg codigo 1")
    texto = painel.texto()
    assert "ffmpeg codigo 1" in texto and "renderizando" in texto


def test_primeiro_envio_e_sempre_permitido():
    assert _painel().deve_enviar(1000.0) is True


def test_envio_seguido_e_represado():
    painel = _painel()
    painel.deve_enviar(1000.0)
    painel.marcar("baixado", "x")
    assert painel.deve_enviar(1002.0) is False


def test_envio_liberado_apos_o_intervalo():
    painel = _painel()
    painel.deve_enviar(1000.0)
    painel.marcar("baixado", "x")
    assert painel.deve_enviar(1000.0 + p.INTERVALO_MINIMO + 0.1) is True


def test_texto_igual_nao_reenvia_mesmo_apos_o_intervalo():
    painel = _painel()
    painel.deve_enviar(1000.0)
    assert painel.deve_enviar(2000.0) is False
```

- [ ] **Step 2: Implementar `vidbot/progresso.py`**

```python
"""Painel de progresso do Telegram: uma mensagem, editada ate o fim.

O feedback e acessorio: nada aqui pode derrubar o processamento. Por isso a
formatacao e pura e o represamento vive junto dela, longe da rede.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

INTERVALO_MINIMO = 5.0


def agora() -> float:
    return time.monotonic()


@dataclass
class Painel:
    job_id: int
    canal: str
    inicio: float
    feitas: list[tuple[str, str]] = field(default_factory=list)
    atual: tuple[str, int, int] | None = None
    erro: tuple[str, str] | None = None
    _ultimo_envio: float = 0.0
    _ultimo_texto: str = ""

    def marcar(self, etapa: str, detalhe: str = "") -> None:
        self.feitas.append((etapa, detalhe))
        self.atual = None

    def andamento(self, etapa: str, feitos: int, total: int) -> None:
        self.atual = (etapa, feitos, total)

    def falhar(self, etapa: str, mensagem: str) -> None:
        self.erro = (etapa, mensagem)
        self.atual = None

    def _restante(self, feitos: int, total: int) -> str:
        if feitos <= 0:
            return ""
        decorrido = max(0.0, agora() - self.inicio)
        falta = decorrido / feitos * (total - feitos)
        return f" · ~{int(falta // 60)}min restante" if falta >= 60 else " · quase la"

    def texto(self) -> str:
        decorrido = int(max(0.0, agora() - self.inicio) // 60)
        linhas = [f"job #{self.job_id} · {self.canal} · decorrido {decorrido}min", ""]
        linhas += [f"[ok] {etapa}{f'   {det}' if det else ''}" for etapa, det in self.feitas]
        if self.atual:
            etapa, feitos, total = self.atual
            linhas.append(f"[..] {etapa}   {feitos}/{total}{self._restante(feitos, total)}")
        if self.erro:
            etapa, mensagem = self.erro
            linhas += [f"[!!] {etapa}", "", mensagem]
        return "\n".join(linhas)

    def deve_enviar(self, momento: float) -> bool:
        """True so quando o texto mudou E o intervalo minimo passou."""
        texto = self.texto()
        if texto == self._ultimo_texto:
            return False
        if self._ultimo_envio and momento - self._ultimo_envio < INTERVALO_MINIMO:
            return False
        self._ultimo_envio, self._ultimo_texto = momento, texto
        return True
```

- [ ] **Step 3: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_progresso.py -v`
Esperado: 10 passed

- [ ] **Step 4: Escrever `tests/test_bot.py` (falha)**

```python
import pytest

from vidbot import bot, config, db, estados as e


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _cfg(ids="7"):
    return config.carregar({"TELEGRAM_ALLOWED_USER_IDS": ids})


def _corte(con):
    jid = db.criar_job(con, "u", "A", "Ep", "@x", 600, "p")
    return db.criar_corte(con, jid, 0.0, 40.0, "t", 80)


def test_operador_listado_e_autorizado():
    assert bot.autorizado(7, _cfg()) is True


def test_estranho_e_recusado():
    assert bot.autorizado(999, _cfg()) is False


def test_sem_lista_ninguem_entra():
    assert bot.autorizado(7, _cfg(ids="")) is False


def test_callback_e_lido():
    assert bot.ler_callback("aprovar:12") == ("aprovar", 12)


def test_callback_malformado_devolve_none():
    assert bot.ler_callback("lixo") is None
    assert bot.ler_callback("aprovar:abc") is None
    assert bot.ler_callback("") is None


def test_aprovar_leva_o_corte_para_aprovado(con):
    cid = _corte(con)
    assert bot.decidir_corte(con, "aprovar", cid) == e.APROVADO


def test_descartar_leva_para_rejeitado(con):
    cid = _corte(con)
    assert bot.decidir_corte(con, "descartar", cid) == e.REJEITADO


def test_refazer_leva_para_refazer(con):
    cid = _corte(con)
    assert bot.decidir_corte(con, "refazer", cid) == e.REFAZER


def test_acao_desconhecida_nao_muda_nada(con):
    cid = _corte(con)
    with pytest.raises(ValueError):
        bot.decidir_corte(con, "publicar_agora", cid)
    assert db.obter_corte(con, cid).estado == e.AGUARDANDO_APROVACAO


def test_decidir_duas_vezes_nao_reaplica(con):
    cid = _corte(con)
    bot.decidir_corte(con, "aprovar", cid)
    with pytest.raises(bot.JaDecidido):
        bot.decidir_corte(con, "descartar", cid)
```

- [ ] **Step 5: Implementar `vidbot/bot.py`**

```python
"""Telegram: dispara, acompanha e aprova.

O bot enfileira; nao processa. Handler que renderiza video trava o bot inteiro.
"""
from __future__ import annotations

from . import db, estados as e

ACOES = {
    "aprovar": e.APROVADO,
    "descartar": e.REJEITADO,
    "refazer": e.REFAZER,
}


class JaDecidido(RuntimeError):
    """O corte saiu de AGUARDANDO_APROVACAO antes deste toque."""


def autorizado(user_id: int, cfg) -> bool:
    return bool(cfg.telegram_ids) and user_id in cfg.telegram_ids


def ler_callback(dado: str) -> tuple[str, int] | None:
    acao, _, bruto = (dado or "").partition(":")
    if acao not in ACOES or not bruto.isdigit():
        return None
    return acao, int(bruto)


def decidir_corte(con, acao: str, corte_id: int) -> str:
    """Aplica a decisao humana. Levanta se ja houve outra."""
    destino = ACOES.get(acao)
    if destino is None:
        raise ValueError(f"acao desconhecida: {acao}")
    if not db.transicionar_corte(con, corte_id, e.AGUARDANDO_APROVACAO, destino):
        raise JaDecidido(f"corte {corte_id} nao esta aguardando aprovacao")
    return destino


def teclado_do_corte(corte_id: int) -> list[list[tuple[str, str]]]:
    """(rotulo, callback_data) — convertido em InlineKeyboard pelo chamador."""
    return [[
        ("Publicar", f"aprovar:{corte_id}"),
        ("Refazer", f"refazer:{corte_id}"),
        ("Descartar", f"descartar:{corte_id}"),
    ]]
```

- [ ] **Step 6: Rodar a suíte**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 133 passed

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: painel de progresso e decisoes do bot do Telegram"
```

---

### Task 12: Ligar as etapas e fechar a CLI (`montar_passos`, `limpar`)

Até aqui cada peça existe e é testada isoladamente. Esta tarefa liga tudo: o pipeline passa a rodar de ponta a ponta.

**Files:**
- Create: `vidbot/etapas.py`
- Modify: `main.py`
- Test: `tests/test_etapas.py`, `tests/test_integracao.py`

**Interfaces:**
- Consumes: todos os módulos anteriores
- Produces:
  - `etapas.obter_legendas(job, workdir)` — busca metadados e legendas; `PulaPara(SEM_LEGENDA)` se não houver faixa
  - `etapas.selecionar(job, workdir)` — lê a transcrição do workdir, chama `segment.escolher`, grava os cortes; `PulaPara(SEM_CORTES)` se o filtro esvaziar
  - `etapas.fazer_renderizar(con, render_corte, perfil)` — para cada corte: baixa a seção, gera o `.ass`, renderiza; corte que falha vira `ERRO_RENDER` sem derrubar os demais. A função injetada tem assinatura `(corte, workdir, perfil, transcricao, url) -> Path`
  - `etapas.montar(cfg, perfis_dir) -> dict[str, pipeline.Passo]`
  - `main.cmd_limpar`

- [ ] **Step 1: Escrever `tests/test_etapas.py` (falha)**

```python
import json
from pathlib import Path

import pytest

from vidbot import db, estados as e, etapas, pipeline


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def _job(con):
    jid = db.criar_job(con, "https://youtu.be/A", "A", "", "", 0, "cortes_br")
    return db.obter_job(con, jid)


def test_sem_faixa_de_legenda_pula_para_sem_legenda(con, tmp_path):
    def meta(url, **kw):
        return {"video_id": "A", "titulo": "Ep", "canal": "@x", "duracao_s": 600,
                "capitulos": [], "url_original": url,
                "subtitles": {}, "automatic_captions": {}}

    etapa = etapas.fazer_obter_legendas(metadados=meta, baixar=lambda u: "")
    with pytest.raises(pipeline.PulaPara) as capturado:
        etapa(_job(con), tmp_path)
    assert capturado.value.estado == e.SEM_LEGENDA


def test_com_faixa_grava_a_transcricao_no_workdir(con, tmp_path):
    def meta(url, **kw):
        return {"video_id": "A", "titulo": "Ep", "canal": "@x", "duracao_s": 600,
                "capitulos": [], "url_original": url, "subtitles": {},
                "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}

    conteudo = json.dumps({"events": [
        {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "oi", "tOffsetMs": 0}]}]})
    etapa = etapas.fazer_obter_legendas(metadados=meta, baixar=lambda u: conteudo)
    etapa(_job(con), tmp_path)
    salvo = json.loads((tmp_path / "transcricao.json").read_text())
    assert salvo["origem"] == "asr" and salvo["palavras"][0]["texto"] == "oi"


def test_metadados_do_episodio_sao_gravados_no_job(con, tmp_path):
    def meta(url, **kw):
        return {"video_id": "A", "titulo": "Episodio 148", "canal": "@x",
                "duracao_s": 6720, "capitulos": [], "url_original": url,
                "subtitles": {"pt": [{"ext": "vtt", "url": "u"}]},
                "automatic_captions": {}}

    job = _job(con)
    etapa = etapas.fazer_obter_legendas(
        metadados=meta,
        baixar=lambda u: "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\noi\n",
        con=con)
    etapa(job, tmp_path)
    assert db.obter_job(con, job.id).titulo == "Episodio 148"


def test_filtro_vazio_pula_para_sem_cortes(con, tmp_path):
    (tmp_path / "transcricao.json").write_text(json.dumps(
        {"origem": "asr", "idioma": "pt",
         "palavras": [{"texto": "x", "inicio_s": 0, "fim_s": 1}]}))
    etapa = etapas.fazer_selecionar(con=con, escolher=lambda *a, **k: [])
    with pytest.raises(pipeline.PulaPara) as capturado:
        etapa(_job(con), tmp_path)
    assert capturado.value.estado == e.SEM_CORTES


def test_selecao_grava_um_corte_por_candidato(con, tmp_path):
    from vidbot.segment import Candidato

    (tmp_path / "transcricao.json").write_text(json.dumps(
        {"origem": "asr", "idioma": "pt",
         "palavras": [{"texto": "x", "inicio_s": 0, "fim_s": 1}]}))
    job = _job(con)
    etapa = etapas.fazer_selecionar(con=con, escolher=lambda *a, **k: [
        Candidato(10, 50, "um", "g", 90), Candidato(100, 140, "dois", "g", 80)])
    etapa(job, tmp_path)
    assert [c.titulo for c in db.cortes_do_job(con, job.id)] == ["um", "dois"]


def test_falha_num_corte_nao_derruba_os_outros(con, tmp_path):
    job = _job(con)
    bons = [db.criar_corte(con, job.id, 0, 40, "a", 90),
            db.criar_corte(con, job.id, 100, 140, "b", 80)]

    def render_de_um_falha(corte, workdir, perfil, transcricao, url):
        if corte.id == bons[0]:
            raise RuntimeError("ffmpeg codigo 1")
        return workdir / "ok.mp4"

    etapa = etapas.fazer_renderizar(con=con, render_corte=render_de_um_falha,
                                    perfil=etapas.PERFIL_PADRAO)
    etapa(job, tmp_path)
    estados_finais = {c.id: c.estado for c in db.cortes_do_job(con, job.id)}
    assert estados_finais[bons[0]] == e.ERRO_RENDER
    assert estados_finais[bons[1]] == e.AGUARDANDO_APROVACAO
```

- [ ] **Step 2: Implementar `vidbot/etapas.py`**

```python
"""As etapas reais do pipeline, com as dependencias injetaveis.

Cada `fazer_*` devolve a etapa ja amarrada, o que permite testar a orquestracao
sem rede e sem ffmpeg. `montar` liga tudo com as implementacoes de producao.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

from . import (captions, db, download, estados as e, perfis, pipeline,
               reframe, render, segment, subtitles)

log = logging.getLogger(__name__)
PERFIL_PADRAO = perfis.Perfil(nome="padrao")
ARQ_TRANSCRICAO = "transcricao.json"


def _salvar_transcricao(workdir: Path, t: captions.Transcricao) -> None:
    (Path(workdir) / ARQ_TRANSCRICAO).write_text(json.dumps({
        "origem": t.origem, "idioma": t.idioma,
        "palavras": [asdict(p) for p in t.palavras],
    }, ensure_ascii=False), encoding="utf-8")


def _ler_transcricao(workdir: Path) -> captions.Transcricao:
    d = json.loads((Path(workdir) / ARQ_TRANSCRICAO).read_text(encoding="utf-8"))
    return captions.Transcricao(
        [captions.Palavra(**p) for p in d["palavras"]], d["origem"], d["idioma"])


def fazer_obter_legendas(metadados=download.metadados, baixar=None,
                         con=None, idiomas=("pt", "en")):
    def etapa(job, workdir: Path) -> None:
        meta = metadados(job.url)
        if con is not None:
            con.execute(
                "UPDATE jobs SET titulo=?, canal_origem=?, duracao_s=? WHERE id=?",
                (meta["titulo"], meta["canal"], meta["duracao_s"], job.id))
        (Path(workdir) / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        obter = baixar or _baixar_url
        transcricao = captions.obter(meta, obter, list(idiomas))
        if transcricao is None:
            raise pipeline.PulaPara(e.SEM_LEGENDA)
        _salvar_transcricao(workdir, transcricao)

    return etapa


def _baixar_url(url: str) -> str:
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.text


def fazer_selecionar(con, escolher=segment.escolher, cfg=None,
                     perfil: perfis.Perfil = PERFIL_PADRAO):
    def etapa(job, workdir: Path) -> None:
        transcricao = _ler_transcricao(workdir)
        meta = json.loads((Path(workdir) / "meta.json").read_text(encoding="utf-8")) \
            if (Path(workdir) / "meta.json").exists() else {"titulo": job.titulo}
        candidatos = escolher(transcricao, meta, cfg,
                              min_s=perfil.min_s, max_s=perfil.max_s,
                              max_cortes=perfil.max_cortes)
        if not candidatos:
            raise pipeline.PulaPara(e.SEM_CORTES)
        for c in candidatos:
            db.criar_corte(con, job.id, c.inicio_s, c.fim_s, c.titulo, c.nota)

    return etapa


def _render_corte_real(corte, workdir: Path, perfil: perfis.Perfil,
                       transcricao: captions.Transcricao, url: str) -> Path:
    bruto = Path(workdir) / f"corte_{corte.id}_bruto.mp4"
    download.baixar_secao(url, corte.inicio_s, corte.fim_s, bruto)

    janela = [captions.Palavra(p.texto, p.inicio_s - corte.inicio_s,
                               p.fim_s - corte.inicio_s)
              for p in transcricao.palavras
              if corte.inicio_s <= p.inicio_s < corte.fim_s]
    ass = Path(workdir) / f"corte_{corte.id}.ass"
    ass.write_text(subtitles.gerar_ass(janela, perfil.estilo,
                                       karaoke=transcricao.por_palavra),
                   encoding="utf-8")

    centro = (reframe.detectar_rosto_x(bruto, 1920)
              if perfil.reenquadre == "rosto" else None)
    filtro = reframe.filtro_vertical(perfil.reenquadre, 1920, 1080, centro)
    return render.renderizar(bruto, ass, Path(workdir) / f"corte_{corte.id}.mp4", filtro)


def fazer_renderizar(con, render_corte=_render_corte_real,
                     perfil: perfis.Perfil = PERFIL_PADRAO):
    """`render_corte(corte, workdir, perfil, transcricao, url) -> Path`."""
    def etapa(job, workdir: Path) -> None:
        transcricao = (_ler_transcricao(workdir)
                       if (Path(workdir) / ARQ_TRANSCRICAO).exists()
                       else captions.Transcricao([], "asr", "pt"))
        for corte in db.cortes_do_job(con, job.id):
            if corte.caminho:
                continue  # ja renderizado numa execucao anterior
            try:
                saida = render_corte(corte, workdir, perfil, transcricao, job.url)
                db.definir_caminho_corte(con, corte.id, str(saida))
            except Exception as erro:  # noqa: BLE001 - isolar o corte
                log.warning("corte %s falhou: %s", corte.id, erro)
                db.transicionar_corte(con, corte.id, e.AGUARDANDO_APROVACAO,
                                      e.ERRO_RENDER, erro=str(erro)[:300])

    return etapa


def montar(con, cfg, perfil: perfis.Perfil) -> dict[str, pipeline.Passo]:
    return {
        e.NOVO: pipeline.Passo(
            fazer_obter_legendas(con=con, idiomas=tuple(perfil.idiomas)),
            e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(
            fazer_selecionar(con=con, cfg=cfg, perfil=perfil), e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(
            fazer_renderizar(con=con, perfil=perfil), e.RENDERIZADO),
    }
```

- [ ] **Step 3: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_etapas.py -v`
Esperado: 6 passed

- [ ] **Step 4: Ligar no `main.py`**

Substituir `montar_passos()` e o corpo de `cmd_run` por:

```python
def cmd_run(args) -> int:
    from vidbot import etapas, perfis as mod_perfis

    con = _con(args)
    try:
        cfg = config.carregar()
        job = (db.obter_job(con, args.job) if args.job
               else db.proximo_job(con, [e.NOVO, e.LEGENDA_OBTIDA, e.SEGMENTADO]))
        if job is None:
            print("nada a fazer")
            return 0
        todos = mod_perfis.carregar_todos(Path("perfis"))
        perfil = todos.get(job.perfil) or etapas.PERFIL_PADRAO
        passos = etapas.montar(con, cfg, perfil)
        final = pipeline.executar_job(con, job.id, passos, cfg.work_dir)
        print(f"job #{job.id} terminou em {final}")
        return 0 if final != e.ERRO else 1
    finally:
        con.close()


def cmd_limpar(args) -> int:
    """Remove workdirs de jobs que ja terminaram."""
    import shutil

    con = _con(args)
    try:
        cfg = config.carregar()
        finais = ",".join("?" * len(e.JOB_FINAIS))
        ids = [r["id"] for r in con.execute(
            f"SELECT id FROM jobs WHERE estado IN ({finais})", list(e.JOB_FINAIS))]
        removidos = 0
        for job_id in ids:
            d = Path(cfg.work_dir) / str(job_id)
            if d.is_dir():
                shutil.rmtree(d)
                removidos += 1
        print(f"{removidos} workdir(s) removido(s)")
        return 0
    finally:
        con.close()
```

E registrar o subcomando junto dos outros:

```python
    sub.add_parser("limpar", help="apaga workdirs de jobs encerrados")
```
```python
        "doctor": cmd_doctor, "ingest": cmd_ingest, "jobs": cmd_jobs,
        "run": cmd_run, "limpar": cmd_limpar,
```

- [ ] **Step 5: Teste de integração ponta a ponta (sem rede)**

```python
# tests/test_integracao.py
import json
from pathlib import Path

import pytest

from vidbot import db, estados as e, etapas, perfis, pipeline
from vidbot.segment import Candidato


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


def test_do_link_ate_aguardando_aprovacao(con, tmp_path):
    """Percorre NOVO -> RENDERIZADO com todas as bordas externas falsas."""
    jid = db.criar_job(con, "https://youtu.be/A", "A", "", "", 0, "p")

    meta = {"video_id": "A", "titulo": "Ep", "canal": "@x", "duracao_s": 600,
            "capitulos": [], "url_original": "https://youtu.be/A", "subtitles": {},
            "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}
    eventos = {"events": [{"tStartMs": i * 1000, "dDurationMs": 1000,
                           "segs": [{"utf8": f"p{i}", "tOffsetMs": 0}]}
                          for i in range(120)]}

    passos = {
        e.NOVO: pipeline.Passo(etapas.fazer_obter_legendas(
            metadados=lambda url, **k: meta,
            baixar=lambda u: json.dumps(eventos), con=con), e.LEGENDA_OBTIDA),
        e.LEGENDA_OBTIDA: pipeline.Passo(etapas.fazer_selecionar(
            con=con, escolher=lambda *a, **k: [Candidato(10, 50, "corte um", "g", 90)]),
            e.SEGMENTADO),
        e.SEGMENTADO: pipeline.Passo(etapas.fazer_renderizar(
            con=con,
            render_corte=lambda c, w, p, t, u: Path(w) / f"corte_{c.id}.mp4"),
            e.RENDERIZADO),
    }

    final = pipeline.executar_job(con, jid, passos, tmp_path)

    assert final == e.RENDERIZADO
    cortes = db.cortes_do_job(con, jid)
    assert len(cortes) == 1
    assert cortes[0].estado == e.AGUARDANDO_APROVACAO
    assert cortes[0].caminho.endswith(".mp4")


def test_nada_chega_a_publicado_sem_decisao_humana(con, tmp_path):
    """Trava estrutural: nenhuma etapa do pipeline publica."""
    jid = db.criar_job(con, "https://youtu.be/A", "A", "", "", 0, "p")
    db.criar_corte(con, jid, 0, 40, "t", 90)
    assert all(c.estado != e.PUBLICADO for c in db.cortes_do_job(con, jid))
```

- [ ] **Step 6: Rodar a suíte inteira**

Run: `.venv/bin/python -m pytest tests/ -v`
Esperado: 141 passed

- [ ] **Step 7: Conferir a CLI de verdade**

```bash
.venv/bin/python main.py doctor
.venv/bin/python main.py --db /tmp/vb.sqlite3 ingest <link-de-um-podcast> -p cortes_br
.venv/bin/python main.py --db /tmp/vb.sqlite3 run
.venv/bin/python main.py --db /tmp/vb.sqlite3 jobs
```
Esperado: o job avança até `RENDERIZADO` e os `.mp4` aparecem em `work/<id>/`.
Este é o primeiro contato com a rede de verdade — trate falhas do yt-dlp aqui como informação sobre o mundo real, não como bug do plano.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: liga as etapas no pipeline e fecha a CLI"
```

---

## Depois deste plano

Ficam de fora, para um segundo plano, e cada um está registrado aqui para não se perder:

- `bot.py` rodando de verdade contra a Bot API — aqui só a lógica pura foi construída e testada
- `scheduler.py` com as cadências dos perfis, incluindo o alerta de job travado há mais de 6h (spec §9) e o dreno diário dos cortes aprovados que ficaram sem quota (spec §7)
- O fluxo OAuth de cada canal, que gera os arquivos em `tokens/`
- A estratégia `split` de reenquadre (spec §5), hoje degradando para `centro` Todos dependem de credenciais que o operador precisa criar, e nenhum deles muda o núcleo — são clientes da CLI que já existe.
