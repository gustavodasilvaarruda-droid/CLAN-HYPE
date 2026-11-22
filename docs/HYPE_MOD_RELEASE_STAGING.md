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
5. Ao receber um build candidato, o backend faz um preflight estático de integridade SHA-256 dos JARs, compatibilidade do Fabric, classes de inicialização e presença do atualizador (para o Client). Na seção **Revisar e testar**, o admin pode executar novamente essas verificações contra os bytes privados armazenados. Elas não executam o Minecraft e não provam ofuscação.
6. Instalar **exatamente o build candidato identificado pelo SHA-256** no Minecraft de teste e confirmar individualmente: inicialização, menus e recursos, conexão/login no servidor e ausência de crashes críticos. O painel registra usuário, data/hora em UTC (mostrada em Brasília), observações e SHA-256 na coluna JSON meta. Uma falha ou um teste faltando bloqueia a aprovação; aprovar continua sendo diferente de publicar.
7. Um registro só pode receber um JAR candidato. Caso precise testar outro JAR, criar novo rascunho, preservando a rastreabilidade. Voltar um item aprovado para testes ou rejeitá-lo apaga a evidência manual de aprovação, mas não altera os JARs armazenados.
8. Criar um manifesto properties usando as linhas release, version, url, sha256, size, minecraft, mod_id e channel, nesta ordem, e assiná-las offline com a chave Ed25519 privada original. A assinatura Base64 é acrescentada como signature.
9. Importar o manifesto assinado no painel, selecionar a versão aprovada e publicar. O backend verifica assinatura, hash do arquivo recuperado, tamanho, versão, URL oficial e número de release crescente.
10. Habilitar DISTRIBUTION inicialmente só em homologação; verificar o endpoint de saúde, o manifesto, o download, o fechamento e reinício do Minecraft, e a recuperação de falhas. Depois aprovar deploy em produção.

## Assinatura offline assistida (sem enviar a chave ao site)
O repositório inclui `python -m modules.hype_manifest_signer` para gerar e verificar o manifesto **num computador confiável**. É necessária a **chave privada Ed25519 original** que corresponde à chave pública presente no cliente instalado; o script recusa qualquer outra chave. Não envie a chave privada pelo chat, site, GitHub, Supabase ou Render. Não coloque a chave em variáveis de ambiente do servidor.

Depois de registrar o **candidato protegido**, validar seu hash e testar o **mesmo JAR** no Minecraft, executar localmente (exemplo ilustrativo; escolher um número de release ainda não utilizado):

```sh
python -m modules.hype_manifest_signer --jar "HYPE-CLIENT-PROTEGIDO.jar" --private-key "hype-private-key.pem" --release 43 --output "manifest.properties"
```

A ferramenta lê a versão diretamente de `fabric.mod.json`, calcula SHA-256 e tamanho do arquivo protegido, monta as oito linhas canônicas e adiciona a assinatura Ed25519. O verificador do site ainda confere todos os dados antes da publicação. O manifesto `.properties` pode ser enviado pelo Painel Admin **somente após** a aprovação dos testes. O arquivo PEM jamais deve ser enviado.

Se a chave original não existir, **não gere outra esperando atualizar o cliente já instalado**: será necessário planejar uma atualização inicial manual que instale um cliente com a nova chave pública incorporada. Esse procedimento deve ser testado separadamente.

## Contrato do manifesto
- release: inteiro positivo de 1 a 999999999, sempre maior que releases anteriores.
- version: versão exata do fabric.mod.json, inclusive letras e símbolos.
- url: https://clan-hype.onrender.com/hype-updates/releases/hypeclient-rN.jar, onde N é release.
- sha256: hash hexadecimal minúsculo do JAR (64 caracteres).
- size: tamanho exato do arquivo em bytes (entre 1000 e 67108864 aceitos pelo cliente; o bucket aceita até 10485760).
- minecraft: 1.21.1; mod_id: hypeclient; channel: stable.
- signature: Base64 da assinatura Ed25519 do texto canônico UTF-8 com as oito primeiras linhas, cada uma no formato chave=valor seguida de uma quebra de linha LF, inclusive a última. A linha signature não é assinada.

## Limpeza de uploads privados no Painel Admin

A Central de Publicação permite ao administrador apagar um registro e os JARs
privados associados somente se o rascunho estiver **aguardando proteção** ou
**rejeitado**. A exclusão exige confirmação explícita, sessão administrativa,
verificação do bucket privado e validação dos caminhos de armazenamento. Um JAR
em teste deve ser rejeitado antes de ser descartado; builds aprovados e releases
publicadas ou desabilitadas para rollback não podem ser excluídos.

O servidor verifica ligações no catálogo de releases (por rascunho e caminho).
A remoção ocorre primeiro no banco e depois no Storage privado, com registro da
ação. Como banco e Storage não têm uma transação conjunta, uma falha na segunda
etapa pode deixar um objeto privado órfão: nesse caso, o painel alerta para
conferência administrativa, sem publicar ou afetar uma release ativa. **Nada é
apagado automaticamente.**

Na etapa **2A — Escolher um original já enviado**, o administrador seleciona
um JAR do armazenamento privado que esteja **aguardando proteção** e o move
para **em teste**, sem alterar seus bytes nem publicar a versão. A seleção mostra
ID Fabric, versão, nome do arquivo, data de envio e parte do SHA-256.
Na etapa **2B — Vincular o JAR candidato**, o administrador seleciona explicitamente
a versão **em teste** que ainda não tem candidato, e envia um **segundo JAR**
gerado/protegido fora do site. O backend compara ID, versão, dependências,
estrutura e hashes; a tela indica quais candidatos já foram registrados.
O site não reprotege o original nem comprova a ofuscação. Reenviar o original
como candidato não é o procedimento correto.

## Segurança e limitações
O servidor nunca assina atualizações, nem aceita manifesto sem assinatura válida para a chave pública fixa no cliente. A publicação assinada precisa apontar para o **build candidato protegido**, armazenado separadamente no mesmo bucket privado; o original não pode ser distribuído por engano. A URL retorna o JAR diretamente a partir de Storage privado, pelo domínio oficial, com conferência de tamanho e hash. Uma vez instalado no PC do jogador, o JAR não pode ser protegido 100% contra cópia: manter segredos e decisões de permissão no servidor. A entrega automática só deve ser ativada após homologação do instalador e do rollback.

**Estado:** branch de desenvolvimento pronta para revisão. Nenhum arquivo foi publicado automaticamente para os jogadores com estas mudanças.

## Estado e pendências em 22/11/2026
- Implementado: verificação estrutural automática de arquivos Fabric; recebimento privado de candidatos protegidos com SHA-256 próprio; proibição de aprovar sem candidato e teste manual; assinatura digital vinculada ao candidato, nunca ao JAR original.
- Necessário para ofuscação **automática**: o **código-fonte** do HYPE Client (projeto Gradle/Fabric, regras de remapeamento, Mixins, dependências), um builder isolado, regras de keep validadas, validações em Minecraft e credenciais de um assinador fora do servidor web. Isso **não está implementado**.
- Não habilitar HYPE_MOD_PUBLISH_ENABLED nem HYPE_MOD_DISTRIBUTION_ENABLED até confirmar chave original Ed25519, teste do instalador e rollback. A proteção total contra engenharia reversa não é possível.


## Migração para a nova chave pública (instalação manual inicial)

A nova chave pública Ed25519 enviada pelo administrador foi verificada contra a
classe `br/clanhype/client/update/HypeAutoUpdate.class` do JAR experimental
`HYPE-CLIENT-CHAVE-PUBLICA-NOVA-TESTE-MANUAL.jar`. Seu SHA-256 da chave **pública
em DER** é:
`0eef3a6a125a8efe03b93949e98a8028c3f589317c3c9ec8fe4509b2d31f0cd4`.

O verificador de manifesto no servidor foi atualizado para fixar essa chave
pública na branch de revisão. A chave **privada correspondente permanece apenas
no computador do administrador** e jamais deve ser transferida ao site ou ao GitHub.

**Pré-condições para produção:**
1. Fazer backup do mod instalado e instalar manualmente o JAR com a nova chave
   pública nos PCs de teste; verificar Minecraft, login e funções principais.
2. Integrar a PR e implantar o servidor **sem ativar publicação/distribuição**.
   Configurar o armazenamento privado e fazer testes de integração em homologação.
3. Validar a assinatura de um manifesto de teste **offline** com a chave privada
   correspondente e testar a atualização automática fim a fim, inclusive rollback.
4. Só então distribuir a versão-base nova manualmente aos outros jogadores e
   considerar ativar o canal de distribuição com aprovação explícita do administrador.

**Aviso de compatibilidade:** as instalações que ainda contêm a chave pública
antiga não aceitarão as atualizações assinadas pela nova chave. A nova assinatura
não é uma atualização automática da chave antiga.
