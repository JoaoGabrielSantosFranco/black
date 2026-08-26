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
