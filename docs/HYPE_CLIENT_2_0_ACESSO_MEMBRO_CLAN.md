# HYPE Client 2.0 — acessos por grupo

Esta atualização separa **cadastro**, **membro básico** e **integrante do Clã HYPE**.

## Regras

| Conta | Cargo em usuarios_clan | membros_hype.ativo | Grupos disponíveis |
|---|---|---|---|
| Cadastro novo | visitante | false | nenhum |
| Membro básico aprovado | membro | false | membro |
| Integrante ativo do clã | membro ou cargo interno | true | membro, membro_hype, e o próprio cargo (quando aplicável) |

- Módulos com estado `desativado` ou `manutencao` sempre ficam bloqueados.
- Para funcionar, cada módulo precisa estar globalmente **ativo** e ter uma atribuição de grupo.
- Módulos atribuídos apenas ao grupo `membro` são acessíveis a membros básicos e membros HYPE.
- Módulos atribuídos ao grupo `membro_hype` (mas **não** `membro`) são exclusivos do clã; liberação individual não contorna a exigência de pertencer ao clã.
- Módulos concedidos a ambos os grupos são compartilhados.
- Um visitante permanece sem acesso a módulos, inclusive com liberação individual.
- Permissões individuais temporárias continuam disponíveis a contas aprovadas, respeitando exclusividade do clã e desligamento global.
- O site nunca passa chaves Supabase ao cliente Minecraft.

## Uso no site

1. Novo registro em /login cria uma conta com cargo visitante (sem acesso a mods).
2. Em **Administração > Cargos** (/admin/cargos), trocar `visitante` para `membro` torna a conta **membro básico**, sem admitir automaticamente no clã.
3. Em **Administração > Membros HYPE** (/admin/membros), **Adicionar ao clã** ativa `membros_hype.ativo`; **Remover do clã** retira o status HYPE e preserva a conta como membro básico.
4. Em **Administração > Gerenciador de Módulos** (/admin/modulos), escolha o grupo `membro` para módulos básicos e `membro_hype` para módulos exclusivos. Marque cada módulo como **Ativo**.
5. Se for necessário bloquear absolutamente o usuário, altere seu cargo para `visitante`.

**Atenção:** esta migração é apenas de código. Nenhum registro existente é promovido, desativado ou excluído automaticamente. Integrantes HYPE já ativos continuam ativos até uma alteração administrativa.

## Segurança do servidor

O endpoint /api/hype/v1/modulos informa a decisão de acesso de cada conta. Os endpoints de leitura de Breed (/meus-pedidos, /fila, /painel-breeder, /team-breeders e /ranking) agora validam **também** a permissão do módulo `breeder` no servidor antes de retornar dados.

**Pendente no Minecraft:** os recursos puramente locais (Pokédex offline, Detector de Ovos etc.) ainda precisam de verificação própria no código do .jar. Mudar só o site não impede que um cliente antigo execute funcionalidades locais. Para garantir bloqueio efetivo das ferramentas locais, atualizar o HYPE Client 2.0 para usar /modulos e falhar fechado, incluindo rechecagem periódica e saída segura dos módulos.
