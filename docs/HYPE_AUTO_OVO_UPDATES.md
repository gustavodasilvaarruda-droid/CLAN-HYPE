# Auto Ovo HYPE — fase 1 do canal de atualizações (não habilitado)

Este canal atende **somente** ao mod Fabric MoreCobblemonTweaks-HYPE,
ID de Fabric \`more_cobblemon_tweaks\`, versão analisada \`1.3.3+hype.19\`
(Minecraft 1.21.1, Java 21, Cobblemon >=1.7). Não altera nem distribui
novas versões do **HYPE Client R7.17**.

## Rotas preparadas

- \`GET /hype-updates/auto-ovo/health\` — retorna \`manifest_present: false\` antes de publicar manifesto.
- \`GET /hype-updates/auto-ovo/manifest.properties\` — somente entrega
  o manifesto local se existir. Caso contrário, HTTP 404.
- \`GET /hype-updates/auto-ovo/releases/hype-auto-ovo-hN.jar\` —
  permite apenas nomes dessa família; entrega JAR local ou HTTP 302 para
  armazenamento HTTPS externo especificamente configurado.

O canal é **somente leitura**: não recebe upload, não altera Supabase, não
assina e não gera atualizações. Nenhuma mudança automática ocorrerá a partir
desse servidor isoladamente.

## Estrutura de publicação

O diretório padrão é \`hype-updates/auto-ovo/\` dentro do projeto Flask
(ou \`<HYPE_UPDATES_DIR>/auto-ovo/\` se esta variável já estiver definida):

\`\`\`
auto-ovo/
  manifest.properties      # NÃO criar até concluir cliente, assinatura e testes
  releases/
    hype-auto-ovo-h20.jar  # exemplo de futuro JAR homologado
\`\`\`

Opcionalmente, a variável
\`HYPE_AUTO_OVO_RELEASE_BASE_URL=https://github.com/USUARIO/REPO/releases/download/auto-ovo-updates\`
faz somente redirecionamento para nomes permitidos quando o arquivo não existir localmente.
**Essa variável não é a mesma do atualizador do R7.17.**

## Antes de publicar um manifesto

1. Obter o **código-fonte Gradle/Java** da versão HYPE h19 e acrescentar o
   verificador no cliente (ou criar bootstrap separado com segurança).
   O JAR h19 analisado tem apenas bytecode, sem código-fonte da adaptação HYPE.
2. Definir esquema de manifesto versionado com assinatura digital Ed25519, chave
   pública fixa no cliente, ID \`more_cobblemon_tweaks\`, compatibilidade Fabric,
   versão monotônica, tamanho e SHA-256 do arquivo.
3. Guardar a chave privada exclusivamente offline. Verificar assinatura ANTES
   de confiar na URL, SHA-256 ANTES de instalar, impedir downgrades e não aceitar
   URLs de atualização arbitrárias.
4. Baixar e preparar arquivo temporário, mantendo backup da versão funcional.
   **Não substituir o JAR com o jogo executando.** Aplicar em fase segura entre
   inicializações, sem instalar duplicatas do mesmo mod e com rollback.
5. Testar em Minecraft real no Windows, Fabric 1.21.1, Cobblemon instalado e
   vários cenários: offline, HTTP com redirecionamento, arquivo incompleto,
   falha de assinatura, hash errado, atualização correta e recuperação.
6. Implantar gradualmente apenas após homologação e autorização do dono.

### Estado atual

- Back-end: estrutura de distribuição criada, inativa sem manifesto.
- Painel admin de upload/publicação: ainda **não** implementado.
- Cliente atualizador: ainda **não** implementado para o Auto Ovo.
- HYPE Client R7.17: não modificado.
- Mod Auto Ovo h19: não modificado.

## Testes

\`python -m unittest tests.test_hype_updates -v\`.
