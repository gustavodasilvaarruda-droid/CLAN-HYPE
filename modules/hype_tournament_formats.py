"""Catálogo de formatos Gen 9 — snapshot versionado do Pokémon Showdown.

Filtros ajudam a montar equipes; NÃO equivalem à validação oficial (TeamValidator).
Novos formatos devem ser adicionados por atualização do snapshot, nunca com
regras arbitrárias que um navegador ou inscrição possam enviar ao servidor.
"""
from copy import deepcopy
import json
from pathlib import Path

_SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / 'data' / 'hype_showdown_gen9_snapshot.json'
with _SNAPSHOT_PATH.open(encoding='utf-8') as handle:
    _SNAPSHOT = json.load(handle)

_FORMATS = {row['codigo']: row for row in _SNAPSHOT['formatos']}
_ESPECIES = _SNAPSHOT['especies']


def especies_showdown():
    """Metadados de espécies / tiers correspondentes ao snapshot."""
    return deepcopy(_ESPECIES)


def obter_especie_showdown(codigo):
    import re
    chave = re.sub(r'[^a-z0-9]', '', str(codigo or '').casefold())
    # Os aliases '-Base' aparecem nas banlists oficiais, mas não no Pokédex.
    if chave.endswith('base') and chave[:-4] in _ESPECIES:
        chave = chave[:-4]
    return deepcopy(_ESPECIES.get(chave))


def formatos_disponiveis():
    """Formatos configuráveis por organizadores e Team Builder."""
    return [{**deepcopy(row), 'regulamento': regulamento_congelado(row)}
            for row in _FORMATS.values()]


def obter_formato(codigo):
    """Aceita apenas IDs oficiais presentes no catálogo fixo."""
    return deepcopy(_FORMATS.get(str(codigo or '').strip().lower()))


def regulamento_congelado(formato):
    """Guarda o ID e um resumo na coluna torneios.regras existente.

    A legalidade verdadeira depende do Pokémon Showdown + conferência.
    """
    if not isinstance(formato, dict) or formato.get('codigo') not in _FORMATS:
        raise ValueError('Formato predefinido inválido.')
    row = _FORMATS[formato['codigo']]
    linhas = [
        f"FORMATO: {row['nome']}",
        f"Identificador Pokémon Showdown: {row['showdown']}",
        f"Resumo conferido em: {row['revisado_em']}",
        f"Referência: {row['fonte']}",
        f"Tipo de batalha: {row['tipo_batalha']}",
        "",
        "REGRAS DE ORIGEM SHOWDOWN: " + ', '.join(row['regras_showdown']),
        "CLÁUSULAS HERDADAS (RESUMO): " + ', '.join(row['clausulas']),
        "BANLIST SHOWDOWN: " + ', '.join(row['banlist_showdown']),
        "POKÉMON PROIBIDOS (RESUMO): " + ', '.join(row['pokemons_proibidos']),
        "GOLPES PROIBIDOS (RESUMO): " + ', '.join(row['golpes_proibidos']),
        "ITENS PROIBIDOS (RESUMO): " + ', '.join(row['itens_proibidos']),
        "HABILIDADES PROIBIDAS (RESUMO): " + ', '.join(row['habilidades_proibidas']),
        "TIERS PROIBIDOS: " + ', '.join(row['tiers_proibidos']),
        ("MECÂNICAS: Mega={permite_mega}, Z-Move={permite_zmove}, Tera={permite_tera}, "
         "Dynamax={permite_dynamax}").format(**row),
        "",
        "Regras herdadas, combinações, golpes por origem e legalidade total "
        "DEVEM ser conferidos no TeamValidator oficial do Showdown. "
        "O snapshot não autoriza aprovação automática; a validação oficial é obrigatória.",
    ]
    return '\n'.join(linhas)
