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


def test_fonte_com_virgula_nao_quebra_campo():
    estilo_ruim = dict(ESTILO, fonte="Evil,Font")
    texto = sub.gerar_ass(_ps(), estilo_ruim, karaoke=True)
    assert "[Script Info]" in texto
    linhas_style = [l for l in texto.split("\n") if l.startswith("Style:")]
    assert len(linhas_style) == 1
    campos = linhas_style[0].split(",")
    assert len(campos) == 17


def test_fonte_com_quebra_de_linha_nao_quebra_arquivo():
    estilo_ruim = dict(ESTILO, fonte="Evil\nFont")
    texto = sub.gerar_ass(_ps(), estilo_ruim, karaoke=True)
    assert "[Script Info]" in texto
    assert texto.count("Style: P,") == 1
    linhas_style = [l for l in texto.split("\n") if l.startswith("Style:")]
    assert len(linhas_style) == 1


def test_fonte_com_retorno_carro_nao_quebra_arquivo():
    estilo_ruim = dict(ESTILO, fonte="Evil\rFont")
    texto = sub.gerar_ass(_ps(), estilo_ruim, karaoke=True)
    assert "[V4+ Styles]" in texto
    linhas_style = [l for l in texto.split("\n") if l.startswith("Style:")]
    assert len(linhas_style) == 1
