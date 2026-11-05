# HYPE Client — Fazer Pedido (integração inicial)

Esta mudança prepara o formulário do mod para usar o mesmo catálogo, as mesmas
regras e o mesmo cálculo de preço do site. É uma etapa de **desenvolvimento**;
não altera a produção até revisão e merge.

## Contrato da API (Bearer da rota `/api/hype/v1/login`)

Todas as requisições abaixo exigem `Authorization: Bearer <token>` e a
permissão `pode_fazer_pedido_breed`. O token expira após quatro horas.

### 1. Busca

`GET /api/hype/v1/breed/pokemon/buscar?q=salamence`

Resposta `200`:
```json
{"ok":true,"results":[{"id":373,"name":"salamence","display_name":"Salamence"}]}
```

A interface Minecraft deve mostrar o modelo **3D local do Cobblemon**,
nunca depender de um sprite da API para renderizar o Pokémon.

### 2. Regras da espécie

`GET /api/hype/v1/breed/pokemon/373?nome=Salamence`

Confere se a espécie é breedável, informa bloqueios, categoria e
dependência de Ditto. O cliente deve impedir avanço se `breedavel=false`.

### 3. Prévia de preço oficial

`POST /api/hype/v1/breed/preco-preview`
Content-Type: `application/json`

```json
{
  "pokemon_id": 373,
  "pokemon": "Salamence",
  "breed_tipo": "F5",
  "nature": "Adamant",
  "ha": false,
  "genero": "indiferente",
  "iv_descartado": "defesa",
  "zero_speed": false,
  "treinado": false,
  "cupom": ""
}
```

Resposta: `ok`, `preco_total`, `preco_formatado`, `detalhes` (componentes,
promoções, cupons, tabela vigente), `categoria` e `so_com_ditto`.
**Nunca confiar no preço recebido do Minecraft para gravar um pedido.**

O servidor usa `regra_breed_pokemon`, `classificar_pokemon_preco` e
`calcular_preco_breed` de `app.py`, as mesmas funções usadas no envio web.

## Fluxo de telas definido pelo usuário

1. **Pokémon:** busca, cartões selecionáveis, borda dourada/laranja, painel
   de informações e modelo 3D real, com giro e zoom.
2. **Características:** Nature, HA, gênero, F5/F6/Hidden Power Ability,
   sem sobreposições de texto.
3. **IVs e extras:** F5 exige IV dispensável; Zero Speed exige outro IV
   dispensável; personalizado com seis IVs 0–31; EVs no máximo 252 por
   atributo e 510 no total.
4. **Revisão:** resumo, cupom, componentes e recálculo oficial do preço.
5. **Envio:** confirmação na API do site e retorno do ID único do pedido.

### Fase atual

A **etapa 1 da API e a prévia de preço** estão implementadas nesta branch.
A rota de criação **não existe** ainda: o botão Enviar Pedido deverá
permanecer desabilitado até que haja operação autenticada com validação,
anti-spam, prevenção de duplicatas, idempotência e preço recalculado
no próprio envio.

O mod Alpha 4 precisa ser editado separadamente para remover UI duplicada e
substituir o espaço reservado pelo renderizador do Cobblemon. **Este branch
não é um JAR do Minecraft.** A interface deve permanecer coerente com o
site no fluxo e com a identidade visual HYPE (preto e dourado).

## Verificação

```bash
python -m unittest discover -s tests -p 'test_hype_client_breed_api.py'
```

Os testes usam Flask mockado sem conexão Supabase real. Antes de disponibilizar
para jogadores, validar integração em ambiente de homologação e regressão
dos pedidos web existentes.
