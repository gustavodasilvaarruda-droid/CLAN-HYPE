# Carteira HYPE — etapa 2 (28/10/2026)

## Entregue na branch
- Migração isolada `sql/HYPE_WALLET_V1_20261028.sql`; **não foi executada no Supabase**.
- `hype_wallet_accounts`: saldo inteiro não negativo por identificador estável.
- `hype_wallet_entries`: extrato imutável por operação única.
- `hype_wallet_deposit_requests`: depósitos pendentes, confirmados ou recusados.
- RPC `hype_wallet_post`: bloqueio por conta, verificação de saldo e chave idempotente, tudo na mesma transação.
- RPC `hype_wallet_confirm_deposit`: confirma pedido apenas uma vez, sem creditar duas vezes.
- Escrita financeira reservada ao backend com `service_role`; nenhum privilégio para `anon`/`authenticated`.

## Ainda não funcional
- Nenhum botão/tela foi ligado à migração; nenhum depósito foi confirmado.
- Criar o vínculo estável entre login existente (`usuarios_clan`) e `owner_id`.
- Endpoints autenticados (solicitar depósito, confirmar/rejeitar com verificação de cargo).
- Pagamento de Breed e repasse a breeder, com atomicidade e reversão de cancelamentos.
- Política para operações simultâneas sobre conta e fechamento de caixa.
- Transações de carteira representam moeda virtual interna, não transferência de dinheiro real.
- Revisar permissão de `service_role`, backups, constraints reais e testes com banco de homologação.

## Fluxo proposto
1. Membro logado solicita depósito. Backend cria conta se necessário e pedido `pending`.
2. Pagamento acontece no jogo; somente líder autorizado confirma por endpoint protegido.
3. RPC de confirmação grava lançamento e atualiza saldo em transação única.
4. Cliente vê extrato e saldo; pedido confirmado não pode ser repetido.
5. Para comprar Breed, backend verifica saldo, estado do pedido e preço congelado na mesma operação transacional. Não realizar somente um débito sem marcar o pedido como pago.

**Sem merge/deploy até revisão de segurança e testes integrados.**
