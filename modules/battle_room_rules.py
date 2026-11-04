"""Regras puras para a Sala de Batalha HYPE, sem acesso ao banco."""
def players(match):
    first = match.get('jogador1_email')
    second = match.get('jogador2_email')
    if not first or not second or first == second:
        return ()
    return (first, second)


def both_ready(match, states):
    participants = players(match)
    return bool(participants) and all(
        bool(states.get(email, {}).get('pronto')) for email in participants
    )


def agreed_winner(match, states):
    """Retorna o vencedor apenas com dois palpites idênticos e jogadores prontos."""
    participants = players(match)
    if not both_ready(match, states):
        return None
    choices = [states.get(email, {}).get('vencedor_reportado_email')
               for email in participants]
    return choices[0] if choices[0] in participants and choices[0] == choices[1] else None
