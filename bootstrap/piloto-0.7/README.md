# HYPE Bootstrap 0.7 — planejamento seguro de instalação (DRAFT)

**NÃO INSTALAR / NÃO PUBLICAR.** Este é um módulo de planejamento **somente leitura**,
anexado ao piloto 0.6. Nenhum arquivo em `mods/` é criado, sobrescrito,
movido ou removido por este código.

O que já existe:
- `PrivateInstallPlanner.inspect(...)` aceita a release privada somente após
  verificar o manifesto Ed25519 e o JAR preparado com SHA-256 exato.
- Inspeciona o diretório `mods/` e os `fabric.mod.json` reais, sem confiar
  no nome do JAR como identidade do módulo.
- Retorna `READY_FOR_FIRST_INSTALL` somente quando não existe outra instalação
  com o mesmo ID Fabric; retorna `ALREADY_INSTALLED` se o SHA exato já está lá;
  retorna `CONFLICT` se existe uma versão manual diferente ou duplicada.
- Recusa JAR adulterado, staging inseguro, diretório de mods com symlink,
  manifesto incorreto e diretório de mods com JARs malformados.
- Trabalha com os quatro mods privados (`hype_pokedex`,
  `hype_breed_calculator`, `hype_battlefield`, `hype_battle_ai`).
  **O HYPE Client tem atualização assinada própria**, e o Bootstrap
  não deve tratar o próprio Client como mod privado.

Validação local em 22/11/2026:
- Compilação em Java 21 OK.
- **10 verificações locais aprovadas** com o mesmo SHA protegido da Pokédex Beta 8:
  primeiro install possível, pasta mods ausente e vazia, arquivo igual,
  versão manual conflitante, duplicação, assinatura adulterada,
  staging adulterado, symlink de staging e ausência de escrita em mods.
- Testes com chave Ed25519 temporária descartável, sem servidor real,
  sem instalação automática no Minecraft e sem alterar a produção.

**Ainda falta para a atualização TOTALMENTE automática:**
1. Publicar releases protegidas e offline-assinadas na homologação com permissões
   verificadas pela API, mais migração da tabela privada.
2. Validar staging real com token autenticado, inclusive revogação.
3. Implementar registro de arquivos **gerenciados pelo Bootstrap**, troca
   transacional após fechamento do Minecraft, backups e rollback;
   **nunca** sobrescrever um JAR instalado manualmente.
4. Resolver autenticação para a etapa pós-fechamento sem persistir tokens
   no disco, instalar no máximo uma versão ativa por ID Fabric.
5. Teste end-to-end em instância Windows/Fabric 1.21.1 separada, com os
   quatro mods protegidos e atualização independente do HYPE Client.
6. Automatizar obfuscação no processo de build isolado, com relatórios de
   integridade e revisão. A assinatura privada continua sob custódia segura.
   Ofuscação **não impede completamente engenharia reversa**. Permissões
   de recursos sensíveis devem ser verificadas no servidor, inclusive
   para jogadores com o JAR já copiado no computador.

Dependências: PR #78 (Bootstrap 0.6 e login) e PRs #77/#79 (API e publicação).
Todos continuam em revisão. Flags OFF por padrão; não ligar nada na produção.

### Primeira instalação com desfazimento automático (prova isolada)

Adicionado `PrivateFirstInstallTransaction.java` — **não vinculado ao jogo
nem à inicialização automática**. Exige `after_exit` como opt-in local,
uma prova externa de jogo encerrado e uma verificação de autorização
fornecida pelo chamador. **A prova e a autorização ainda NÃO são implementadas
por um processo real**, e os testes usam callbacks simulados: não ativar
em produção.

- Revalida a assinatura Ed25519 e o SHA-256 do JAR privado preparado.
- Impede sobrescrever mods manuais; instala apenas quando não existe
  nenhum JAR com aquele ID Fabric. O JAR protegido é criado por link exclusivo
  dentro de `mods/` (falha fechado em filesystem sem hardlinks).
- Cria um marcador local sem tokens em `.hype-private-managed/`.
- Se surgir erro de escrita, falha provocada ou revogação antes de concluir,
  remove somente o novo arquivo criado pela própria transação.
- Não adota automaticamente JAR preexistente nem substitui versões já
  gerenciadas. **Recuperação de queda abrupta de energia ainda não garantida.**
- Não oferece instalador pós-fechamento real, prova de encerramento do processo,
  revalidação da autorização no servidor, reentrada do jogador nem integração
  com o atualizador HYPE Client.

**Testes locais (Java 21, 22/11/2026): 19 verificações aprovadas** com o
JAR real protegido da Pokédex Beta 8 e assinatura Ed25519 descartável.
O teste `PrivateFirstInstallTransactionTest.java` só lê esse JAR do caminho
local informado, nunca publica o binário e não acessa Render/Supabase.

**Próximos passos:** implementar autenticação segura do instalador pós-saída
sem guardar Bearer; transação de upgrade de versões previamente gerenciadas
com backup e rollback; recuperação de queda, locks e teste real no Windows.

### Upgrade de versão já gerenciada + recuperação (22/11/2026)

Novo código: `PrivateManagedUpgrade.java`, com testes em
`test/br/clanhype/bootstrap/PrivateManagedUpgradeTest.java`.

- Troca **somente** um mod que já tenha `.hype-private-managed/{id}.state`,
  arquivo antigo íntegro e SHA-256 exato, sem outro JAR com mesmo ID Fabric.
- O catálogo, manifesto e JAR protegido da nova versão são validados antes
  de qualquer alteração pela `PrivateInstallPlanner`.
- Com `after_exit` opt-in, callbacks de jogo encerrado e autorização ativa
  (ainda **simulados nos testes**, NÃO conectados ao servidor), a rotina
  prepara o backup privado, cria um journal de transação e a nova versão
  exclusivamente, atualiza o marcador e remove só o JAR antigo gerenciado.
- Falha ou revogação durante a operação restauram o estado anterior.
  O backup é preservado para inspeção/rollback.
- `recoverPending` recupera uma atualização abruptamente interrompida
  restaurando o backup anterior, desde que os arquivos passem nos hashes.
  **Precisa ser chamado pelo launcher/agent ANTES da descoberta de mods
  pelo Fabric; ainda não está integrado**. O Minecraft poderia falhar
  se o usuário o abrisse durante uma recuperação pendente.
- Um `.pending` impede outra tentativa de atualização mesmo que o novo
  SHA já pareça instalado. O usuário não deve apagar journals manualmente.
- Não atualiza o HYPE Client ou o próprio Bootstrap nesta etapa.
  Eles exigem canais assinados próprios e agente externo pós-saída.

**Teste local:** Java 21, arquivo protegido real da HYPE Pokédex Beta 8 e
chaves Ed25519 temporárias: **38 verificações aprovadas**, incluindo
troca, backup, rollback, revogação, adulteração, duplicatas e recuperação
simulada de queda. Sem rede, sem Windows/Minecraft real, sem deploy.

**ATENÇÃO:** a implementação ainda é **experimento desconectado**.
Não chamar na inicialização Fabric, não distribuir como atualizador
completo. O callback de autorização usado nos testes NÃO substitui
consulta real às permissões no site. A chave privada de produção
nunca deve ir para o site ou para o JAR.

### Simulação dos quatro mods HYPE (somente estrutura)

O teste `PrivateMultiModUpgradeTest.java` cria builds **sintéticos**
para os quatro módulos privados da HYPE e percorre instalação inicial,
backup e troca de versão no mesmo diretório de Minecraft descartável.
**25 verificações locais aprovadas** no Java 21 (sem rede).
Isso prova a generalidade do instalador para IDs Fabric distintos, mas
**não comprova que os JARs reais dos outros três mods funcionem**.
A Pokédex Beta 8 protegida foi testada separadamente com o artefato real.

Fluxo automático desejado, **ainda não conectado**:
1. Bootstrap instala o HYPE Client público assinado e aguarda reinício;
2. HYPE Client autentica o jogador; backend autoriza cada mod privado;
3. Bootstrap prepara as versões assinadas, sem alterar JAR em uso;
4. Agente externo mantém credenciais temporárias apenas em memória,
   aguarda fechamento real do Minecraft, revalida a permissão no site,
   e aplica as transações com backup/rollback;
5. Agente pré-lançamento recupera `.pending` antes de o Fabric buscar mods;
6. Atualização do HYPE Client e do próprio Bootstrap usam seus canais
   públicos assinados, pois o Bootstrap não pode substituir-se em uso.
A obfuscação automatizada exige build isolado, sem chave privada no servidor.
Nenhuma dessas etapas deve ser habilitada em produção antes de homologação.
