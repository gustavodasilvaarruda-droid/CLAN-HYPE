# HYPE Client: preparação segura de atualizações (14/11/2026)

## Situação atual

- A Central de Publicação recebe e valida JARs do Fabric; os originais ficam no bucket PRIVADO do Supabase, marcados como aguardando_protecao.
- Esse upload NÃO ofusca, assina ou distribui arquivos para os jogadores.
- O cliente atual usa uma chave pública Ed25519 fixa embutida em HypeAutoUpdate. Ele rejeita atualizações assinadas por outra chave.
- O cliente aceita manifesto no domínio HTTPS clan-hype.onrender.com, mod_id=hypeclient, minecraft=1.21.1, channel=stable, um release numérico crescente, version, url, sha256, size e signature (Base64 Ed25519). A assinatura abrange os oito primeiros campos na ordem exata com quebra de linha final.
- As rotas existentes de /hype-updates no Flask são SOMENTE para leitura. Não existe ainda publicação automática ou conversão do staging em release. A distribuição pública permanece desligada.

## Preparação local, sem publicar

Instale cryptography somente no computador offline ou ambiente de build confiável que prepara releases; não adicione a chave privada ao GitHub, Render, Supabase, backups de jogo nem ao JAR.

1. Instale a dependência de ferramenta: python -m pip install "cryptography>=43,<47".
2. Inspecione o arquivo sem escrever nada:
   python tools/hype_sign_release.py --jar CAMINHO_DO_CLIENT.jar --inspect
3. Se e SOMENTE se existir a chave privada ORIGINAL que corresponde à chave pública já embutida no cliente instalado, prepare a release:
   python tools/hype_sign_release.py --jar CAMINHO_DO_CLIENT.jar --key CAMINHO_PRIVADO/chave.pem --release 8 --out CAMINHO_PRIVADO/preparado-r8
   Substitua o número 8 pelo próximo release que nunca tenha sido usado.
4. O resultado LOCAL contém manifest.properties assinado e releases/hypeclient-r8.jar. Não há upload e o Minecraft não muda.
5. Confirme a versão, o hash e a assinatura com uma cópia TESTE do cliente, mantendo os jogadores no canal antigo.
6. Após teste separado de distribuição/rollback e do painel administrativo, planejar a publicação com controle de acesso, armazenamento durável e rollback. O serviço Render possui filesystem efêmero; não depender apenas de arquivos locais nele para releases.
7. Nunca compartilhar a chave privada. Se a chave original não existir, interrompa: será necessário criar um novo par de chaves em ambiente confiável, embutir a NOVA chave pública em um novo build do HYPE Client e instalar esse novo cliente por um caminho confiável antes de testar atualização automática. Apenas trocar a chave no servidor NÃO funciona.

## Antes de distribuir para jogadores

- Verificar se o JAR novo realmente tem uma versão/build identificável; dois JARs de mesma versão podem confundir o teste. O número release do manifesto é separado da versão em fabric.mod.json.
- Confirmar hash SHA-256 e assinatura com chave já confiada no cliente.
- Testar download/redirect HTTPS, instalação, reinicialização e restauração do backup anterior com um cliente de teste.
- Testar que um manifesto com assinatura falsa ou JAR alterado é recusado.
- Ofuscação é outra etapa, NÃO é fornecida por este assinador; antes de ofuscar, testar Fabric entrypoints, mixins e compatibilidade.
- Nenhum procedimento descrito aqui autoriza publicação antecipada.
