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
    resultado = s.filtrar(muitos, max_cortes=5)
    assert len(resultado) == 5
    # Finding 3: must assert which candidates survive, not just count
    # Highest scores (19, 18, 17, 16, 15) should be selected
    assert sorted([c.nota for c in resultado], reverse=True) == [19, 18, 17, 16, 15]


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


def test_ajusta_borda_fim_quando_word_posterior_existe():
    # Exposes Finding 1: fim_s should snap to the end of the word containing it,
    # not stretch to a word after it.
    palavras = [
        Palavra("a", 10.0, 10.5),
        Palavra("b", 10.5, 11.0),
        Palavra("c", 40.0, 40.4),
        Palavra("d", 41.0, 41.5),
    ]
    ajustado = s.ajustar_bordas(_c(10.3, 10.7), palavras)
    # fim_s=10.7 falls inside word "b" (10.5-11.0), so should snap to 11.0
    assert ajustado.inicio_s == 10.5
    assert ajustado.fim_s == 11.0


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


def test_escolher_levanta_quando_todas_as_janelas_falham():
    # Finding 2: when every window fails, should raise instead of returning []
    palavras = [Palavra("x", i, i + 1) for i in range(200)]
    t = Transcricao(palavras, "asr", "pt")

    def sempre_falha(prompt, sistema, cfg, **kw):
        raise RuntimeError("provider falhou")

    try:
        s.escolher(t, {"titulo": "Ep"}, cfg=None, perguntar=sempre_falha)
        assert False, "deveria ter levantado RuntimeError"
    except RuntimeError:
        pass  # esperado


def test_escolher_ignora_falha_de_janelas_individuais():
    # Finding 2: when some windows fail, should still return results from successful ones
    # Create long words to force multiple windows with default max_chars=12000
    palavras = [Palavra("palavra" * 10, i * 2, i * 2 + 1) for i in range(1000)]
    t = Transcricao(palavras, "asr", "pt")

    chamadas = [0]

    def falha_depois(prompt, sistema, cfg, **kw):
        chamadas[0] += 1
        if chamadas[0] == 1:
            raise RuntimeError("primeira janela falhou")
        return {"trechos": [{"inicio": 10, "fim": 50, "titulo": "ok", "gancho": "g", "nota": 80}]}

    r = s.escolher(t, {"titulo": "Ep"}, cfg=None, perguntar=falha_depois)
    # Primeira janela falha, segunda sucede e retorna um clip
    assert len(r) == 1 and r[0].titulo == "ok"


def test_coagir_le_a_descricao_do_modelo():
    bruto = {"trechos": [{"inicio": 10, "fim": 50, "titulo": "t", "gancho": "g",
                          "nota": 80, "descricao": "Leon tenta uma estrategia inesperada"}]}
    assert s.coagir(bruto)[0].descricao == "Leon tenta uma estrategia inesperada"


def test_coagir_sem_descricao_nao_quebra():
    bruto = {"trechos": [{"inicio": 10, "fim": 50, "titulo": "t", "gancho": "g", "nota": 80}]}
    assert s.coagir(bruto)[0].descricao == ""


def test_prompt_pede_descricao():
    assert "descricao" in s.SISTEMA


def test_criterios_do_perfil_entram_no_prompt():
    sistema = s.montar_sistema("so momentos de humor, nada de tutorial")
    assert "so momentos de humor" in sistema and "SOMENTE JSON" in sistema


def test_sem_criterios_o_prompt_fica_o_base():
    assert s.montar_sistema("") == s.SISTEMA


def test_escolher_repassa_os_criterios_ao_modelo():
    from vidbot.captions import Palavra, Transcricao

    vistos = []

    def falso(prompt, sistema, cfg):
        vistos.append(sistema)
        return {"trechos": [{"inicio": 10, "fim": 50, "titulo": "a", "gancho": "g", "nota": 80}]}

    t = Transcricao([Palavra(f"p{i}", i, i + 1) for i in range(50)], "asr", "pt")
    s.escolher(t, {"titulo": "Ep"}, cfg=None, perguntar=falso, criterios="foco em briga")
    assert vistos and "foco em briga" in vistos[0]
