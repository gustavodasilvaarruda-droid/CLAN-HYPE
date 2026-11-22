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
