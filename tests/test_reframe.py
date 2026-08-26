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
