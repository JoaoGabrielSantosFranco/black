import pytest

from vidbot import canais, db


@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "t.sqlite3")
    yield c
    c.close()


# ------------------------------------------------- normalizacao da url

def test_handle_vira_url_de_uploads():
    assert canais.normalizar("@leon") == "https://www.youtube.com/@leon/videos"


def test_url_de_canal_ganha_a_aba_de_videos():
    assert canais.normalizar("https://www.youtube.com/@leon") == \
        "https://www.youtube.com/@leon/videos"


def test_url_que_ja_aponta_para_videos_fica_igual():
    url = "https://www.youtube.com/@leon/videos"
    assert canais.normalizar(url) == url


def test_url_de_canal_por_id_e_aceita():
    bruto = "https://www.youtube.com/channel/UC123"
    assert canais.normalizar(bruto) == "https://www.youtube.com/channel/UC123/videos"


def test_link_que_nao_e_canal_e_recusado():
    assert canais.normalizar("https://vimeo.com/1") is None
    assert canais.normalizar("") is None


def test_link_de_video_nao_e_canal():
    assert canais.normalizar("https://youtu.be/EDmsbELe9Ic") is None


# ------------------------------------------------- cadastro

def test_canal_cadastrado_aparece_na_lista(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    assert [c.perfil for c in canais.listar(con)] == ["cortes_br"]


def test_canal_nasce_ativo(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    assert canais.listar(con)[0].ativo is True


def test_cadastrar_o_mesmo_canal_duas_vezes_nao_duplica(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    canais.cadastrar(con, "https://www.youtube.com/@leon", "outro")
    assert len(canais.listar(con)) == 1


def test_recadastrar_atualiza_o_perfil(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    canais.cadastrar(con, "@leon", "outro_perfil")
    assert canais.listar(con)[0].perfil == "outro_perfil"


def test_canal_invalido_nao_e_cadastrado(con):
    with pytest.raises(ValueError):
        canais.cadastrar(con, "https://vimeo.com/1", "p")


def test_desativar_tira_do_monitoramento(con):
    cid = canais.cadastrar(con, "@leon", "cortes_br")
    canais.definir_ativo(con, cid, False)
    assert canais.listar(con)[0].ativo is False
    assert canais.listar(con, so_ativos=True) == []


def test_remover_apaga_o_canal(con):
    cid = canais.cadastrar(con, "@leon", "cortes_br")
    assert canais.remover(con, cid) is True
    assert canais.listar(con) == []


def test_remover_canal_inexistente_devolve_false(con):
    assert canais.remover(con, 999) is False


# ------------------------------------------------- descoberta

def _uploads(*ids):
    """Imita a saida achatada do yt-dlp para uma aba /videos."""
    return {"entries": [{"id": i, "title": f"video {i}",
                         "url": f"https://youtu.be/{i}"} for i in ids]}


def test_descobrir_cria_job_para_cada_video_novo(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    novos = canais.descobrir(con, listar_uploads=lambda url, limite: _uploads("aaaaaaaaaaa",
                                                                             "bbbbbbbbbbb"))
    assert len(novos) == 2
    assert {j.video_id for j in db.listar_jobs(con)} == {"aaaaaaaaaaa", "bbbbbbbbbbb"}


def test_descobrir_usa_o_perfil_do_canal(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    canais.descobrir(con, listar_uploads=lambda url, limite: _uploads("aaaaaaaaaaa"))
    assert db.listar_jobs(con)[0].perfil == "cortes_br"


def test_video_ja_visto_nao_vira_job_de_novo(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    uploads = lambda url, limite: _uploads("aaaaaaaaaaa")  # noqa: E731
    canais.descobrir(con, listar_uploads=uploads)
    segunda = canais.descobrir(con, listar_uploads=uploads)
    assert segunda == []
    assert len(db.listar_jobs(con)) == 1


def test_canal_desativado_e_ignorado(con):
    cid = canais.cadastrar(con, "@leon", "cortes_br")
    canais.definir_ativo(con, cid, False)
    novos = canais.descobrir(con, listar_uploads=lambda url, limite: _uploads("aaaaaaaaaaa"))
    assert novos == [] and db.listar_jobs(con) == []


def test_entrada_sem_id_valido_e_ignorada(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    ruim = {"entries": [{"id": "curto"}, {"titulo": "sem id"}, None]}
    assert canais.descobrir(con, listar_uploads=lambda url, limite: ruim) == []


def test_canal_que_falha_nao_derruba_os_outros(con):
    canais.cadastrar(con, "@quebrado", "cortes_br")
    canais.cadastrar(con, "@bom", "cortes_br")

    def uploads(url, limite):
        if "quebrado" in url:
            raise RuntimeError("canal privado")
        return _uploads("aaaaaaaaaaa")

    novos = canais.descobrir(con, listar_uploads=uploads)
    assert [j.video_id for j in novos] == ["aaaaaaaaaaa"]


def test_descobrir_marca_o_canal_como_visto(con):
    canais.cadastrar(con, "@leon", "cortes_br")
    canais.descobrir(con, listar_uploads=lambda url, limite: _uploads("aaaaaaaaaaa"))
    assert canais.listar(con)[0].visto_em is not None


def test_nome_do_canal_sai_do_handle(con):
    canais.cadastrar(con, "https://www.youtube.com/@leon/videos", "p")
    assert canais.listar(con)[0].nome == "@leon"


def test_nome_explicito_vence_o_derivado(con):
    canais.cadastrar(con, "@leon", "p", nome="Leon Oficial")
    assert canais.listar(con)[0].nome == "Leon Oficial"
