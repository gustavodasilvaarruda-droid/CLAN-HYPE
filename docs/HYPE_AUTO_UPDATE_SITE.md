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

A variável `HYPE_UPDATES_DIR` é o diretório absoluto de armazenamento em disco do serviço. Na ausência dela, o serviço procura uma pasta `hype-updates` na raiz do projeto Flask. Em Render sem disco persistente, arquivos locais não duram entre deploys: configurar armazenamento apropriado ou uma distribuição externa de arquivos. A chave privada **não deve** estar no repositório nem no servidor.

**Importante:** atualizar o código Minecraft Fabric requer instalação entre inicializações, e não garante atualização segura de outros mods ou compatibilidade entre versões. Nenhum update deve ser liberado antes de testes reais.

## Testes

`python -m unittest tests.test_hype_updates -v` (com `Flask>=3,<4` instalado).

Os testes cobrem funcionamento com manifesto ausente, headers anti-cache, nomes permitidos e métodos de escrita indisponíveis. Eles não validam criptografia ou execução dentro do Minecraft; essas partes exigem testes adicionais da ferramenta do cliente.

## Rollback

Remover o manifesto de distribuição para interromper **novas** atualizações. Para clientes já atualizados, usar o mecanismo de backup e recuperação testado no cliente. Como o manifesto recebe `Cache-Control: no-store`, novas consultas deixam de oferecer o release removido.
