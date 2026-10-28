# Carteira HYPE — validação da etapa de depósitos (28/10/2026)

## Status verificado no Supabase
- Migração `hype_wallet_v1_20261028` aplicada no projeto conectado.
- Tabelas existentes: `hype_wallet_accounts`, `hype_wallet_deposit_requests` e `hype_wallet_entries`.
- No momento da verificação: **0 contas, 0 solicitações, 0 entradas**.
- Políticas: RLS habilitado, nenhuma política pública. `anon` e `authenticated` não conseguem executar as RPCs nem ler as tabelas; `service_role` possui os privilégios esperados.
- Não foi executada nenhuma movimentação financeira real ou fictícia.

## Entregue no GitHub
- Rotas Flask e telas separadas para membro e administrador.
- Depósitos solicitados por membros ativos do clã e confirmados no jogo pelo líder.
- Três etapas para crédito: pedido `pending` → recebimento verificado → confirmação pelo líder, cuja RPC faz crédito uma vez.
- RPC de recusa não credita saldo.
- Cálculo do saldo e extrato isolados das `transacoes_hype` antigas.
- Testes unitários isolados com cliente Supabase simulado e workflow dedicado do GitHub Actions.

## Ativação gradual no Render (ainda NÃO realizada)
1. Verificar que a PR da carteira está revisada e que os testes passam antes de qualquer merge.
2. Criar variável de ambiente **secreta** `SUPABASE_SERVICE_ROLE_KEY` no painel do servidor Render. Não inserir no Git, HTML, logs nem nesta conversa; ela confere acesso administrativo ao banco.
3. Com `HYPE_WALLET_ENABLED=1`, as telas poderão consultar saldos. Mantendo `HYPE_WALLET_DEPOSITS_ENABLED=0`, nenhum depósito pode ser solicitado/confirmado pelas novas rotas.
4. Somente depois de validar login, CSRF, permissões e teste de crédito/repetição de confirmação em ambiente de homologação, ativar `HYPE_WALLET_DEPOSITS_ENABLED=1`.
5. Depósitos ainda dependem de entrega manual de moedas no Minecraft e confirmação humana; o site não verifica o pagamento no jogo sozinho.

## Testes mínimos antes de usar
- [ ] Entrar como membro ativo, visitante e administrador e testar permissão.
- [ ] Verificar POST sem token CSRF usando o Flask real (não apenas Blueprint isolado).
- [ ] Enviar dois pedidos do mesmo jogador; confirmar apenas o recebido.
- [ ] Tentar confirmar o mesmo depósito duas vezes e verificar crédito único.
- [ ] Simular confirmações concorrentes em ambiente de testes.
- [ ] Recusar pedido e verificar saldo invariável.
- [ ] Verificar saldo e histórico após reiniciar Flask/Render.
- [ ] Garantir não exposição de service role key.
- [ ] Verificar logs de auditoria administrativos e backup do Supabase.
- [ ] Verificar acessibilidade no celular.

## Pendências
- **Pagamento por carteira no Breed** não está habilitado: requer transação única no banco para desconto e transição do pedido, com regras de cancelamento/estorno.
- **Repasses aos breeders**, inscrição e premiação de torneios ainda dependem do livro-razão financeiro.
- A PR #11 (economia/isencao/chaveamentos) deve ser revisada separadamente. No banco atual, o constraint de `hype_breed_comissoes` não aceita `isento` até sua migração ser aplicada.
- Avisos de segurança anteriores do Supabase devem ser avaliados sem alterar funções legadas às cegas.

**Código em branch; publicação no Render ainda pendente. Não publicar as telas com depósitos ativos sem validação.**
