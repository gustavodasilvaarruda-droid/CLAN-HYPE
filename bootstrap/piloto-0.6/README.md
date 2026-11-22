# HYPE Bootstrap 0.6 — private update staging (DRAFT)

**NÃO DISTRIBUIR.** Este piloto acrescenta somente a etapa de **download autenticado e preparação** das releases privadas; **não instala mods**, não altera a pasta `mods`, não publica JARs e não ativa nenhuma flag no Render/Supabase.

### Origem e segurança
- Reutiliza o HYPE Bootstrap 0.5 e o verificador Ed25519 público do 0.4.
- O `HYPE Client` autenticado deverá chamar `PrivateModUpdater.stageAfterLogin(gameDir, token)` **somente após o login**, com Bearer de sessão em memória. Essa chamada **ainda não foi ligada ao HYPE Client**.
- `update_mode=off` continua sendo o padrão e não faz qualquer requisição.
- Para `stage` e `after_exit`, a rotina nova faz **somente staging**: `GET /api/hype/v1/updates/releases` e `GET /api/hype/v1/updates/mods/{id}/{sha}.jar` com o mesmo Bearer.
- O backend decide quais releases são autorizadas, aplicando cargos, bloqueios, visibilidade, filiação e manutenção; o Bootstrap não tenta contornar essas regras.
- Verifica cada manifesto Ed25519 com chave pública pinada, SHA-256, tamanho, URL oficial fixa, mod ID e versão do `fabric.mod.json`; recusa cópias adulteradas.
- Não permite redirects, URLs arbitrárias, HTTP, parâmetros de URL, path traversal, symlinks de staging, respostas gigantes nem gravação de token em disco.
- O staging fica apenas em `.hype-private-staging` dentro do diretório do Minecraft, sem modificar outros mods.

### Testes isolados

Java 21, arquivo JAR base 0.4 do administrador para `CatalogVerifier` e `JsonCodec`. Executar:

```sh
javac -cp hype-bootstrap-0.4.jar -d classes src/br/clanhype/bootstrap/{UpdateMode,UpdateConfiguration,PrivateModUpdater}.java test/br/clanhype/bootstrap/PrivateModUpdaterTest.java
java -cp hype-bootstrap-0.4.jar:classes br.clanhype.bootstrap.PrivateModUpdaterTest
```

**Resultado local em 22/11/2026:** 20 verificações isoladas aprovadas, sem rede, Minecraft real ou Supabase. Esse resultado NÃO equivale a teste de instalação automática.

### Bloqueios antes do teste real
1. Juntar o código-fonte completo do Bootstrap 0.4 a uma compilação Fabric/Gradle reprodutível e revisar o cliente 0.5.
2. Integrar a chamada Java ao login/saída do HYPE Client, sem salvar sessão, e tratar token expirado, perda de rede e permissão revogada.
3. Subir a release **protegida** exata para Storage privado, executar migração somente em homologação, validar o processo de aprovação e assinar manifesto offline. O JAR original não substitui o protegido.
4. Criar um agente **pós-fechamento** que reaplique validação do manifesto, estado da autorização, compatibilidade, backup/rollback, dependências e conflitos antes de trocar arquivos. Isso ainda **NÃO** foi implementado aqui.
5. Testar no Windows / Fabric 1.21.1 / Java 21 com instância separada e confirmar logs e ausência de crash. Depois, revisão manual antes de liberar a distribuição.

Dependências: PR #76 (Bootstrap 0.5) e PR #77 (API de releases privadas), ambas em revisão. Não ativar `HYPE_AUTH_MOD_ENTITLEMENTS_ENABLED` ou `HYPE_PRIVATE_MOD_DOWNLOADS_ENABLED` no ambiente de produção.
