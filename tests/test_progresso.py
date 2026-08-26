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
