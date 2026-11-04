# HYPE Arena — Sala de Batalha (primeira etapa)

Status: branch de desenvolvimento; não publicado no site oficial.

## Entregue na branch
- Rota pública por confronto: `/torneios/<torneio_id>/batalha/<partida_id>`.
- Link direto pelo chaveamento público e administrativo.
- Interface responsiva preta/dourada, jogadores com avatar/nick, presença e vencedor.
- Somente integrantes reais da partida podem marcar `Estou pronto` ou enviar o resultado.
- A finalização automática de uma partida requer os dois prontos e os dois
  apontando o mesmo vencedor. Divergências ficam para revisão administrativa.
- Reutiliza a tabela `partidas_torneio`, incluindo o resultado já publicado.
- Proteção CSRF já existente em `app.py`, histórico e aviso ao vencedor.

## Passos antes de ativar em produção
1. Revisar código/fluxo via Pull Request sem fazer merge.
2. Executar a migração `supabase/migrations/20261104_hype_sala_batalha.sql`
   primeiro num ambiente de testes. O backend Flask precisa de chave Supabase
   apropriada para acessar a tabela protegida por RLS.
3. Rodar os testes automáticos e validar a sala com duas contas de teste.
4. Avaliar os impactos sobre apostas e chaveamento: o MVP NÃO encerra apostas,
   NÃO movimenta moedas, e NÃO gera sozinho a rodada seguinte. A organização
   ainda deve clicar no comando já existente para criar a próxima rodada.
5. Só publicar após aprovação do responsável pelo site.

Ações de administrador para correção de resultado continuam no painel de
chaveamento existente. Antes de vincular apostas reais, criar uma camada de
aprovação financeira separada da confirmação esportiva.
