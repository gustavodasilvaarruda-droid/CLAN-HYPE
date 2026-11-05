# HYPE Client → Site HYPE: envio de pedidos Breed (primeira integração)

**Estado:** proposta de implementação para revisão. A aplicação no site em produção e o envio do JAR do Minecraft ainda NÃO foram ativados.

## Fluxo

1. O jogador se autentica com a própria conta HYPE já cadastrada em `POST /api/hype/v1/login`.
2. Na Etapa 5 do HYPE Client, ele confirma o pedido e recebe um `request_id` UUID v4, que precisa permanecer o mesmo enquanto o cliente repetir esse envio.
3. O mod faz `POST /api/hype/v1/pedidos` por HTTPS, enviando `Authorization: Bearer <token>`.
4. O servidor confere a conta vinculada ao token, permissão para Breed, campos, forma regional, Pokémon bloqueados, cooldown, pedidos repetidos e regras de preço.
5. O banco recebe um pedido em `public.pedidos_breed` com `status=pendente`. A resposta traz o ID do pedido do site e o preço oficial.
6. O mesmo pedido aparece em *Meus Pedidos* e, se for elegível, na fila de breeders. O pagamento não é confirmado pelo mod.

**NUNCA distribuir `SUPABASE_KEY`, `SECRET_KEY` nem credenciais do banco dentro do JAR.**

## Ordem de implantação

- [ ] Fazer backup do banco e aplicar `sql/20261105_hype_client_breed_request_id.sql` no Supabase.
- [ ] Rever e integrar a ramificação / PR no GitHub.
- [ ] Publicar pelo Render; verificar `GET /api/hype/v1/health`.
- [ ] Validar em ambiente controlado com uma conta de teste.
- [ ] Adicionar o botão de envio real no HYPE Client. Desabilitar enquanto aguarda a resposta e manter o mesmo UUID v4 em caso de timeout/retry.
- [ ] Somente depois habilitar o fluxo para todos os jogadores.

## Pedido de exemplo (não execute em produção sem conta de teste)

```http
POST /api/hype/v1/pedidos
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "request_id": "03a5de4c-2135-4823-9779-a0cef62c6797",
  "pokemon_id": 10066,
  "pokemon": "rapidash-galar",
  "regiao": "galar",
  "nature": "Jolly",
  "ha": false,
  "genero": "indiferente",
  "breed_tipo": "F5",
  "iv_descartado": "ataque_especial",
  "zero_speed": false,
  "treinado": false,
  "evs_treinamento": {},
  "ivs_personalizados": {},
  "cupom_breed": ""
}
```

Para formas regionais, o ID deve vir do catálogo oficial de formas em `static/breed_regional_forms.json`: **não** enviar o ID da espécie base com somente um rótulo regional. Por exemplo, o servidor transforma o ID regional na grafia canônica `rapidash-galar` e mantém o ID no pedido.

Um pedido personalizado requer `breed_tipo: "PERSONALIZADO"` e exatamente seis IVs em `ivs_personalizados`, cada um entre 0 e 31. Treinamento exige `treinado: true` e EVs até 252 por atributo, no máximo 510 no total.

## Resposta

- **201:** `{"ok":true,"repetido":false,"pedido":{"id":123,"status":"pendente","pokemon":"rapidash-galar","preco_total":600000}}`
- **200 (retry idempotente):** `{"ok":true,"repetido":true,"pedido":{"id":123,"status":"pendente","preco_total":600000}}`
- **401:** token ausente, expirado ou inválido.
- **403:** conta sem permissão.
- **409:** pedido ativo idêntico ou `request_id` reutilizado indevidamente.
- **422:** Pokémon, forma regional, IVs, EVs, Nature, cupom ou outro campo inválido.
- **429:** respeitar cooldown de 2 minutos entre pedidos.
- **503:** erro interno. **Antes de tentar novamente, consultar Meus Pedidos**; não gerar outro UUID automaticamente.

## Proteções

- O preço, comissão, status, player e usuário são determinados no servidor, não aceitos do Minecraft.
- A API reutiliza os validadores e a classificação oficial do site.
- O banco tem uma restrição única para o UUID de origem, protegendo contra reenvio acidental.
- Não aceitar pedidos de Ditto, lendários/míticos e Pokémon não disponíveis para Breed.
- O mesmo token é utilizado pela API existente do HYPE Client, com expiração.
- Sem acesso direto do mod ao banco; sem cobrança automática; sem confirmação de pagamento.
