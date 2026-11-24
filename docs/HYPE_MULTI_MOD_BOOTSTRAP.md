# HYPE — instalador universal de mods (arquitetura e etapa 1)

## Objetivo

O jogador instala o Fabric Loader e coloca somente o HYPE Client bootstrap
na pasta de mods. Na primeira inicialização, o bootstrap deverá consultar um
catálogo oficial assinado, baixar as dependências e os mods HYPE e preparar a
instalação para a próxima inicialização do Minecraft. Depois, baixa somente
os mods alterados e também atualiza o próprio bootstrap. O usuário não terá
de substituir manualmente os arquivos.

O administrador envia JARs originais privados pelo site. Um processador
isolado, ainda não implementado, criará cópias ofuscadas com regras específicas
por mod. Só builds protegidos, testados, aprovados e publicados poderão ser
distribuídos. Upload nunca equivale a publicação.

## Estado real

- Existente: inspeção Fabric, staging privado, vínculo manual de candidatos,
  aprovação e distribuição assinada somente do HYPE Client.
- Etapa 1 (neste PR): contrato JSON de catálogo multi-mod, verificação
  de assinatura Ed25519, hashes, URLs e dependências internas; endpoint
  somente leitura e desativado por padrão.
- Etapa 2 (pendente): releases independentes por mod e download privado
  de JARs aprovados por URLs imutáveis, com rollback.
- Etapa 3 (pendente): worker de proteção isolado, com regras de Mixins,
  entrypoints, reflexão, recursos e falha fechada antes da publicação.
- Etapa 4 (pendente): novo bootstrap Java que inicia com Fabric Loader sem
  exigir Cobblemon nem Fabric API antes de baixá-los, valida assinatura
  e SHA-256, resolve dependências, salva downloads atomicamente e preserva
  mods não gerenciados e mudanças manuais dos jogadores.
- Etapa 5 (pendente): autoatualização segura do próprio Client,
  backup e rollback. Mods Fabric novos só carregam no próximo início do jogo.
- Etapa 6 (pendente): testes completos de instalação limpa,
  interrupção de rede, JAR inválido, conflito de versões e recuperação.

Dependências externas como Fabric API e Cobblemon exigem política específica
de origem, licença, versão e compatibilidade. Não se deve republicar mods
de terceiros indiscriminadamente.

## Contrato de catálogo V1 (apenas homologação)

URL planejada: GET /hype-updates/mods/catalog.json

Este endpoint está desativado por padrão. Requer a flag de ambiente
HYPE_MULTI_MOD_CATALOG_ENABLED=1 e o arquivo
HYPE_UPDATES_DIR/mods/catalog.json, criado e assinado previamente.
Sem arquivo retorna 404; assinatura inválida retorna 503.
Não afeta o manifesto legado do HYPE Client e não serve JAR algum.

Envelope JSON exato:
- schema: inteiro 1
- minecraft: string 1.21.1
- channel: string stable
- mods: lista de objetos contendo id, version, sha256, size, url,
  required (booleano) e depends_on (lista de IDs HYPE internos)
- signature: assinatura Ed25519 codificada em Base64

Para a assinatura, retirar signature do objeto, serializar JSON com
sort_keys=True, separators=(",", ":"), ensure_ascii=True,
codificar como ASCII e assinar esses bytes. O validador usa a
chave pública já fixada no atualizador existente; a chave privada
nunca deve entrar no site, no repositório ou em um JAR.

Formato obrigatório das URLs:
https://clan-hype.onrender.com/hype-updates/mods/{id}/{sha256}.jar

Etapa 2A (piloto): o endpoint de download individual agora existe no código,
mas está **desativado por padrão** e separado da publicação/atualizador legado.
Requer simultaneamente `HYPE_MULTI_MOD_CATALOG_ENABLED=1` e
`HYPE_MULTI_MOD_DOWNLOADS_ENABLED=1`. Busca JARs somente em
`HYPE_UPDATES_DIR/mods/{id}/{sha256}.jar`, quando presentes no catálogo
assinado e com tamanho e SHA-256 exatos. Não permite upload nem acesso aos
originais/candidatos privados. O diretório do piloto local é manual. O backend de leitura persistente em
Supabase está preparado opcionalmente (abaixo), mas ainda depende de
configuração segura, aprovação dos artefatos e testes ponta a ponta. Nenhum JAR é disponibilizado
sem as duas flags e o catálogo assinado válido.

ATENÇÃO: o piloto NÃO implementa o cadastro de releases por mod, controle
de acesso individual, permissões do painel, download de dependências externas,
ofuscação ou instalação automática; **não habilitar em produção** até essas
etapas estarem validadas. URLs do catálogo são públicas por design: mods
restritos por permissão exigirão autorização antes da publicação.
O catálogo público assinado aceita IDs novos de mods sem modificar uma lista
fixa no site (nomes seguros, até 128 entradas por catálogo). Isso **não torna
públicos** os originais enviados ao staging privado. Somente JARs de
distribuição aprovados e incluídos num catálogo assinado offline podem ser
servidos. A distribuição continua desligada por padrão; habilitar somente
após conferir o conteúdo público, URLs imutáveis e integridade dos JARs.

Não ativar a flag em produção nem anunciar downloads a jogadores
até haver arquivos oficiais protegidos, URLs válidas e bootstrap
Java compatível. O cliente instalado atualmente NÃO lê esse catálogo.

## Critérios de liberação

1. JAR protegido aprovado de cada mod, hash e URL imutável.
2. Catálogo assinado com chave que o bootstrap conhece e verifica.
3. Instalação inicial, atualização incremental e dependências testadas.
4. Autoatualização do próprio bootstrap com backup/rollback aprovado.
5. Integridade validada pelo cliente (não somente pelo servidor).
6. Compatibilidade Fabric/Cobblemon, ausência de conflito com mods alheios.
7. Aprovação explícita no site antes de qualquer publicação.

## Etapa 2B — armazenamento persistente assinado (implementado no código; DESLIGADO)

A partir desta PR, o site pode ler um catálogo e JARs de distribuição
de um bucket **novo e privado**, exclusivo para artefatos finais aprovados:

- Bucket Supabase: `hype-mod-distribution` (**public=false**).
- Catálogo: `stable/1.21.1/catalog.json`.
- JARs: `stable/1.21.1/mods/{id}/{sha256}.jar`.
- Flag para usar Supabase em vez do diretório local:
  `HYPE_MULTI_MOD_PUBLIC_STORAGE_ENABLED=1`.
- Também exige `HYPE_MULTI_MOD_CATALOG_ENABLED=1` e, para servir
  JARs, `HYPE_MULTI_MOD_DOWNLOADS_ENABLED=1`.

Mesmo com as flags ligadas, **nenhum** arquivo do bucket
`hype-mod-originals` ou da fila privada é disponibilizado por essas
rotas. O servidor verifica que o bucket de distribuição é privado,
valida assinatura Ed25519 do catálogo, pertença ao catálogo, tamanho
e SHA-256 de cada arquivo antes de responder ao Bootstrap.

A chave privada de assinatura deve permanecer **fora** do site e do
repositório: não inserir chaves privadas em variáveis de ambiente
web/Render ou em códigos cliente. Upload de original não cria release
nem altera o catálogo. A publicação deve ser um passo distinto,
**atômico quanto ao catálogo**: primeiro disponibilizar e conferir todos
os JARs finais; somente depois substituir o objeto assinado
`catalog.json`. A versão anterior do catálogo deve poder ser restaurada.

A distribuição acima ainda depende de **criar e configurar o bucket
privado**, gerar JARs protegidos, concluir revisão e assinatura externa,
preencher os objetos e passar nos testes de rede e Minecraft. Não ativar
as três flags antes desses passos. O Render não deve depender de disco
efêmero para servir arquivos oficiais.

## Novos mods enviados — sem whitelist fixa no staging

Agora a análise privada de JARs aceita identificadores Fabric seguros
compatíveis com `[a-z][a-z0-9_]{1,63}`, com exceção do identificador
reservado `hypebootstrap`. O registro e a fila de proteção usam o
mesmo validador. Os nomes amigáveis antigos continuam apenas para
exibição; um ID novo recebe o nome de `fabric.mod.json`.

Após revisão, aplicar **somente a migração revisada**
`migrations/20261124_hype_dynamic_mod_ids.sql`, no momento coordenado
com o deploy do código. Ela troca as CHECK constraints **somente**
em `hype_mod_release_drafts` e `hype_mod_protection_jobs`.
Não altera as regras de autorização dos módulos restritos nem publica
automaticamente qualquer JAR.

### Bloqueios restantes para o resultado pedido pelo proprietário

1. Processar a fila real de proteção em worker isolado (há jobs aguardando);
   teste estático ou renomeação não equivalem a ofuscação.
2. Registrar aprovação manual por SHA exato, compatibilidade de Fabric e
   permissão de distribuição antes de publicar.
3. Produzir e assinar externamente o catálogo para a chave Ed25519 fixada
   no Bootstrap 1.4 (ou coordenar uma rotação de chave, se necessária).
4. Preencher o bucket `hype-mod-distribution`, testar entrega
   dos JARs e só então habilitar flags no Render.
5. Validar o Bootstrap em Minecraft 1.21.1 / Fabric 0.19.5 no launcher
   Planeta: nova instalação, atualização, queda de rede e rollback.

O jogador não precisa fazer login para baixar **releases públicas**.
Módulos privados/restritos continuam exigindo a política de acesso
correspondente; não liberar seus originais como atalho para eliminar login.
