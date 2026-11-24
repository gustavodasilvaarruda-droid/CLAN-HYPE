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
originais/candidatos privados. O diretório do piloto é manual e a persistência
em Render/Supabase ainda precisa ser implementada. Nenhum JAR é disponibilizado
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
