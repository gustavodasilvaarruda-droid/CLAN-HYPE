"""Cálculos puros da futura Carteira HYPE (moeda inteira do jogo).

Não executa pagamentos nem altera banco; valores e lançamentos só se tornam
efetivos após validação transacional no backend.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Iterable


class FinanceError(ValueError):
    """Entrada financeira inválida."""


@dataclass(frozen=True)
class Entry:
    transaction_id: str
    account_id: str
    amount: int
    confirmed: bool = False


def _valid_amount(value: int, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FinanceError("Valor deve ser inteiro na moeda do jogo")
    if value < 0 or (value == 0 and not allow_zero):
        raise FinanceError("Valor deve ser positivo")
    return value


def wallet_balance(entries: Iterable[Entry], account_id: str) -> int:
    """Saldo exclusivamente de lançamentos confirmados, sem duplicidades."""
    if not account_id:
        raise FinanceError("Conta obrigatória")
    seen = set()
    balance = 0
    for entry in entries:
        if not entry.transaction_id or not entry.account_id:
            raise FinanceError("Lançamento sem identificador")
        if entry.transaction_id in seen:
            raise FinanceError("ID de transação duplicado")
        seen.add(entry.transaction_id)
        if isinstance(entry.amount, bool) or not isinstance(entry.amount, int):
            raise FinanceError("Valor inválido")
        if entry.confirmed and entry.account_id == account_id:
            balance += entry.amount
    return balance


def split_breeder_payment(total: int, fee_percent: str) -> tuple[int, int]:
    """Retorna (taxa do clã, repasse do breeder), sem arredondar para cima."""
    _valid_amount(total)
    try:
        rate = Decimal(str(fee_percent))
    except Exception as exc:
        raise FinanceError("Taxa inválida") from exc
    if not rate.is_finite() or not 0 <= rate <= 100:
        raise FinanceError("Taxa deve estar entre 0 e 100")
    clan_fee = int((Decimal(total) * rate / 100).to_integral_value(rounding=ROUND_DOWN))
    return clan_fee, total - clan_fee


def validate_transfer(balance: int, amount: int, payer: str, receiver: str) -> None:
    """Checagens de domínio; bloqueio de saldo e idempotência exigem banco."""
    _valid_amount(balance, allow_zero=True)
    _valid_amount(amount)
    if not payer or not receiver or payer == receiver:
        raise FinanceError("Contas de origem e destino inválidas")
    if amount > balance:
        raise FinanceError("Saldo insuficiente")
