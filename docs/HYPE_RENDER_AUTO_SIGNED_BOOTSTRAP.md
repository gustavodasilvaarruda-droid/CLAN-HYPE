# Assinatura automática HYPE na Render — piloto controlado

## Objetivo
O proprietário envia um único JAR Fabric do HYPE Client em **Admin > Módulos > Releases**.
O arquivo fica no bucket privado `hype-mod-originals`; depois da ativação **explícita**
do canal de distribuição, o Bootstrap consulta um catálogo Ed25519 assinado
pelo servidor e pode baixar o JAR pelo SHA-256.

## Segredo
Variável privada da Render: `HYPE_AUTO_SIGNING_PRIVATE_KEY_PEM_B64`, contendo
o PEM PKCS#8 codificado em Base64. Nunca colocar o PEM ou seu Base64 em
GitHub, logs, documentação, templates, SQL, JS ou cliente. O backend compara
a chave pública derivada com a chave já fixada no Bootstrap antes de assinar.

## Chaves de ativação (ambas devem ser verdadeiras)
- `HYPE_AUTO_SIGNED_CATALOG_ENABLED=1`
- `HYPE_AUTO_SIGNED_DOWNLOADS_ENABLED=1`

**Padrão: desligado.** Com qualquer chave de ativação ausente ou diferente
de `1`, as rotas usam o comportamento antigo, que não publica uploads.

## Restrições deste piloto
- Somente JARs com Fabric ID `hypeclient` enviados pelo formulário único
  e que continuem elegíveis na biblioteca. Rejeitados e registros de piloto
  antigos não entram no catálogo.
- O catálogo é público e só inclui HYPE Client. Não habilitar módulos
  restritos (Pokédex etc.) na mesma URL pública sem avaliar autorização.
- Para evitar vazamento acidental, a assinatura não é ativada somente ao
  configurar o segredo. Os dois controles ficam desligados até um teste
  completo do Bootstrap, com jogo aberto e fechado, backup, rollback e
  substituição pós-fechamento.
- O upload pode repetir o número de versão. Verificar que o Bootstrap
  compara o SHA-256 e não apenas a string de versão.
- Não usar diretório efêmero da Render para armazenar os JARs. O endpoint
  lê do bucket privado e valida o conteúdo antes de entregá-lo.
- A chave privada compartilhada anteriormente no chat deve ser considerada
  exposta. Planejar rotação posterior, preferencialmente junto com uma
  versão de Bootstrap que aceite chave pública substituta.

## Verificações
`python -m unittest tests.test_hype_auto_signed_catalogue -v`.
Depois, testar manualmente catálogo assinado, URL do binário e Bootstrap
isolado antes de liberar para todos.
