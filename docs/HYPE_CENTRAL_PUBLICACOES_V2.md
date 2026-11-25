# Central de Publicacoes HYPE v2 — configuracao segura do site

## Objetivo

Um envio de **JAR original** pelo painel de administrador gera um rascunho privado.
Quando a fila estiver ativada, a solicitação de proteção é criada automaticamente.
Um worker **isolado** prepara o candidato protegido; apenas depois dos testes e
da aprovação manual é possível criar uma release. O Bootstrap público nunca
deve consultar o bucket de originais.

## Ordem dos mods

O **HYPE Client** é o primeiro teste: outros mods HYPE dependem dele.
A migração `sql/20261124_hype_client_priority_queue.sql` faz a RPC
`hype_claim_mod_protection_job()` escolher o Client antes dos demais,
preservando a ordem de chegada dentro de cada prioridade e o lock atômico.

**Essa migração não foi aplicada na produção pela PR**. Deve ser revisada antes
de ser aplicada. Ela não processa JARs, não publica nenhuma versão nem libera
arquivos privados.

## Acesso ao original

A nova regra do download administrativo do arquivo original exige, além do
login e cargo de administrador:

- `HYPE_MOD_ORIGINAL_OWNER_EMAIL` no ambiente do servidor (email do proprietário);
- `HYPE_MOD_ORIGINAL_TEST_DOWNLOAD_ENABLED=1` e
  `HYPE_MOD_STAGING_ENABLED=1`.

Sem a identificação explícita do proprietário, o download falha fechado.
O email é comparado com `session["usuario_email"]`, não com um parâmetro
enviado no pedido HTTP. Não colocar credenciais nos arquivos públicos.

**Atenção:** a integração do canal privado automático para todos os novos
mods ainda está pendente. Esta regra controla a rota de download pelo painel.

## Proteção automatizada — dependências não concluídas

A fila do site usa `HYPE_MOD_PROTECTION_QUEUE_ENABLED=1`, mas isso só agenda
o job: o processo web **não** executa obfuscação.
`services/hype_mod_protection_worker.py` precisa rodar num ambiente isolado
com `HYPE_MOD_PROTECTION_WORKER_ENABLED=1`,
`HYPE_WORKER_SUPABASE_URL`,
`HYPE_WORKER_SUPABASE_SERVICE_KEY` e
`HYPE_MOD_PROTECTOR_ARGV_JSON`, apontando para um executável confiável
de ofuscação compatível com Fabric 1.21.1.

A ferramenta de ofuscação **ainda não foi instalada/validada**.
Não ativar o worker em produção sem testar a preservação de metadados Fabric,
entrypoints, mixins, reflexão, recursos e funcionamento real no Minecraft.
Não colocar a chave de serviço ou originais nos workflows públicos.
O worker não assina, aprova ou publica releases automaticamente.

## Checklist antes de publicar

1. Executar testes da Central e do worker com `python -m unittest discover -s tests -p "test_hype_mod*.py" -v` e `python -m unittest discover -s tests -p "test_hype_publish_center*.py" -v`.
2. Configurar o proprietário do original no servidor, após revisar o RBAC.
3. Aplicar a migração de prioridade depois de validar o SQL.
4. Configurar e testar a ferramenta de proteção em ambiente isolado.
5. Fazer upload de uma nova versão do HYPE Client; não reutilizar um JAR já publicado.
6. Confirmar que o protegido inicia e funciona no Minecraft.
7. Publicar só com aprovação explícita e manifesto assinado offline.
8. Testar atualização do Bootstrap separado, sem expor originais.

A PR #101 é uma primeira entrega de código, **não** uma versão implantada no site.

## Novos IDs de mods

A migracao `sql/20261124_hype_mod_dynamic_ids_staging.sql` remove a lista
de cinco IDs dos CHECKs de **rascunhos** e **fila de protecao**, aceitando
identificadores Fabric validos. Ela nao altera as tabelas de publicacao
assinada; a distribuicao de novos IDs sera uma etapa separada.

## Baixar o original depois da aprovacao

A rota privada do painel tambem permite baixar o original
`pronto_para_aprovacao`. Continua restrita ao email do proprietario
e preserva a verificacao SHA-256; JARs rejeitados ou excluidos nao
ficam acessiveis nessa rota.
