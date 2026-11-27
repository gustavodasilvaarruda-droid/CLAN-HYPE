# HYPE: somente candidatos aprovados no catálogo automático

A Biblioteca HYPE já permite uploads de originais e tem um catálogo assinado
Ed25519 para o Bootstrap. O catálogo legado pode servir o **JAR original**
quando as duas flags de distribuição são ligadas.

## Modo de proteção antes da distribuição (opt-in)

Configure `HYPE_AUTO_REQUIRE_APPROVED_CANDIDATE=1` **além** das duas
flags existentes `HYPE_AUTO_SIGNED_CATALOG_ENABLED=1` e
`HYPE_AUTO_SIGNED_DOWNLOADS_ENABLED=1` para impedir que originais sejam
servidos por esse catálogo público.

Neste modo, cada mod deve ter um candidato armazenado em caminho privado
`<mod_id>/<draft_id>/protected/<nonce>/<sha256>.jar`, com:

- status `pronto_para_aprovacao` do draft da Biblioteca (`library_upload=true`);
- SHA-256 e tamanho válidos, diferentes do original, e caminho esperado;
- revisão automática `passed` vinculada ao hash exato do candidato;
- revisão humana do mesmo hash, com lançamento, menus, conexão e estabilidade
  confirmados no Minecraft.

O catálogo e o download passam a usar exclusivamente os bytes do candidato
aprovado, com verificação de hash, tamanho e ID/version Fabric no download.
Um mod novo sem aprovação não substitui uma versão anterior aprovada.
Sem candidato elegível, o catálogo não lista o mod; não ocorre fallback
para o original. O próprio Bootstrap permanece excluído, assim como
`hypeegg`.

**Limite fundamental:** esta opção NÃO ofusca o arquivo e não comprova que
um candidato esteja realmente ofuscado. Ela somente impede a distribuição
dos originais pelo catálogo automático quando ativada. Para ter upload →
proteção automática, ainda é necessário instalar/configurar um ofuscador
Fabric compatível no worker isolado, testar o resultado em Minecraft 1.21.1
e completar a aprovação. Até lá, não ative distribuição pública sem avaliar
as permissões dos mods e os riscos de versões piloto.

Esta opção é OFF por padrão para não alterar o funcionamento atual. Não
altera Bootstrap, chaves, banco de dados, publicação privada ou variáveis
de ambiente na Render.
