"""Presets versionados para criação segura de torneios da Arena HYPE.

Esta fase só publica formatos cuja prévia foi revisada. Um resumo de regras NÃO
substitui o validador completo do Pokémon Showdown; não sinalize times como
legais com base apenas nas listas abaixo.
"""
from copy import deepcopy

# Fonte consultada em 2026-11-09. Data de revisão, não versão oficial Smogon.
_FORMATS = {
    "gen9nationaldexubers": {
        "codigo": "gen9nationaldexubers",
        "geracao": 9,
        "nome": "Geração 9 · National Dex Ubers",
        "showdown": "gen9nationaldexubers",
        "revisado_em": "2026-11-10",
        "fonte": "https://www.smogon.com/forums/threads/national-dex-ubers-metagame-discussion.3712168/",
        "resumo": "National Dex Ubers: regras de tier, itens e mecânicas de acordo com a Smogon; exige verificação final no Showdown.",
        "clausulas": ("Standard NatDex", "Team Preview", "Species Clause", "OHKO Clause", "Evasion Clause"),
        "pokemons_proibidos": ("Shedinja", "Calyrex-Shadow", "Koraidon", "Miraidon", "Rayquaza-Mega", "Xerneas"),
        "itens_proibidos": ("Gengarite",),
        "golpes_proibidos": ("Assist", "Baton Pass"),
        "permite_mega": True,
        "permite_zmove": True,
        "permite_tera": True,
        "permite_dynamax": False,
        "observacao": (
            "Dynamax/Gigantamax não integra National Dex Ubers. Megas, Z-Moves e "
            "Terastal seguem as restrições próprias do formato. Esta lista "
            "continua resumida; a legalidade final requer Showdown."
        ),
    }
}

# Catálogo inicial de formatos Gen 9 para o painel e o Team Builder.
# Os IDs seguem a convenção de Pokémon Showdown. As banlists completas,
# restrições por geração, learnsets e requisitos de item/ability NÃO são
# reconstruíveis a partir desta tabela: a validação oficial será integrada
# em uma camada própria, nunca considerada aprovada por estes resumos.
# Fonte dos identificadores e regulamentos (sujeitos a atualizações):
# https://github.com/smogon/pokemon-showdown/blob/master/config/formats.ts
# Não cria nem modifica torneios históricos.
_GEN9_CATALOG = (
    # codigo, nome, modalidade, tamanho do time
    ('gen9anythinggoes', 'Geração 9 · Anything Goes (AG)', 'Singles', 6),
    ('gen9ubers', 'Geração 9 · Ubers', 'Singles', 6),
    ('gen9ubersuu', 'Geração 9 · Ubers UU', 'Singles', 6),
    ('gen9ou', 'Geração 9 · OU', 'Singles', 6),
    ('gen9uu', 'Geração 9 · UU', 'Singles', 6),
    ('gen9ru', 'Geração 9 · RU', 'Singles', 6),
    ('gen9nu', 'Geração 9 · NU', 'Singles', 6),
    ('gen9pu', 'Geração 9 · PU', 'Singles', 6),
    ('gen9zu', 'Geração 9 · ZU', 'Singles', 6),
    ('gen9lc', 'Geração 9 · Little Cup (LC)', 'Singles', 6),
    ('gen9monotype', 'Geração 9 · Monotype', 'Singles', 6),
    ('gen9doublesubers', 'Geração 9 · Doubles Ubers', 'Doubles', 6),
    ('gen9doublesou', 'Geração 9 · Doubles OU', 'Doubles', 6),
    ('gen9doublesuu', 'Geração 9 · Doubles UU', 'Doubles', 6),
    ('gen91v1', 'Geração 9 · 1v1', 'Singles', 3),
    ('gen92v2doubles', 'Geração 9 · 2v2 Doubles', 'Doubles', 4),
    ('gen9nationaldexag', 'Geração 9 · National Dex AG', 'Singles', 6),
    ('gen9nationaldex', 'Geração 9 · National Dex OU', 'Singles', 6),
    ('gen9nationaldexuu', 'Geração 9 · National Dex UU', 'Singles', 6),
    ('gen9nationaldexru', 'Geração 9 · National Dex RU', 'Singles', 6),
    ('gen9nationaldexmonotype', 'Geração 9 · National Dex Monotype', 'Singles', 6),
    ('gen9nationaldex1v1', 'Geração 9 · National Dex 1v1', 'Singles', 3),
    ('gen9nationaldexbh', 'Geração 9 · National Dex Balanced Hackmons', 'Singles', 6),
)
for _code, _name, _mode, _size in _GEN9_CATALOG:
    if _code in _FORMATS:
        continue
    _natdex = _code.startswith('gen9nationaldex')
    _FORMATS[_code] = {
        'codigo': _code, 'showdown': _code, 'geracao': 9, 'nome': _name,
        'modalidade': _mode, 'tamanho_equipe': _size,
        'nivel_maximo': 5 if _code == 'gen9lc' else 100,
        'revisado_em': '2026-11-10',
        'fonte': 'https://github.com/smogon/pokemon-showdown/blob/master/config/formats.ts',
        'resumo': 'Formato cadastrado para criação de torneio e montagem preliminar; ainda exige validação oficial do Showdown.',
        'clausulas': ('Regulamento específico do formato: consultar Showdown',),
        'pokemons_proibidos': (), 'itens_proibidos': (), 'golpes_proibidos': (),
        'permite_mega': _natdex,
        'permite_zmove': _natdex,
        'permite_tera': True,
        'permite_dynamax': False,
        'species_clause': _code not in ('gen9anythinggoes', 'gen9nationaldexag'),
        'validacao_completa': False,
        'observacao': (
            'Regras de banlist, formas, habilidades, golpes, combinações e '
            'mecânicas especiais dependem do validador do Showdown. '
            'Não considerar um time legal apenas porque passou na prévia HYPE.'
        ),
    }
# O preset histórico também continua sujeito à validação oficial.
for _entry in _FORMATS.values():
    _entry.setdefault('modalidade', 'Singles')
    _entry.setdefault('tamanho_equipe', 6)
    _entry.setdefault('nivel_maximo', 100)
    _entry.setdefault('validacao_completa', False)
    _entry.setdefault('species_clause', True)
del _entry, _code, _name, _mode, _size, _natdex



def formatos_disponiveis():
    """Cópias para serialização na prévia do formulário."""
    return [{**deepcopy(registro), 'regulamento': regulamento_congelado(registro)}
            for registro in _FORMATS.values()]


def obter_formato(codigo):
    """Não aceita nomes nem regras arbitrárias enviados pelo navegador."""
    formato = _FORMATS.get(str(codigo or "").strip().lower())
    return deepcopy(formato) if formato else None


def regulamento_congelado(formato):
    """Salva um retrato da regra escolhida no campo existente torneios.regras.

    Nenhuma migração ou mudança em torneios anteriores é necessária nesta etapa.
    """
    if not formato or formato.get("codigo") not in _FORMATS:
        raise ValueError("Formato predefinido inválido.")
    original = _FORMATS[formato["codigo"]]
    linhas = [
        f"FORMATO: {original['nome']}",
        f"Identificador Pokémon Showdown: {original['showdown']}",
        f"Resumo conferido em: {original['revisado_em']}",
        f"Referência: {original['fonte']}",
        "",
        "CLÁUSULAS BASE: " + ", ".join(original["clausulas"]),
        "POKÉMON PROIBIDOS (RESUMO): " + ", ".join(original["pokemons_proibidos"]),
        "GOLPES PROIBIDOS (RESUMO): " + ", ".join(original["golpes_proibidos"]),
        "ITENS PROIBIDOS (RESUMO): " + ", ".join(original.get("itens_proibidos", ())),
        f"MODALIDADE: {original['modalidade']} | SLOTS: {original['tamanho_equipe']} | NÍVEL MÁXIMO: {original['nivel_maximo']}",
        "VALIDAÇÃO: prévia do HYPE; equipe precisa de verificação oficial Showdown e aprovação do organizador.",
        "MECÂNICAS: Mega=" + str(original.get("permite_mega", False)) + ", Z-Move=" + str(original.get("permite_zmove", False)) + ", Tera=" + str(original.get("permite_tera", False)) + ", Dynamax=" + str(original.get("permite_dynamax", False)),
        "",
        original["observacao"],
        "Os times só devem ser considerados aprovados após validação completa "
        "do formato e revisão do organizador.",
    ]
    return "\n".join(linhas)
