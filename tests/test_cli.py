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


def test_bot_sem_token_avisa_e_nao_sobe(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    code = main.main(_argv(tmp_path, "bot"))
    assert code == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().out


def test_bot_sem_operadores_avisa_e_nao_sobe(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    code = main.main(_argv(tmp_path, "bot"))
    assert code == 1
    assert "TELEGRAM_ALLOWED_USER_IDS" in capsys.readouterr().out
