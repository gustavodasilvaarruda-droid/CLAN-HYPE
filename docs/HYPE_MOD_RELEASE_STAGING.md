# Central de Publicação HYPE — primeira integração

Implementação opt-in, desativada por padrão, integrada ao painel já existente em `/admin/modulos`. Não altera APIs do HYPE Client, Breed ou distribuição de updates já existente.

## Controles atuais
- `HYPE_MOD_STAGING_ENABLED` vazio/0: **rotas novas inexistentes**.
- Quando habilitada, somente sessão administrativa aprovada por `_is_admin`.
- POST exige CSRF global do `app.py` e tamanho do arquivo <= 10 MiB.
- Valida ZIP/Fabric/ID da primeira lista oficial (Client, Pokédex, Breed Calculator, Campo de Batalha e Battle AI). Auto Ovo preview não entra.
- Verifica que o Supabase Storage bucket é privado ANTES de enviar o JAR.
- Metadados, hash SHA-256, compatibilidade Fabric declarada no JAR (Minecraft, loader, Cobblemon, Java) e histórico na tabela `hype_mod_release_drafts`, com RLS.
- Sem endpoint de download público, sem ofuscação/assinatura/publicação nesta fase.

## Homologação antes de ativar em produção
1. Implantar esta branch num ambiente de teste separado.
2. Executar `sql/20261110_hype_mod_release_staging.sql` **somente no banco de teste**.
3. Confirmar bucket `hype-mod-originals` privado e RLS ativo.
4. Configurar `HYPE_RELEASE_SUPABASE_SERVICE_ROLE_KEY` **somente no ambiente do backend**, nunca no repositório ou Java Client.
5. Definir `HYPE_MOD_STAGING_ENABLED=1` no ambiente de teste. Acessar `/admin/modulos/releases`.
6. Testar 403 sem login/não admin, falha no CSRF, arquivo inválido, tamanhos, bucket acidentalmente público, armazenamento, rollback e logs. Testes locais não substituem estes testes.
7. Fazer revisão de segurança antes de decidir ativar na produção.

## Interface de administração
A opção **Atualizações do Cliente** aparece no Gerenciador de Módulos. A rota `/admin/modulos/releases` pode analisar um JAR mesmo com o staging desligado; o upload privado depende de `HYPE_MOD_STAGING_ENABLED=1` e da configuração correta do backend.

Esta área **não publica** o mod para os jogadores; ela apenas inicia a preparação da versão e registra o JAR em privado. O relatório lê somente os requisitos declarados no `fabric.mod.json`, sem garantir compatibilidade real no jogo.

## Próximas etapas necessárias para atualizar pelo site
Pipeline isolado de ofuscação, regras de preservação Fabric/Mixin/Cobblemon, testes em jogo, assinatura Ed25519 com chave privada fora do servidor web, aprovação manual, catálogo assinado e instalador/Client que instala com Minecraft fechado e oferece rollback. Sem isso, upload é só rascunho privado.
