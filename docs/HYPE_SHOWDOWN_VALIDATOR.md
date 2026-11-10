# HYPE Arena — validação oficial Pokémon Showdown

A lista de formatos e o pré-filtro do Team Builder são alimentados pelo snapshot versionado. **Esses dados não comprovam legalidade de sets**. Para avaliar habilidades, movimentos obtidos por transferência, formas, itens, tiers e regras especiais, a Arena usa o `TeamValidator` oficial do pacote `pokemon-showdown` (versão fixada no `package.json`).

## Instalação de teste
No diretório do projeto: `npm install --omit=dev --no-audit --no-fund`. Requer Node.js 20+ e Python já configurado. A instalação é opcional até a homologação. A migração do Supabase não é alterada por esta integração.

No Render, **primeiro conferir a presença de Node.js e os comandos de build existentes**. Acrescentar `npm install --omit=dev --no-audit --no-fund` ao build somente após validar que a instalação de dependências Python continua funcionando e que há espaço/recursos. Não substituir `pip install -r requirements.txt` por npm.

## Comportamentos
- `legal`: o TeamValidator do formato não apontou infrações; a equipe **continua aguardando revisão do torneio**, nunca inscrição automática.
- `illegal`: erros oficiais são apresentados e o envio é bloqueado.
- `unavailable`: quando Node, pacote, formato ou processo falha, não se declara legalidade; o time pode seguir somente com estado `aguardando_verificacao` para análise humana, nunca aprovação automática.

A ponte `modules/hype_showdown_bridge.py` só executa um script local e não envia times privados a servidores externos. O processo filho não recebe credenciais do Supabase.

## Homologação obrigatória
Testar Gen 9 OU, Ubers, LC, National Dex e Monotype usando times reais válidos e inválidos, incluindo Mega Metagross, Miraidon no NatDex Ubers, Abomasite em Garchomp, Tera, Z-Moves, Ability e Move inexistente. Conferir se o formato de cada torneio é preservado durante a inscrição, se a tela de administração continua privada e se a política de aprovação não foi alterada. O nome do formato no catálogo deve corresponder ao formato suportado na versão do pacote instalada.

**Não fazer deploy em produção só porque os testes de contrato passaram.** Os testes reais de integração precisam ser executados com a biblioteca Showdown instalada e com o Supabase do ambiente de homologação.
