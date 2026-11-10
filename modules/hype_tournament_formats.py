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
        "MECÂNICAS: Mega=" + str(original.get("permite_mega", False)) + ", Z-Move=" + str(original.get("permite_zmove", False)) + ", Tera=" + str(original.get("permite_tera", False)) + ", Dynamax=" + str(original.get("permite_dynamax", False)),
        "",
        original["observacao"],
        "Os times só devem ser considerados aprovados após validação completa "
        "do formato e revisão do organizador.",
    ]
    return "\n".join(linhas)
