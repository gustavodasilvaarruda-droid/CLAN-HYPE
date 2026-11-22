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
- A rota experimental `GET /api/hype/v1/updates/authorized-mods` reutiliza o
  **Bearer já autenticado pelo HYPE Client**, lê as permissões atuais do banco
  e retorna **somente IDs permitidos**, sem URLs, hashes ou JARs. A flag
  `HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED` é **OFF por padrão**.
- Cada consulta busca novamente o cargo, a filiação ativa, os estados dos
  módulos, os grupos e os bloqueios individuais. Falha no banco resulta em
  erro de serviço, nunca em liberação parcial.
- A migration sql/20261122_hype_mod_restricted_releases.sql prepara uma tabela
  SEPARADA e privada para os quatro mods restritos (sem executar o SQL).
- O verificador modules/hype_mod_private_releases.py valida assinatura Ed25519,
  hash e a aprovação estática/manual vinculada ao candidato protegido exato.
- GET /api/hype/v1/updates/releases lista releases autorizadas e assinadas.
- GET /api/hype/v1/updates/mods/{id}/{sha256}.jar entrega bytes do Storage
  privado apenas após autenticação e autorização, sem cache público ou redirect.
  Cargo e filiação são revalidados antes de responder, mesmo após ler o JAR.
- Ambas as rotas são OFF por padrão: exigem simultaneamente as flags
  HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED e HYPE_PRIVATE_MOD_DOWNLOADS_ENABLED.
  Nenhum JAR foi cadastrado ou publicado por estas rotas, e nenhuma flag foi
  ativada. A migração SQL também não foi executada no Supabase.
- AINDA FALTA: publicação administrativa com assinatura offline, upload
  de originais/candidatos privados, validar a migração em homologação,
  conectar o token Bearer no Bootstrap, verificar o manifesto no lado Java,
  instalar após sair do Minecraft, rollback e testes completos de segurança.

## Piloto da Pokédex Beta 8

O proprietário informou em 22/11/2026 que a Pokédex Beta 8 protegida
funcionou no Minecraft. Trata-se de teste manual informado pelo proprietário,
não de homologação integral e nem de autorização para publicar.

- Fabric mod ID: hype_pokedex
- Versão: 2.0.0-beta.8-defesas-multiplas-colecao-compacta-20261109
- SHA-256 protegido: 176819c73facf52da2826ba3ac1d179926670d64f10c6e92923ccefa65f5ca18
- Originais e builds protegidos permanecem privados; nunca colocar JAR
  original no repositório ou em URL pública.
- Para publicar: upload no Storage privado, revisão automática e manual
  para esse SHA, aprovação humana, assinatura offline, teste de download
  autenticado em homologação e só então autorização final do administrador.

## Testes obrigatórios para liberar

Sem login; cargo negado; membro inativo; bloqueio por usuário; liberação
individual válida/expirada; invisível; manutenção; desativado; erro no banco;
alteração de cargo durante o download; troca de sessão; conflito com JAR local;
revogação após download; atualização e rollback sem alterar permissões.

**Não publicar para jogadores antes de homologar esses testes.**
