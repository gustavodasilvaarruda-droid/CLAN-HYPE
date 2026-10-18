# HYPE Client R7 — Etapa 2: API de estados e permissões

Esta proposta usa a API já existente em `modules/hype_client_api.py` e adiciona somente uma **leitura autenticada**, sem modificar pedidos de Breed, dados do usuário, SQL ou o estado do banco.

## Rota
`GET /api/hype/v1/modulos`, com `Authorization: Bearer <token>` obtido em `POST /api/hype/v1/login`.

Resposta 200 (exemplo, não representa dados reais):

```json
{"ok":true,"modulos":[{"codigo":"pokedex","nome":"HYPE Pokédex","estado":"ativo","permitido":true,"motivo":"cargo_permitido","versao":"0.1.0","descricao":"","icone":"book","categoria":"competitivo"}]}
```

Token ausente ou inválido: 401. Erro em qualquer consulta de tabelas: 503 (falha fechada, sem indicar liberação). Nenhuma informação de credenciais, chaves Supabase ou motivos internos do administrador é enviada ao cliente.

## Política de acesso

1. Módulo `desativado` ou em `manutencao` jamais permite acesso, mesmo com autorização manual.
2. `bloquear` individual vigente prevalece sobre cargo.
3. `permitir` individual vigente concede acesso se o módulo está globalmente ativo.
4. Permissão por cargo só vale se houve correspondência explícita na tabela de grupos.
5. `membro` representa conta cadastrada. Cargos especializados e `membro_hype` requerem vínculo ativo do clã.
6. Concessões futuras ou expiradas não têm efeito; campos de data inválidos não liberam.
7. `visivel=false` oculta o módulo da resposta.
8. Todas as verificações usam os dados atuais do banco; não se deve confiar permanentemente em decisões guardadas no cliente.

## Pré-requisitos

- Flask e dependências já listadas em `requirements.txt`.
- Tabelas já previstas na migração do Mod Manager: `hype_modulos`, `hype_modulos_grupos`, `hype_modulos_acessos`.
- Uma `SECRET_KEY` forte, configurada no ambiente do Render e **não no JAR**.
- Evite instalar/rodar novamente o arquivo SQL consolidado de instalação completa num banco existente.

## Testes

```bash
python -m unittest discover -s tests -p 'test_hype_mod_access.py' -v
```

A lógica pura foi submetida a 14 testes unitários offline, todos aprovados no ambiente de desenvolvimento desta etapa.

### Pendências de produção

Ainda é necessário verificar um deploy de homologação, a tabela real no Supabase, autenticação no Render e o consumo do endpoint no mod R7. O endpoint por si só **não** fecha telas, interrompe batalhas ou desliga o motor no JAR já instalado. Isso requer atualização cliente e checks por operação. O painel admin de escrita, logs e aprovações permanece como etapa separada.

**Não habilitar tudo em produção antes da validação.**
