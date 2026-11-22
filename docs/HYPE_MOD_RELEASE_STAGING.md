# HYPE Client — publicação e atualização segura pelo site

Esta implementação é opt-in e desligada por padrão. O administrador faz upload privado, revisa e testa o JAR, depois publica somente com manifesto Ed25519 assinado. O upload por si só não atualiza jogadores.

## Atualizador existente no HYPE Client
A versão R7.19 Alpha 7 Preview 10.0.42 fornecida em novembro de 2026 consulta:
- https://clan-hype.onrender.com/hype-updates/manifest.properties
- https://clan-hype.onrender.com/hype-updates/releases/hypeclient-rN.jar

O cliente exige HTTPS no domínio oficial, mod_id=hypeclient, minecraft=1.21.1, channel=stable, número de release crescente, tamanho, SHA-256 e assinatura Ed25519. **A chave pública já é fixa dentro do JAR**. A chave privada correspondente precisa existir fora do repositório e do servidor web. Sem ela, nenhum manifesto gerado para este cliente será aceito. Uma chave privada nova não funciona com as instalações atuais: seria preciso uma primeira instalação manual de um cliente contendo a nova chave pública.

## Configuração no servidor
- HYPE_MOD_STAGING_ENABLED=1: análise e upload para bucket privado pelo Painel Admin.
- HYPE_MOD_PROTECTED_UPLOAD_ENABLED=1: aceita build protegido candidato (verificado e separado do original) para uma versão em teste; não executa ofuscação e não publica. Requer STAGING. Por segurança, vem desativado.
- HYPE_MOD_PUBLISH_ENABLED=1: habilita a importação administrativa de um manifesto válido para JAR previamente aprovado. Requer STAGING.
- HYPE_MOD_DISTRIBUTION_ENABLED=1: o manifesto e os JARs vêm do catálogo Supabase privado. Se não houver versão assinada publicada, os endpoints retornam 404.
- Sem DISTRIBUTION, a distribuição estática anterior continua inalterada.

O backend usa SUPABASE_URL e SUPABASE_KEY, inicializados no app.py. Essas chaves devem permanecer secretas no Render, jamais no site público, repositório ou mod Java. O bucket hype-mod-originals deve permanecer privado e sem políticas SELECT para usuários anônimos.

Em homologação, aplicar sql/20261110_hype_mod_release_staging.sql e sql/20261121_hype_mod_published_releases.sql, confirmar RLS e acesso do backend. **Não executar migrações de produção sem revisão e backup.**

## Uso da tela
1. Admin → Gerenciador de Módulos → Atualizações do Cliente.
2. Enviar o JAR. O site verifica ZIP, ID Fabric, integridade, versão, dependências declaradas e SHA-256, e salva como rascunho privado.
3. Preparar o build protegido em um projeto-fonte Fabric/Gradle, respeitando entrypoints, Mixins, reflexão e classes usadas pelo atualizador. O site **não** faz ofuscação automática no upload, pois processar um JAR arbitrário sem mapeamentos pode quebrar o mod.
4. Habilitar o upload privado de candidato quando houver uma compilação preparada. A tela compara com o original e rejeita ID, versão, dependências, entrypoints e Mixins diferentes. Uma diferença de bytes e a análise estrutural **não provam** a ofuscação.
5. Testar **o build candidato** dentro do Minecraft, marcar 'Testado no jogo' e aprovar somente se o cadastro tiver esse build. Sem ele, aprovação é bloqueada.
6. Criar um manifesto properties usando as linhas release, version, url, sha256, size, minecraft, mod_id e channel, nesta ordem, e assiná-las offline com a chave Ed25519 privada original. A assinatura Base64 é acrescentada como signature.
7. Importar o manifesto assinado no painel, selecionar a versão aprovada e publicar. O backend verifica assinatura, hash do arquivo recuperado, tamanho, versão, URL oficial e número de release crescente.
8. Habilitar DISTRIBUTION inicialmente só em homologação; verificar o endpoint de saúde, o manifesto, o download, o fechamento e reinício do Minecraft, e a recuperação de falhas. Depois aprovar deploy em produção.

## Contrato do manifesto
- release: inteiro positivo de 1 a 999999999, sempre maior que releases anteriores.
- version: versão exata do fabric.mod.json, inclusive letras e símbolos.
- url: https://clan-hype.onrender.com/hype-updates/releases/hypeclient-rN.jar, onde N é release.
- sha256: hash hexadecimal minúsculo do JAR (64 caracteres).
- size: tamanho exato do arquivo em bytes (entre 1000 e 67108864 aceitos pelo cliente; o bucket aceita até 10485760).
- minecraft: 1.21.1; mod_id: hypeclient; channel: stable.
- signature: Base64 da assinatura Ed25519 do texto canônico UTF-8 com as oito primeiras linhas, cada uma no formato chave=valor seguida de uma quebra de linha LF, inclusive a última. A linha signature não é assinada.

## Segurança e limitações
O servidor nunca assina atualizações, nem aceita manifesto sem assinatura válida para a chave pública fixa no cliente. A publicação assinada precisa apontar para o **build candidato protegido**, armazenado separadamente no mesmo bucket privado; o original não pode ser distribuído por engano. A URL retorna o JAR diretamente a partir de Storage privado, pelo domínio oficial, com conferência de tamanho e hash. Uma vez instalado no PC do jogador, o JAR não pode ser protegido 100% contra cópia: manter segredos e decisões de permissão no servidor. A entrega automática só deve ser ativada após homologação do instalador e do rollback.

**Estado:** branch de desenvolvimento pronta para revisão. Nenhum arquivo foi publicado automaticamente para os jogadores com estas mudanças.

## Estado e pendências em 22/11/2026
- Implementado: verificação estrutural automática de arquivos Fabric; recebimento privado de candidatos protegidos com SHA-256 próprio; proibição de aprovar sem candidato e teste manual; assinatura digital vinculada ao candidato, nunca ao JAR original.
- Necessário para ofuscação **automática**: o **código-fonte** do HYPE Client (projeto Gradle/Fabric, regras de remapeamento, Mixins, dependências), um builder isolado, regras de keep validadas, validações em Minecraft e credenciais de um assinador fora do servidor web. Isso **não está implementado**.
- Não habilitar HYPE_MOD_PUBLISH_ENABLED nem HYPE_MOD_DISTRIBUTION_ENABLED até confirmar chave original Ed25519, teste do instalador e rollback. A proteção total contra engenharia reversa não é possível.
