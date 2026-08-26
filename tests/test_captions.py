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


def test_parse_json3_com_none_devolve_lista_vazia():
    assert captions.parse_json3(None) == []


def test_parse_json3_com_lista_devolve_lista_vazia():
    assert captions.parse_json3([]) == []


def test_parse_json3_com_int_devolve_lista_vazia():
    assert captions.parse_json3(42) == []


def test_obter_com_null_json_nao_levanta():
    info = {"subtitles": {}, "automatic_captions": {"pt": [{"ext": "json3", "url": "u"}]}}
    t = captions.obter(info, baixar=lambda _url: "null", idiomas=["pt"])
    assert t is None


def test_nao_seleciona_srv3():
    info = {
        "subtitles": {},
        "automatic_captions": {"pt": [{"ext": "srv3", "url": "u-srv3"}]},
    }
    assert captions.escolher_faixa(info, ["pt"]) is None


def test_prefixo_de_idioma_combina_com_pt_br():
    info = {
        "subtitles": {"pt-BR": [{"ext": "vtt", "url": "u-pt-br"}]},
        "automatic_captions": {},
    }
    assert captions.escolher_faixa(info, ["pt"]) == ("u-pt-br", "autor", "pt-BR")


def test_ultima_palavra_fecha_no_fim_do_evento():
    ps = captions.parse_json3(json.loads((FIX / "asr.json3.json").read_text()))
    assert ps[-1].texto == "me"
    assert ps[-1].fim_s == 3.8
