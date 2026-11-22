# HYPE — permissões obrigatórias na distribuição de mods (piloto)

## Regra fundamental

**Atualizar um mod NÃO altera suas permissões.** O admin continua controlando
`hype_modulos.estado` (ativo/manutencao/desativado), `visivel`,
`hype_modulos_grupos` (cargos) e `hype_modulos_acessos` (permissões individuais
com datas). A publicação e o download de JARs são um fluxo separado.

O arquivo Fabric usa identificadores diferentes dos códigos de módulo no site:

| Mod no catálogo | Código de controle no site |
| --- | --- |
| hype_pokedex | pokedex |
| hype_breed_calculator | breed_calculator |
| hype_battlefield | campo_batalha |
| hype_battle_ai | battle_ai |

`hypeclient` é o bootstrap obrigatório e **não** autoriza automaticamente nenhum
módulo restrito.

## Política que as novas rotas deverão cumprir

1. Autenticar a conta do jogador **no backend** e consultar a filiação ativa,
   o cargo atual, o estado do módulo e as liberações/bloqueios individuais.
2. Resolver cada ID Fabric por um mapeamento fixo mantido no servidor.
   IDs desconhecidos, ausentes ou inconsistentes devem ser negados.
3. `manutencao` e `desativado` bloqueiam o módulo para todos, mesmo com
   liberação individual. Um módulo oculto não pode ser distribuído.
4. Respeitar cargos, exclusividade do clã, bloqueios individuais e intervalos
   de vigência. Reavaliar **antes de cada entrega** e ao ativar funcionalidades
   restritas no servidor. Falhas de consulta significam acesso negado.
5. Catálogos de teste e URLs públicas não podem dar acesso a JARs restritos.
   Entregas privadas exigem autenticação e autorização vinculadas à conta,
   não apenas assinatura de catálogo. Não usar links públicos permanentes,
   redirects ou caching público para os JARs com controle de acesso.
6. A instalação após sair do Minecraft só pode aplicar builds aprovados
   e autorizados e não pode remover nem conceder cargos ou privilégios.
7. Downloads já obtidos não podem ser revogados do computador de alguém:
   para **parar** uma função em manutenção é indispensável consultar o estado
   no servidor no uso (ou manter a lógica protegida no backend). Funções
   inteiramente offline não podem ser desativadas com garantia por um site.

## Estado da implementação nesta PR

- `modules/hype_mod_update_access.py` reutiliza a regra já existente do
  site em vez de criar uma nova lógica de permissões.
- Os endpoints públicos experimentais de multi-mod ficam impedidos de servir
  um catálogo que anuncie mods restritos e JARs restritos, mesmo se as duas
  flags experimentais forem habilitadas por engano.
- **Ainda falta** implementar o catálogo por conta, a rota autenticada para
  downloads, a integração Bearer no Bootstrap, a aplicação em jogo e os testes
  ponta a ponta. As flags de distribuição devem continuar desligadas.

## Testes obrigatórios para liberar

Sem login; cargo negado; membro inativo; bloqueio por usuário; liberação
individual válida/expirada; invisível; manutenção; desativado; erro no banco;
alteração de cargo durante o download; troca de sessão; conflito com JAR local;
revogação após download; atualização e rollback sem alterar permissões.

**Não publicar para jogadores antes de homologar esses testes.**
