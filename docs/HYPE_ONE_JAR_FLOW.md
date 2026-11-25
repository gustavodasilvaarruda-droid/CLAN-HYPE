# HYPE — Envio único de JARs

## Biblioteca no site
A Central de Publicações do proprietário tem agora **um único formulário de envio**.
O usuário autorizado escolhe um `.jar` Fabric (original ou ofuscado, sem rótulo
obrigatório). O servidor verifica estrutura ZIP, CRC, `fabric.mod.json`, tamanho e
SHA-256, salva os bytes no bucket privado e agrupa os registros pelo ID do Fabric.
Vários arquivos para o mesmo ID/versão permanecem disponíveis sem sobrescrita.
Não há status de proteção, análise de classes, fila ou etapas de publicação visíveis.

### Ação atual
- **Enviar JAR:** guarda na biblioteca do mod. Nenhuma substituição automática é iniciada.
- **Baixar:** devolve o arquivo privado exato ao administrador, com verificação SHA-256.
- Os endpoints antigos de publicação e os direitos de acesso foram preservados no
  backend para compatibilidade, mas não aparecem mais na tela simplificada.

## Contrato do Bootstrap 1.4 enviado pelo proprietário
O JAR `hypebootstrap` versão `1.4.0-fabric-abi-hotfix` consulta
`https://clan-hype.onrender.com/hype-updates/mods/catalog.json` em segundo plano.
Ele **exige** uma assinatura Ed25519 sobre o catálogo, SHA-256 por arquivo,
URLs oficiais e o ID `hypeclient` obrigatório. O instalador adia a troca até
o Minecraft fechar, fazendo staging e cópias de segurança.

### Por que apenas o upload ainda não atualiza o cliente
No código atual, `/hype-updates/mods/catalog.json` é servido apenas se
`HYPE_MULTI_MOD_CATALOG_ENABLED` estiver habilitado **e** houver um JSON
pré-assinado válido no diretório de distribuição. Uploads privados não geram
esse JSON. A chave privada correspondente à pública fixada no Bootstrap **não
está no repositório**, e não é possível assinar usando apenas a chave pública.

Antes de prometer "enviei um JAR e todos receberam a atualização", é preciso
implantar uma etapa de assinatura confiável do catálogo (com gestão de chave
aprovada), resolver o storage persistente e ligar o catálogo aos JARs salvos.
Não habilitar endpoints de download/catálogo só para eliminar o HTTP 404:
o Bootstrap rejeitaria uma assinatura ausente, falsa ou incompatível.

## Para completar a automação numa etapa separada
1. Configurar um assinador confiável compatível com a chave **já fixada** no
   Bootstrap (ou distribuir uma nova versão manual com outra chave).
2. Construir catálogo canônico com números de release, dependências e URLs
   imutáveis; servir apenas artefatos verificados, protegendo os canais restritos.
3. Testar o download incremental, erro de rede, corrupção, backup e substituição
   somente com o jogo fechado antes da liberação aos jogadores.

O repositório **não** armazena chaves privadas e esta mudança não ativa
atualizações nem distribui JARs aos jogadores.
