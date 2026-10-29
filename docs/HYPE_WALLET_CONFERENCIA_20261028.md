# HYPE Carteira — conferência financeira (etapa seguinte)

## Recursos preparados
- RPC somente leitura `hype_wallet_integrity_report`, para o servidor/admin, sem acesso a visitantes e membros comuns.
- Soma de saldos de contas e soma de todos os lançamentos.
- Detecta carteiras cujo saldo armazenado difere da soma do extrato.
- Detecta depósito confirmado sem entrada financeira correspondente.
- Detecta lançamento de depósito sem solicitação confirmada correspondente.
- Exibe aviso de divergência no Painel do Líder; não cria, edita ou transfere moedas.

## Segurança e testes pendentes
- Revisar relatório em homologação e aplicar `sql/HYPE_WALLET_AUDITORIA_20261028.sql` no banco correto antes de publicar a interface.
- Testes automatizados mockados verificam que membro comum não acessa relatório e que líder consegue visualizá-lo.
- Não habilitar `HYPE_WALLET_DEPOSITS_ENABLED` enquanto a auditoria, o CSRF real e o fluxo de depósito completo não estiverem validados.
- O relatório é agregado. Ele não expõe e-mails ou nomes dos depositantes.
- Uma auditoria com zero divergências não comprova pagamento no Minecraft: o líder sempre deve conferir manualmente antes de liberar saldo.
- Não inclui pagamento de Breed, repasses, saques ou uso de saldo para torneios; continuam pendentes.

## Operação
- `HYPE_WALLET_ENABLED`: habilita leitura se o backend tem credencial, desligada por padrão.
- `HYPE_WALLET_DEPOSITS_ENABLED`: habilita novas solicitações e aprovações; manter desligada até teste de ponta a ponta.
- `SUPABASE_SERVICE_ROLE_KEY`: inserir somente nas variáveis secretas do serviço Render, sem incluir no Git nem compartilhar na conversa.
- A demonstração separada continua sem banco e usando dados fictícios.
