# Bootstrap 0.8 — revalidação privada pós-fechamento (código experimental)

**NÃO DISTRIBUIR / NÃO ATIVAR NO CLÃ.**

A biblioteca `PrivateAuthorizedPostExit` foi acrescentada ao ramo experimental
que depende dos pilotos 0.6 e 0.7. Ela é uma etapa intermediária **e ainda não
é um atualizador automático funcional**: não existe aqui um executor externo
testado iniciando sozinho após o fechamento do Minecraft.

## O que foi implementado

1. Exige `update_mode=after_exit`, uma sessão temporária em memória e confirmação
   fornecida pelo agente de que o Minecraft terminou.
2. Verifica o manifesto Ed25519 e usa apenas releases dos quatro mods privados.
3. Antes de cada instalação e durante cada transação, consulta novamente
   `GET /api/hype/v1/updates/releases` com o Bearer de sessão; confere módulo,
   release, versão, SHA-256, tamanho, URL e manifesto idênticos.
4. Se o site negar acesso, a sessão expirar, a rede cair ou a release mudar,
   interrompe sem usar um catálogo offline como permissão.
5. Encaminha apenas primeira instalação ao `PrivateFirstInstallTransaction`
   e apenas JARs com marcador de propriedade à rotina `PrivateManagedUpgrade`.
   Mods instalados manualmente não são assumidos nem sobrescritos.
6. O código não contém chave privada, não publica original sem proteção e
   não escreve token no disco.

## Teste isolado

`PrivateAuthorizedPostExitTest.java` fornece um catálogo temporário assinado
com chave descartável e verifica bloqueio com Minecraft aberto, token ausente,
releases duplicadas, revogação, primeira instalação, repetição sem alteração
e modo OFF. O teste **não** acessa site real, não inicia Minecraft nem confirma
as dependências dos mods em execução.

Para compilar, use Java 21, o piloto 0.6 e as classes base do Bootstrap 0.4
(`CatalogVerifier` e `JsonCodec`) conforme os READMEs dos pilotos anteriores.
Ainda falta executar e homologar este teste na cadeia de build completa.

## Pendências para o usuário

- Criar e testar um agente externo que aguarde o encerramento do processo real
  do Minecraft, sem salvar Bearer no disco ou na linha de comando; validar a
  identidade do processo para evitar troca de PID.
- Ligar a ponte de login do HYPE Client ao download autenticado e ao agente
  externo, com cancelamento por logout e expiração.
- Incluir essas classes no JAR final do Bootstrap para Windows / Fabric 1.21.1 /
  Java 21 e testar uma instância separada. Não substituir JAR durante execução.
- Resolver o canal público assinado independente de atualização do próprio
  Bootstrap e do HYPE Client.
- Testar autorização real da API, os quatro mods verdadeiros, backup, rollback,
  desligamento inesperado, conflito com mods manuais e recuperação antes de
  iniciar o Fabric.
- Submeter JAR protegido, testar, aprovar e assinar as releases na Central HYPE.
  Não ativar downloads ao clã até concluir toda a homologação.

Este piloto não muda variáveis no Render e não muda o site em produção.
