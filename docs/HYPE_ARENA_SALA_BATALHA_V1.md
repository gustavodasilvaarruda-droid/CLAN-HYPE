# HYPE Arena — Sala de Batalha: ativação segura

## Situação
- A interface da Sala de Batalha (PR #19) já foi publicada no site oficial.
- Esta alteração corrige o backend, ainda **não implantado em produção**.
- O banco oficial ainda não tinha a tabela `hype_batalha_participantes`
  na última verificação. Não executar mudanças em resultados antigos.

## Segurança e regras
- Participantes autenticados podem confirmar presença e informar resultado
  somente se o torneio estiver `em_andamento`, com dois competidores.
- A partida só é finalizada se **ambos confirmarem a mesma vitória**.
- O SQL usa `SELECT ... FOR UPDATE` para impedir corrida entre envios;
  as permissões da tabela e RPCs são restritas à role `service_role`.
- Chave `SUPABASE_SERVICE_ROLE_KEY` é necessária exclusivamente no backend;
  nunca colocá-la em HTML, JavaScript, repositório ou conversa.
- Sem chave ou tabela, a tela permanece de consulta e bloqueia confirmações.
- Divergências não encerram a partida: o admin revisa no chaveamento.
- Não existe movimentação automática de moedas, apostas, pagamentos
  nem avanço automático de rodada nesta etapa.

## Checklist de ativação
1. Revisar o PR e verificar que os testes GitHub Actions estão verdes.
2. Executar `supabase/migrations/20261104_hype_sala_batalha.sql`
   **primeiro em um projeto Supabase de teste**, confirmar RLS e RPCs.
3. Testar duas contas distintas em torneio fictício (presença, mesma vitória,
   vitória divergente, usuário externo, simultaneidade, torneio cancelado).
4. Conferir que a chave `SUPABASE_SERVICE_ROLE_KEY` está configurada
   como secret no Render, sem expor seu valor.
5. Após validar, aplicar migração em produção, revisar serviço e publicar o PR.
6. Repetir dois cenários controlados no site e conferir registros.
7. Só então integrar rankings, fechamento de rodadas e eventos de apostas.

A confirmação esportiva não libera pagamentos financeiros.
