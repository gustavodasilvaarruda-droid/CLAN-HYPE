# Publicar um JAR e atualizar automaticamente no HYPE Bootstrap

## Operação do dono

Na página **Meus Mods**, enviar qualquer JAR Fabric válido para a biblioteca
privada. O upload **não publica** nada. Quando a versão estiver pronta, clicar
**Publicar no Bootstrap** no arquivo exato e confirmar que será distribuído.

O site verifica o JAR privado (ZIP, metadados Fabric, tamanho, SHA-256), valida
a chave Ed25519 do catálogo e grava em `meta.bootstrap_publication` a autorização
explicita do administrador vinculada ao `module_id`, `version` e SHA.

O endpoint `/hype-updates/mods/catalog.json` inclui **somente** arquivos
explicitamente publicados quando o modo simples está ligado, escolhendo a
última data de publicação de cada ID Fabric. O download no endpoint
`/hype-updates/mods/<id>/<sha>.jar` verifica novamente o arquivo armazenado.

Assim, publicar outro JAR do mesmo ID substitui a revisão no catálogo, **mesmo
sem mudar o campo version**. Publicar intencionalmente um arquivo antigo volta
para a revisão antiga. JARs não publicados não substituem versões existentes.

O Bootstrap 1.7 consulta o catálogo periodicamente e compara os hashes. A
instalação ocorre **depois que o Minecraft fecha**, não enquanto usa o JAR.

## Configuração (ambiente do Render)

Somente após teste em instância separada, configurar explicitamente:

- `HYPE_MOD_STAGING_ENABLED=1` para a biblioteca (já disponível no site).
- `HYPE_AUTO_SIMPLE_PUBLISH_ENABLED=1` para exigir botão de publicação.
- `HYPE_AUTO_SIGNED_CATALOG_ENABLED=1` para catálogo assinado.
- `HYPE_AUTO_SIGNED_DOWNLOADS_ENABLED=1` para baixar os JARs publicados.
- `HYPE_AUTO_REQUIRE_APPROVED_CANDIDATE=0` para o modo **simples**, que
  distribui o JAR enviado pelo administrador sem um fluxo de ofuscação.
- `HYPE_AUTO_SIGNING_PRIVATE_KEY_PEM_B64` contém uma chave privada Ed25519
  já configurada pelo responsável, cuja pública corresponde à fixada no
  Bootstrap. **Nunca gerar outra chave sem atualizar os clientes nem expor
  esta chave nos logs, frontend ou repositório.**

A tela só oferece o botão se o modo simples e ambos os canais de distribuição
estiverem habilitados. Consulte `/hype-updates/mods/health` para ver o estado
do catálogo, sua revisão e total de mods. Sem JAR publicado, o catálogo
permanece vazio — isso não é erro de download.

Os controles são opt-in para evitar que uploads antigos se tornem públicos.

## Segurança e limitações

**Publicar distribui o JAR original, sem ofuscação automática**. Quem possui a
URL assinada do catálogo pode baixar o JAR; não é uma API privada. Usar esta
opção somente se o proprietário aceita esta distribuição pública. Permissões
de **uso** no HYPE Client devem continuar validadas no site e no servidor
para recursos sensíveis; bloquear somente a interface do mod não impede
modificações locais do JAR.

O Bootstrap fica fora do catálogo comum (como HYPE Egg). Atualizar o próprio
Bootstrap requer processo separado. Dependências Fabric/Cobblemon não são
instaladas automaticamente se não estiverem no catálogo.

Mesmo com todas as flags ligadas, o site não força atualização nos jogadores
que não têm o Bootstrap 1.7 instalado. A instalação real no Windows precisa ser
testada, incluindo backup, arquivo corrompido, duas versões do mesmo ID e
reabertura do Minecraft. Teste inicial somente com uma instância privada,
não habilite para todo o clã antes de validar.

**Aprovação de segurança:** essa modalidade é uma escolha explícita do dono
para não esperar proteção manual; ela não deve substituir a modalidade
alternativa `HYPE_AUTO_REQUIRE_APPROVED_CANDIDATE=1`, usada quando a
obfuscação/revisão é obrigatória.

## Central em lote (27/11/2026)

A tela **Meus Mods** pode selecionar até **30 JARs** de uma vez. Com JavaScript
habilitado, o botão **Salvar tudo** executa o envio dos arquivos selecionados
e as ações marcadas nos registros da biblioteca, sem navegação/reload da página.
O usuário pode marcar **Publicar os novos arquivos no Bootstrap ao salvar**
para enviar e distribuir cada JAR em uma única interação. O servidor exige
sessão administrativa, CSRF, chave de assinatura e confirmação explícita de
que o original ficará público. Os endpoints existentes continuam responsáveis
por validar cada arquivo.

**Publicar versões recentes:** marca no máximo o registro mais recente de cada
ID Fabric. **Marcar pendentes para apagar:** permite remover rascunhos privados
e rejeitados elegíveis; não marca itens publicados, protegidos ou de testes
restritos. **Limpar seleção** cancela alterações pendentes na tela.

Uma nova publicação do mesmo ID Fabric torna-se a única versão ativa no
catálogo assinado, independentemente do nome do arquivo ou da string de
versão. Isso **não elimina automaticamente versões antigas da biblioteca
ou backups**. JARs publicados anteriormente não podem ser apagados pelo
fluxo comum enquanto puderem estar em uso ou associados a um rollback.
O Bootstrap faz a substituição local após o Minecraft fechar.

A interface mostra sucesso/erro por item e atualiza a lista **uma vez** ao
final. A interação é única, mas os pedidos ao servidor são processados
individualmente: **não é uma transação de tudo-ou-nada**. Se um JAR falhar, os
demais podem ser concluídos; confira o resumo antes de repetir a operação.
Sem JavaScript, os formulários individuais continuam disponíveis.
