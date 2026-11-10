"""Ponte com o TeamValidator real do Pokémon Showdown, sem chamadas externas.

A validação parcial pré-existente continua útil para filtragem instantânea.
O resultado 'unavailable' NUNCA pode ser interpretado como equipe aprovada.
Ativação: executar npm install --omit=dev na implantação do serviço Python.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

from modules.hype_tournament_formats import obter_formato

_ROOT = Path(__file__).resolve().parents[1]
_RUNNER = _ROOT / 'scripts' / 'hype_showdown_validate.cjs'
_STATS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')


def validar_time_showdown(slots, formato_codigo):
    """Retorna {status: legal | illegal | unavailable, errors: [...]}."""
    formato = obter_formato(formato_codigo)
    if not formato:
        return {'status': 'illegal', 'errors': ['Formato não está no catálogo HYPE.']}
    if not isinstance(slots, list) or not 1 <= len(slots) <= 6:
        return {'status': 'illegal', 'errors': ['Equipe inválida.']}
    if not shutil.which('node') or not (_ROOT / 'node_modules' / 'pokemon-showdown').is_dir():
        return {'status': 'unavailable', 'errors': ['Motor oficial ainda não instalado no servidor.']}
    clean = []
    for raw in slots:
        if not isinstance(raw, dict):
            return {'status': 'illegal', 'errors': ['Slot inválido.']}
        s = {k: raw.get(k) for k in (
            'pokemon', 'item', 'ability', 'nature', 'tera_type', 'gender', 'level')}
        s['moves'] = raw.get('moves', []) if isinstance(raw.get('moves'), list) else []
        for field, default in (('evs', 0), ('ivs', 31)):
            values = raw.get(field) or {}
            if not isinstance(values, dict):
                return {'status': 'illegal', 'errors': [field.upper() + ' inválidos.']}
            s[field] = {key: values.get(key, default) for key in _STATS}
        clean.append(s)
    payload = json.dumps({'format': formato['showdown'], 'slots': clean}, ensure_ascii=False)
    if len(payload.encode('utf-8')) > 60000:
        return {'status': 'illegal', 'errors': ['Equipe excede o limite de tamanho.']}
    try:
        # Subprocesso sem shell; ambiente mínimo para não expor segredos Supabase.
        result = subprocess.run(
            ['node', str(_RUNNER)], input=payload, text=True,
            capture_output=True, cwd=str(_ROOT), timeout=12, check=False,
            env={'PATH': os.environ.get('PATH', ''), 'NODE_ENV': 'production'},
        )
        if result.returncode != 0 or len(result.stdout) > 14000:
            raise ValueError('Falha ao executar o validador.')
        parsed = json.loads(result.stdout)
        if parsed.get('status') not in ('legal', 'illegal'):
            raise ValueError('Resposta indisponível do validador.')
        messages = parsed.get('errors') or []
        if not isinstance(messages, list):
            raise ValueError('Resposta inválida do validador.')
        return {'status': parsed['status'], 'errors': [str(m)[:250] for m in messages[:20]]}
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return {'status': 'unavailable', 'errors': ['Validação oficial indisponível. A equipe segue para conferência manual.']}
