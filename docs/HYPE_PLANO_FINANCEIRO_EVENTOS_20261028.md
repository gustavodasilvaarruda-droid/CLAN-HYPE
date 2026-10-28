# HYPE Site — plano integrado de melhorias (28/10/2026)

## Escopo aprovado na conversa
Todas as moedas abaixo sao **moedas internas do Minecraft**, nao reais. As funcões financeiras
devem ser controladas pelo servidor Flask/Supabase; o navegador nunca define sozinho um saldo.

### 1. Carteira HYPE (membro, no painel pessoal)
- Deposito solicitado pelo membro -> pagamento no jogo -> confirmacao manual pelo lider ->
  credito de saldo. A solicitacao por si so NAO libera saldo.
- Pagar Breed com saldo => desconto atomico e pedido marcado como pago; se nao houver
  saldo suficiente, manter fluxo atual. Bloquear uso duplo em pedidos concorrentes.
- Extrato com data/valor/referencia/responsavel; estorno de cancelamento, sem apagar historico.
- Nao usar `transacoes_hype` como saldo monetario sem migrar/conciliar dados:
  atualmente a tabela registra movimentacoes informativas de Breed e ajustes manuais.
- Depositos sao passivos do cla ate efetiva utilizacao; nao contam como receita do cla.

### 2. Repasses aos breeders (Admin)
- Pagamento com carteira cria obrigacao de repasse associada a pedido e breeder.
- Valor congelado: preco_total menos taxa efetiva daquele pedido (respeitar desconto
  do ranking; nao presumir 25%, pois o codigo tem percentual configuravel).
- Mostrar lista automatica 'pendente / liberado / pago / estornado' por breeder.
- Liberar para pagamento apenas apos entrega/conclusao conforme politica acordada.
- Pagamento no Minecraft e confirmacao manual do lider; bloquear confirmacao duplicada.
- Breeds pagos diretamente ao breeder permanecem com cobranca da taxa ao cla,
  sem criar um segundo repasse ficticio.

### 3. Economia e transparencia no Tesouro
- Preservar 'Tesouro do Cla' existente (patrimonio, Pokemon, Mega Stones e emprestimos).
- Adicionar pagina de economia, inicialmente somente leitura, com valores confirmados
  de `hype_caixa_clan`. Entradas: taxas Breed recebidas, alugueis de casas e lojas,
  doacoes/receitas manuais confirmadas. Saidas: premiacoes, eventos, aquisicoes etc.
- Publico-alvo: apenas membros ativos; nao divulgar e-mail/identidade do pagador no extrato.
- Extrato detalhado e as correcoes ficam no Admin, sempre com auditoria.
- Na evolucao, movimentacoes de saida devem ter solicitacao, motivo, comprovante
  opcional e confirmacao de entrega no jogo.
- Nao somar saldo de carteiras, premiacoes reservadas e repasses pendentes ao caixa
  livre: cada categoria tem obrigacoes separadas.

### 4. Conselho HYPE (governanca)
- Qualquer membro pode propor compras; apenas lider decide colocacao em votacao
  e autorizacao final (a votacao e consultiva).
- Um voto por membro; inicio/fim, quorum, desempate, historico e trilha de auditoria.
- Proposta exibe preco, saldo livre, estimativa pos-compra e finalidade.
- Quando lider autoriza compra, reservar verba; debitar caixa so apos confirmar compra
  no jogo. Vincular item recebido ao Arsenal/Tesouro existente.

### 5. Isencao das comissoes anteriores ao inicio da cobranca
- A data de corte deve ser escolhida no Admin.
- RPC de lote com atualizacao atomica e auditada. Somente comissoes em estado
  **pendente** anteriores a data sao isentas; **pagas e informadas sao preservadas**.
- "Isento" nao e sinonimo de "Pago" e nao gera entrada no caixa.
- Verificar constraints e executar a migracao SQL antes de usar o formulario.
- Manter regras existentes para comissoes geradas a partir da data de corte.

### 6. Eventos e torneios
- Inscricao exige identificacao do usuario, valor de inscricao congelado e
  confirmacao de pagamento em jogo ou carteira. Nao considerar inscricao
  paga ate confirmacao efetiva.
- Cada competicao tera uma conta/fundo reservado para inscricoes, separado do caixa.
- Configuracao por evento de percentual do cla, premios (por exemplo 1º, 2º, 3º)
  e itens/premios no "Hall de Premios" antes da inscricao. Congelar percentuais
  ao abrir as inscricoes.
- Torneios do dia e mensais: mesmo motor de chaveamento, com duracao diferente.
  Sortear uma unica vez apos encerrar inscricoes; mostrar nick e avatar do jogador.
  Nao apagar chaves com resultados em sorteio repetido.
- Resultado registrado pelo organizador -> avanco de rodada -> campeao/vice ->
  atualizar o ranking *existente* (nao duplicar ranking) e Hall de Premios.
- Premios em moeda sao obrigações ate pagamento confirmado pelo lider no jogo.
  Taxa do cla so vira entrada livre quando o evento for encerrado e conciliado.

### 7. Apostas — em espera de verificacao das regras
- Usuario pediu duas modalidades: vencedor de uma partida e campeao do torneio,
  ambas com configuracao do valor pelo Admin antes de abrir.
- Se forem legalmente e contratualmente permitidas, definir fundo separado,
  comprovacao de pagamentos, abertura/fechamento, regras de anulacao, ausencia de
  vencedores, percentual do cla congelado, calculo proporcional e recibo.
- **Nao ativar apostas com valor apostado/premiacao sem antes verificar regras do
  servidor e conformidade legal**, inclusive conversibilidade da moeda virtual.

## Ordem de implementacao segura
1. Criar branch, migrations isoladas e testes; sem deploy automatico.
2. Isencao historica, prestacao de contas somente leitura e sorteio nao destrutivo
   (primeiros componentes preparados nesta branch).
3. Criar livro-razao transacional com RPCs atomicas, conciliacao financeira e
   rotinas de auditoria; depois montar Carteira e Repasses.
4. Integrar inscricoes e premios aos fluxos de eventos/torneios existentes;
   apresentar chaveamento e fotos nos detalhes.
5. Criar Conselho com votos consultivos e aprovacao final do lider.
6. Validar regras de apostas antes de codificar/ativar esse modulo.

## Invariantes para validacao
- Nenhuma movimentacao do dinheiro real ou do Minecraft e inventada.
- Lancamentos financeiros nao podem ser editados/excluidos: retificar por estorno.
- Chave idempotente por evento de negocio, bloqueio de concorrencia e transacao unica
  no banco para credito/debito/alteracao do estado.
- Isolamento entre carteira, fundo de evento, repasse e receita do cla.
- CSRF, login, permissao por papel, restricao de membro ativo, logs e backup
  verificados antes de migracao/merge.
- Testar em banco de homologacao e revisar o diff antes de publicar no Render.

## Status atual da branch
- [x] Codigo inicial de isencao de comissoes + formulario + migracao SQL.
- [x] Economia do Cla: consulta somente leitura dos valores confirmados no caixa.
- [x] Sorteio de chaveamento aleatorio com BYEs distribuidos, sem apagar chave existente.
- [ ] Aplicar migracao e validar constraints reais do Supabase.
- [ ] Executar testes integrados com banco de homologacao.
- [ ] Implementar carteira, repasses, compras, votos, inscricoes e premios.
- [ ] Validar regras e elegibilidade do recurso de apostas.
- [ ] Revisao e merge; **nenhuma alteracao em producao nesta etapa**.
