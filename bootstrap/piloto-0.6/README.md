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

### JAR piloto construído localmente

O piloto Fabric `0.6.0-stage-preview` foi montado localmente sobre o JAR
0.5 fornecido pelo proprietário. Foram preservadas todas as classes do 0.5,
adicionadas cinco classes `PrivateModUpdater*` e substituídas apenas
`HypeBootstrap`, `UpdateConfiguration`, `UpdateMode` e `fabric.mod.json`.
O entrypoint Fabric 0.6 permanece **inerte no startup** para impedir que
`update_mode=after_exit` da versão anterior dispare instalações antes
da integração de login e nova homologação.

**Testes locais:** `javac --release 21` OK; 20 asserções de preparação
isolada executadas contra o JAR final com `java -Xverify:all` OK;
`jar --validate` OK; ZIP íntegro sem entradas duplicadas. Não foi
executado no Minecraft real, no Windows do jogador ou com login real.
A presença do método `stageAfterLogin` **não faz** a integração ocorrer
automaticamente. Não colocar o JAR 0.6 no clã.

### Ponte com HYPE Client Preview 10.0.42 — piloto de login

- O JAR HYPE Client `R7.19-ALPHA7-PREVIEW10.0.42` fornecido pelo
  proprietário foi auditado via `javap`: a classe `HypeBreedApi` conclui
  login em `lambda$login$1` e executa logout em `logout()`.
- O helper opcional `integration-client/br/clanhype/client/HypeAutoStagingBridge.java`
  encaminha o token **apenas em memória** por reflexão, depois de login
  bem-sucedido; funciona também sem o Bootstrap instalado. Ele **não altera**
  o mecanismo de persistência da sessão já existente no HYPE Client.
- O patcher OFFLINE `integration-client/build/WeaveHypeClient.java` injeta
  a chamada de login e o cancelamento de logout no bytecode da versão exata
  10.0.42. O JAR original é preservado; o reempacotamento é só para teste.
- `HypePrivateSessionBridge` recebe o sinal, verifica o modo local e só
  chama `PrivateModUpdater.stageAfterLogin` se `update_mode` for
  explicitamente `stage` ou `after_exit`. Mesmo em `after_exit`, esta
  versão só prepara arquivos; não os instala.
- Em `off` (padrão), há logs seguros de recebimento de login/logout para
  homologação no Minecraft, mas **não há rede, download ou escrita em mods/**.
- O logout interrompe a tarefa e cancela o staging antes de gravar o JAR.
  Não grava nem imprime Bearer, senha, refresh token ou chave privada.
- Re-login necessário para disparar a ponte neste piloto; retomada de sessão
  previamente salva ainda exige integração complementar.
- Testes locais Java 21: 22 asserções de staging, inclusive revogação durante
  download; teste de ponte login/logout; teste de modo OFF; BasicVerifier de
  38 métodos da classe HypeBreedApi; validação ZIP/JAR de ambos os arquivos.
  **Ainda não testado dentro do Minecraft pelo proprietário.**

**Atenção: duas etapas ainda pendentes para instalar APENAS Bootstrap:**
primeiro distribuir/instalar HYPE Client assinado publicamente, reiniciar e
efetuar login; depois baixar os quatro JARs restritos por conta e aplicar com
agente pós-fechamento, backup, rollback e novas verificações. A ponte atual
exige que HYPE Client e Bootstrap 0.6 estejam instalados em uma instância
de teste; nada foi publicado no site.

Não incorporar as PRs #76, #77 ou #78, não ativar flags no Render,
não fazer deploy ou distribuir JARs aos jogadores sem homologação.
