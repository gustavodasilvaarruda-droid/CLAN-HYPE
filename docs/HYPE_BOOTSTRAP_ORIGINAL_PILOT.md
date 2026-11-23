# Piloto HYPE: originais para o Bootstrap 0.8

Este canal é exclusivo da conta do administrador. O JAR fornecido tem identificador Fabric hypebootstrap, versão 0.8.0-postexit-test, Minecraft 1.21.1 e Java 21.

O Bootstrap já consulta /api/hype/v1/updates/releases depois do login e baixa /api/hype/v1/updates/mods/{mod_id}/{sha256}.jar. Ele verifica a assinatura Ed25519 e o SHA-256. Com update_mode=after_exit, agenda a instalação para após o fechamento do Minecraft. Nesta etapa, o Bootstrap original NÃO foi modificado, porque o servidor pode oferecer o JAR original com o mesmo contrato assinado.

## Ativação separada

Na Central de Publicações aparecerá a opção "Teste do Bootstrap — JAR original, sem proteção", exclusiva da conta de teste. O JAR precisa estar previamente salvo no bucket privado.

Ativar em Render somente para a conta de teste:
- HYPE_MOD_STAGING_ENABLED=1
- HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED=1
- HYPE_PRIVATE_MOD_DOWNLOADS_ENABLED=1
- HYPE_PRIVATE_MOD_ROLLOUT_SCOPE=single
- HYPE_PRIVATE_MOD_TESTER_EMAIL=EMAIL_REAL_DO_TESTADOR
- HYPE_MOD_PILOT_ORIGINAL_ENABLED=1

A conta precisa estar autenticada e autorizada para cada módulo. Os arquivos não são públicos e a permissão é conferida também antes de transmitir cada JAR. Nunca usar scope clan para originais.

## Preparar o Bootstrap

No computador de teste crie config/hype-bootstrap.properties com:

    update_mode=after_exit

Sem essa configuração, o padrão é off. Inicie o jogo, faça login pelo HYPE Client e feche o Minecraft para permitir que o agente instale os arquivos baixados. Os mods novos entram em uso na próxima inicialização.

## Manifesto obrigatório

O site não guarda a chave de assinatura privada. Assine o JAR ORIGINAL exato no próprio computador com a chave Ed25519 correspondente à pública embutida no Bootstrap:

    python -m modules.hype_manifest_signer --private-mod --jar "HYPE-POKEDEX-ORIGINAL.jar" --private-key "chave-oficial.pem" --release 1 --output "pokedex-piloto-r1.properties"

Selecione o original já guardado no site e anexe esse .properties na opção piloto. Para uma segunda atualização, faça upload de uma nova versão do JAR, assine com um número de release maior e publique. O servidor retornará a última release válida ao Bootstrap.

NÃO envie a chave privada PEM para o site, GitHub, Render, chat ou jogadores. Se a chave original não existir, o Bootstrap atual não aceitará novas assinaturas: será necessária uma nova build piloto com chave pública nova, instalada manualmente antes dos testes.

## Limites e segurança

- O canal protegido normal permanece separado e inalterado.
- Originais ficam no armazenamento privado; nunca use distribuição pública para eles.
- Requer assinatura, SHA-256, integridade do JAR, sessão autenticada e permissão ativa por módulo.
- O piloto não funciona sem a flag individual habilitada.
- O upload isolado não publica uma atualização.
- Não houve teste real de Minecraft ou do instalador pós-fechamento nesta alteração. Faça os testes no PC do proprietário, com backup.
- Desative HYPE_MOD_PILOT_ORIGINAL_ENABLED antes de abrir a distribuição a outros jogadores.
