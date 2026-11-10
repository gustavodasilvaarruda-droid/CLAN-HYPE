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
        "revisado_em": "2026-11-09",
        "fonte": "https://www.smogon.com/dex/sv/formats/national-dex-ubers/",
        "resumo": "Formato National Dex Ubers: Shedinja, Assist e Baton Pass são proibidos.",
        "clausulas": ("Standard NatDex", "Team Preview", "Species Clause"),
        "pokemons_proibidos": ("Shedinja",),
        "golpes_proibidos": ("Assist", "Baton Pass"),
        "observacao": (
            "Também se aplicam as demais cláusulas e restrições herdadas do "
            "formato National Dex Ubers/ND AG. A lista abaixo é um resumo "
            "informativo, não uma validação exaustiva de legalidade."
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
        "",
        original["observacao"],
        "Os times só devem ser considerados aprovados após validação completa "
        "do formato e revisão do organizador.",
    ]
    return "\n".join(linhas)
