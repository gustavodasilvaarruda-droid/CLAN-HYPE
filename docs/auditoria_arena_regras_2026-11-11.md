# Auditoria Arena HYPE — regras do Team Builder e torneios
**Data:** 11/11/2026  
**Escopo:** 28 formatos de Geração 9, 1.518 espécies/formas do snapshot competitivo e 587 IDs de itens extraídos do catálogo Pokémon Showdown.

## Regras preliminares cobertas no servidor
- Tamanho da equipe por formato; até três times privados por torneio; formato imutável após vínculo ao evento.
- Espécies proibidas por nome/tier, indisponibilidade da geração, Little Cup (estágio + nível 5), NFE.
- **Same Type Clause (Monotype e National Dex Monotype)**: interseção dos tipos dos Pokémon, inclusive alterações de Mega Evolution e Ultra Necrozma.
- Species Clause por espécie-base, inclusive formas (por exemplo, Rotom-Wash/Rotom-Heat).
- Item Clause quando ativada no regulamento, itens da banlist, identidade e geração do item, Poké Balls de captura.
- Items obrigatórios: Plates de Arceus, Blue Orb/Red Orb para formas Primal e as três Masks de Ogerpon.
- Mega Stones (espécie correta, forma Mega permitida), Z-Crystals e regras das mecânicas declaradas.
- Banlists explícitas e expansão das cláusulas Showdown: Sleep Moves, Evasion Abilities, Evasion Items, Evasion Moves, Accuracy Moves e OHKO.
- Quatro golpes distintos, nature, ability presentes, limites de EV/IV, Terastalização conforme formato.
- Novo alerta para times legados já enviados que ficaram incompatíveis: não altera time salvo. Bloqueio de aprovação/inscrição se a nova pré-checagem falhar.

## Interface
- Team Builder indica incompatibilidades de Monotype antes de salvar, banimentos preliminares de habilidade, item e movimento.
- Catálogo de 587 itens carregado sob demanda, além das sugestões estratégicas; filtros de itens de captura, itens passados/futuros, banlist e exigências por forma.
- Alterar formato continua solicitando confirmação antes de remover espécies incompatíveis; builds já salvas não são apagadas automaticamente.
- Administração e jogador visualizam o motivo quando um time já enviado não passou na checagem.

## Limitações e trabalho pendente
A checagem é **preliminar**, não uma validação competitiva completa. Não deve substituir o **TeamValidator oficial do Pokémon Showdown**, que continua necessário antes de aprovar um time para jogo.
1. Checar correspondência exata de **golpes por espécie, geração e origem**, incluindo tutores, ovos, transferências, eventos, egg moves e combinações de moves.
2. Checar **habilidades reais por espécie/forma**, hidden abilities, restrições de origem e evolução.
3. Resolver bans e unbans herdados complexos, times com regras customizadas e legalidade de **forma + item + habilidade + golpe** em todas as gerações.
4. Implementar cláusulas dependentes de **combinações e efeitos de batalha** (ex.: Gravity Sleep Clause, Endless Battle Clause); não inferir sua validação apenas por texto.
5. Vincular resultado rastreável do TeamValidator à revisão administrativa, conforme formato exato do torneio. **Não automatizar aprovação final** sem esse passo.
6. Atualizar e versionar periodicamente o snapshot Showdown de tiers, espécies, itens e formatos, porque banlists mudam.

**Fontes:** `data/hype_showdown_gen9_snapshot.json` (snapshot versionado), `data/hype_showdown_items_snapshot.json` (Showdown items.ts), `modules/arena_private_teams.py`, `modules/events_v26.py`.

**Testes:** `tests/test_hype_arena_private_teams.py`, `tests/test_hype_team_builder_ui.py`.  
