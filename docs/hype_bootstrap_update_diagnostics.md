# Diagnóstico do Bootstrap e das atualizações de múltiplos mods

Esta implementação adiciona **apenas diagnóstico de leitura**; não publica JARs,
não ativa chaves do Render, não altera Supabase e não substitui o Bootstrap
instalado nos computadores.

## 1. Diagnosticar o canal ativo

`GET /hype-updates/mods/health` retorna HTTP 200, sempre com
`Cache-Control: no-store`, sem caminhos privados, tokens ou nomes de rascunhos.

Campos:

- `mode`: `auto-signed`, `legacy-signed` ou `disabled`.
- `catalogue_enabled`: o canal de catálogo está habilitado.
- `downloads_enabled`: o servidor está configurado para permitir downloads.
- `catalogue_valid`: assinatura/estrutura de catálogo validada.
- `ready`: catálogo não vazio, validado, com switches de downloads habilitados.
- `reason`: código de diagnóstico, sem informações confidenciais.
- `revision`: os 16 primeiros caracteres do SHA-256 do catálogo assinado,
  presentes somente após validação bem-sucedida.
- `mod_count`: total de entradas do catálogo validado, não total dos uploads.
- `binary_contents_checked: false`: este diagnóstico **não** verifica os JARs
  no Storage e **não** comprova que o Minecraft aplicou a atualização.

Códigos possíveis: `disabled`, `auto_switches_incomplete`,
`release_db_unavailable`, `auto_catalogue_unavailable`,
`legacy_catalogue_unavailable`, `legacy_public_modules_restricted`,
`downloads_disabled`, `empty_catalogue`, `ok`.

O catálogo completo continua em `GET /hype-updates/mods/catalog.json`.
Quando servido, expõe `X-HYPE-Catalog-Revision` com o mesmo prefixo SHA-256.
Os endpoints de JAR permanecem inalterados.

**Atenção:** um upload na Biblioteca não significa uma release aprovada. O
canal automático público só deve ser habilitado para arquivos autorizados para
distribuição pública. Nunca habilitar as flags só para resolver o aviso do
Bootstrap se houver mods restritos. Para builds protegidas e aprovadas,
considerar a opção de homologação do PR #121.

## 2. Investigar a pasta mods do Windows

No launcher utilizado pelo jogador, localizar a **pasta da instância** e seu
subdiretório `mods` (não presumir que seja `%APPDATA%\.minecraft\mods`).
No caso do Planeta Launcher, a instância costuma ficar em pasta própria.

Procedimento seguro:

1. Fechar Minecraft e todos os processos Java relacionados à instância.
2. Guardar backup da pasta `mods` fora da instância.
3. Anotar Fabric ID, versão e SHA-256 de cada JAR HYPE presente. A fonte
   confiável para o ID é `fabric.mod.json` dentro do JAR, não o nome do arquivo.
4. Conferir duplicatas de um mesmo Fabric ID, inclusive JARs com nomes antigos.
5. Conferir `logs/latest.log` após a verificação do Bootstrap; mensagens
   como `All published mods are current` não provam igualdade de SHA.
6. Comparar cada SHA **instalado** com o SHA correspondente do catálogo
   **assinado** oferecido ao cliente.
7. Se forem diferentes, verificar se houve download verificado, staging,
   instalação após saída, backup e novo SHA na próxima inicialização.

Uma nova build pode manter a mesma string `version`; o Bootstrap precisa
comparar o **SHA-256 de cada módulo**, não apenas a string da versão, para
reconhecer os hotfixes. O nome do arquivo JAR também não é identificador
confiável de módulo.

## 3. Requisitos do Bootstrap (a validar no JAR ativo)

- Atualização seletiva para cada Fabric ID presente no catálogo.
- Redownload quando o SHA publicado muda, **mesmo com versão igual**.
- Download em arquivo temporário, validação Ed25519, tamanho, SHA-256 e
  `fabric.mod.json` antes de disponibilizar a troca.
- Nunca sobrescrever um arquivo em uso pelo Minecraft.
- Instalador pós-saída deve esperar o processo correto terminar, realizar
  backup, trocar por rename atômico quando viável e garantir rollback.
- Logs devem distinguir: `catálogo inacessível`, `nenhuma release`,
  `SHA igual`, `download concluído`, `aguardando saída`,
  `substituído`, `rollback` e `falha`.
- Não baixar nem executar arquivos de URL que não corresponda exatamente ao
  catálogo assinado, e não salvar credenciais de sessão em logs.
- Respeitar permissões dos módulos; catálogo público não é canal de
  distribuição para recursos privados sem autorização.

## 4. Teste de homologação recomendado

Usar uma instância Fabric 1.21.1 separada. Publicar uma build de teste
explicitamente autorizada no canal **de homologação**, manter cópia do JAR
antigo, mudar os bytes sem necessariamente mudar a versão, iniciar o jogo,
esperar verificação, sair e reabrir. Só considerar aprovado quando o SHA no
`mods` após reabrir for exatamente o SHA esperado e o Minecraft carregar o
mod. Repetir com rede indisponível, arquivo corrompido e interrupção de
instalação para garantir rollback.

**Limitação:** estes testes do próprio instalador requerem o JAR ativo do
Bootstrap 1.6.2 ou as fontes correspondentes. O novo endpoint sozinho não
corrige os computadores.
