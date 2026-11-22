# HYPE Bootstrap 0.5 — piloto, NÃO liberar

Proposta de continuação do HYPE Bootstrap 0.4, baseada no JAR-piloto fornecido pelo administrador. Minecraft 1.21.1 / Fabric / Java 21.

**Este código NÃO está implantado, NÃO deve substituir o Client em produção e NÃO executa atualizações por padrão.** Os testes locais foram feitos com JARs sintéticos, não dentro do Minecraft.

- `update_mode=off` (padrão): nenhuma atualização nem solicitação de rede.
- `update_mode=stage`: chama StageDownloader 0.4 para consultar o endpoint HTTPS oficial, verificar catálogo Ed25519 e SHA-256 e preparar os downloads, sem instalar.
- `update_mode=after_exit`: chama AfterExitPilot 0.4, que prepara o agente externo de instalação após fechamento do jogo. Usar somente em homologação.

O arquivo de configuração, quando existir, fica em `config/hype-bootstrap.properties`. Só é aceita a chave `update_mode`. Não é possível definir uma URL alternativa ou desabilitar a assinatura.

**O JAR 0.4 e seus módulos de verificação/instalação não estão neste repositório.** Para reconstruir o piloto 0.5, use o ZIP de fontes e testes entregue ao administrador junto ao JAR base 0.4. Essas classes novas são intencionalmente pequenas e compatíveis com o 0.4.

Antes da próxima fase: persistir releases e JARs aprovados no Storage, preparar catálogo assinado offline, testar autorização, versões individuais, dependências externas, rollback e a integração real no Fabric. Não ativar as flags do catálogo multi-mod em produção.
