from pathlib import Path

import pytest

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
