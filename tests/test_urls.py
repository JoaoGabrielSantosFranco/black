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
