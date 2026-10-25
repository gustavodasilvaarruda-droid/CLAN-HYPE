# HYPE Auto Update — distribuição pelo site

A integração com Flask disponibiliza os endpoints:

- `GET /hype-updates/health`: informa apenas se existe manifesto no diretório de distribuição.
- `GET /hype-updates/manifest.properties`: entrega o manifesto (sem cache), se publicado.
- `GET /hype-updates/releases/hypeclient-rN.jar`: entrega um release imutável autorizado.

O serviço **não publica releases**, não grava no banco, não faz upload, não assina arquivos e não mexe no login ou nas permissões. Ao publicar a branch sem arquivos de release, o manifesto retorna 404 e **nenhum update é distribuído**.

## Preparação antes da ativação

1. Confirmar a URL HTTPS do Render usada pela prévia do cliente R7.17.
2. Gerar o manifesto com a ferramenta de assinatura offline, usando a chave privada apropriada **fora do GitHub e do Render**, e confirmar o formato exato esperado pelo cliente.
3. Preparar um novo JAR homologado e conferir seu SHA-256; publicar arquivo de nome `hypeclient-rN.jar` na pasta `releases` do diretório `HYPE_UPDATES_DIR`. Use somente nomes novos, sem substituir releases antigos.
4. Somente após revisão da assinatura, URL, hash e testes de backup e recuperação, disponibilizar `manifest.properties` no mesmo diretório.
5. Testar primeiro com um jogador de homologação e verificar o jogo reiniciando normalmente; depois expandir a distribuição.

A variável `HYPE_UPDATES_DIR` é o diretório absoluto de armazenamento em disco do serviço. Na ausência dela, o serviço procura uma pasta `hype-updates` na raiz do projeto Flask. Em Render sem disco persistente, arquivos locais não duram entre deploys: use um disco persistente ou a opção GitHub Releases abaixo. A chave privada **não deve** estar no repositório nem no servidor.

## Opção de armazenamento persistente: GitHub Releases + Render

Em vez de depender do disco temporário do Render, os arquivos JAR podem ficar
guardados como *assets* de uma versão publicada no GitHub. O site mantém o
endereço `/hype-updates/releases/hypeclient-rN.jar` usado pelo cliente e responde
com redirecionamento HTTPS (302) para o arquivo publicado. Essa opção é **desligada
por padrão** e não cria/publica manifestos.

1. No GitHub do projeto, abra **Releases > Draft a new release**, crie a tag
   `hypeclient-updates` e envie apenas JARs de versões assinadas e homologadas.
   Cada arquivo deve usar um nome único no formato `hypeclient-rN.jar`;
   nunca substitua um arquivo já publicado.
2. No painel do Render, configure a variável de ambiente **não secreta**:
   `HYPE_UPDATES_RELEASE_BASE_URL=https://github.com/gustavodasilvaarruda-droid/CLAN-HYPE/releases/download/hypeclient-updates`
   (ajuste se a tag/repositório mudar). Salve as configurações e verifique o deploy.
3. Sem arquivo na pasta local, a rota de um JAR permitido responde `302` para
   `<HYPE_UPDATES_RELEASE_BASE_URL>/<nome-do-jar>`. Se o endereço remoto não
   existir, o GitHub responderá `404`; a rota não confirma existência do asset.
   Sem a variável e sem JAR local, a resposta continua `404`.
4. O **manifesto assinado** pode ser versionado no próprio repositório em
   `hype-updates/manifest.properties`, **somente após** validar assinatura,
   SHA-256, compatibilidade e backup. Ele será incluído no próximo deploy e
   permanecerá disponível após novos deploys. Revise em um PR separado: fazer
   merge desse manifesto pode iniciar a distribuição para todos os clientes
   que consultam o endereço.
5. Para o teste de ponta a ponta, confirmar que o cliente R7.17 **segue
   redirecionamentos HTTPS**, valida a assinatura do manifesto e o hash do JAR,
   faz backup e só instala depois de fechar o Minecraft. Não liberar o
   manifesto antes desse teste.

Configurar apenas `HYPE_UPDATES_RELEASE_BASE_URL` **não** ativa atualização
automática: sem `manifest.properties`, o endpoint de health continua com
`manifest_present: false`. A chave privada de assinatura deve permanecer
exclusivamente offline; não enviar ao GitHub, Render ou Supabase.

**Importante:** atualizar o código Minecraft Fabric requer instalação entre inicializações, e não garante atualização segura de outros mods ou compatibilidade entre versões. Nenhum update deve ser liberado antes de testes reais.

## Testes

`python -m unittest tests.test_hype_updates -v` (com `Flask>=3,<4` instalado).

Os testes cobrem funcionamento com manifesto ausente, headers anti-cache, nomes permitidos e métodos de escrita indisponíveis. Eles não validam criptografia ou execução dentro do Minecraft; essas partes exigem testes adicionais da ferramenta do cliente.

## Rollback

Remover o manifesto de distribuição (e publicar a alteração no Render) para interromper **novas** atualizações. Para clientes já atualizados, usar o mecanismo de backup e recuperação testado no cliente. Como o manifesto recebe `Cache-Control: no-store`, novas consultas deixam de oferecer o release removido.
