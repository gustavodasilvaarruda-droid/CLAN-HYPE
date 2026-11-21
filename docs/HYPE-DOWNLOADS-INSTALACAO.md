# Central de downloads de mods HYPE (primeira etapa)

## O que esta entrega inclui
- Página autenticada `/mods` com links de download de versões publicadas.
- Área administrativa `/admin/modulos/publicacoes` com upload de JAR FINAL, rascunho, publicação e suspensão.
- Bucket Supabase *privado* para JARs de distribuição (separado de `hype-mod-originals`, que guarda originais).
- Catálogo autenticado `GET /api/hype/v1/atualizacoes-hype` e download por token via `/api/hype/v1/atualizacoes-hype/<id>/download`.
- Respeita permissões do painel HYPE para submódulos (sem autorização, nenhum download).
- Revalidação SHA-256 do JAR antes de entregar os bytes.

## Requisitos antes de ativar
1. Revisar e aplicar `sql/hype_mod_distribuicao.sql` no SQL Editor do Supabase.
2. Conferir que o bucket `hype-mod-distribuicao` é **privado**.
3. Confirmar que o Render usa uma credencial do Supabase com autorização para ler/escrever na tabela e no bucket, SEM revelar essa credencial no mod.
4. Validar o deploy em ambiente de teste com uma conta administrativa e uma conta sem permissão.
5. Ativar `HYPE_MOD_DISTRIBUTION_ENABLED=1` no serviço Flask somente depois dos testes.
6. Testar o upload de um JAR final; a primeira ação guarda um rascunho, e só **Publicar download** o libera.
7. Testar download, SHA-256 e suspensão.

## O que ESTA ETAPA NÃO FAZ
- Não modifica nenhum JAR Minecraft, não executa download automático no jogo e não faz instalação em segundo plano.
- Não produz nem verifica assinatura Ed25519 nesta área de distribuição.
- Não ofusca nem protege contra engenharia reversa o JAR enviado.
- Não substitui o processo existente do `/hype-updates/manifest.properties` e do `hypeclient-r1.jar`.
- Não publica nenhum arquivo automaticamente após a aprovação do PR.

## Próxima etapa: atualizações automáticas
No HYPE Client, implementar consulta autenticada ao catálogo, comparação segura de versões,
assinatura Ed25519 **verificada pelo cliente** para cada mod, validação do SHA-256 após
download, backup, instalação na próxima inicialização (Minecraft fechado), rollback e
indicador de status na UI. Jamais enviar a chave privada para o servidor ou para o JAR.
Não habilitar atualização automática de módulos sem validação criptográfica.

## Segurança
Usuários só baixam pelo site após autenticação; catálogo do Client usa Bearer.
O backend não entrega links públicos do Supabase.
Uma publicação suspensa deixa de aparecer no catálogo e não pode ser baixada.
O autor deve enviar somente o JAR de distribuição, **não** o original reservado.
