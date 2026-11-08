# Organização de cargos e filiação — CLAN HYPE

**Membro do servidor**: toda conta cadastrada recebe o cargo membro, com acesso a solicitações de Breed, seus pedidos e inscrição em torneios abertos. **Membro HYPE**: filiação registrada somente em membros_hype.ativo; é independente do cargo. Breeder, Sub-Líder, Líder e cargos personalizados exigem filiação ativa.

A migração SQL está em sql/20261108_membros_servidor_hype_migracao.sql. Ela:
- corrige o padrão de cadastro para membro;
- remove gatilhos que forçavam visitante e ativavam HYPE após alteração de cargo;
- converte apenas os visitantes em membros comuns, sem tocar no vínculo HYPE;
- torna o valor padrão de membros_hype.ativo igual a falso.

## Procedimento de publicação

1. Confirmar backup restaurável do Supabase e conferir contagens antes da migração.
2. Publicar o código do PR em conjunto com a migração SQL. Evitar janela com versões divergentes, pois o gatilho antigo ainda concede HYPE após alteração de cargo.
3. Conferir as contagens de filiações HYPE ativas antes e depois: não podem aumentar apenas pela conversão de visitantes.
4. Testar inscrição em torneio com conta básica, criar pedido Breed, consultar Meus Pedidos, permissões administrativas, acesso a mods, entrada e saída explícitas do clã.
5. Verificar individualmente os quatro Breeders com cargo especial mas sem filiação ativa, sem admiti-los automaticamente.
6. Não excluir o registro cargo membro_hype enquanto o Detector de Ovos usa o identificador virtual nos grupos de mods.

## Reversão

Se uma implantação falhar, restaurar o código para o commit anterior e usar backup validado para dados. **Não restaurar o gatilho de promoção automática** sem revisão, pois ele pode admitir jogadores no clã ao alterar cargo. Não executar remoção de integrante apenas para testes em produção.
