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

ATENÇÃO: esses endpoints de download dos mods ainda NÃO existem.
O validador está limitado aos cinco IDs já presentes no staging:
hypeclient, hype_pokedex, hype_breed_calculator, hype_battlefield,
hype_battle_ai. Outros IDs devem ser cadastrados e testados.

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
