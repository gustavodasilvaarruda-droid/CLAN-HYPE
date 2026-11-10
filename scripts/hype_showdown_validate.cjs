'use strict';
// Bridge privada: recebe só a equipe e o ID do formato via stdin, nunca via navegador.
// O TeamValidator oficial do Pokémon Showdown é a única fonte da validação completa.
const fs = require('node:fs');
function reply(status, errors = []) {
  process.stdout.write(JSON.stringify({
    status,
    errors: (Array.isArray(errors) ? errors : []).slice(0, 20).map(x => String(x).slice(0, 250))
  }) + '\n');
}
try {
  const input = fs.readFileSync(0, {encoding: 'utf8'});
  if (input.length > 65536) {reply('unavailable', ['Payload muito grande']); process.exit(0);}
  const data = JSON.parse(input);
  if (!/^[a-z0-9]{3,64}$/.test(String(data.format || '')) ||
      !Array.isArray(data.slots) || data.slots.length > 6 || data.slots.length === 0) {
    reply('unavailable', ['Entrada inválida']); process.exit(0);
  }
  const {TeamValidator} = require('pokemon-showdown');
  const formatid = data.format;
  const team = data.slots.map(s => {
    if (!s || typeof s !== 'object') throw Error('Set inválido');
    const evs = {}, ivs = {};
    for (const stat of ['hp','atk','def','spa','spd','spe']) {
      evs[stat] = Number.isInteger(s.evs?.[stat]) ? s.evs[stat] : 0;
      ivs[stat] = Number.isInteger(s.ivs?.[stat]) ? s.ivs[stat] : 31;
    }
    const set = {
      name: String(s.pokemon || '').slice(0,80),
      species: String(s.pokemon || '').slice(0,80),
      item: String(s.item || '').slice(0,100),
      ability: String(s.ability || '').slice(0,100),
      nature: String(s.nature || 'Serious').slice(0,40),
      moves: Array.isArray(s.moves) ? s.moves.slice(0,4).map(m => String(m).slice(0,100)) : [],
      evs, ivs, level: Number.isInteger(s.level) ? s.level : 100,
    };
    // A Terastalização é uma escolha de batalha; o tipo ainda precisa ser legal.
    if (s.tera_type) set.teraType = String(s.tera_type).slice(0,30);
    if (s.gender === 'M' || s.gender === 'F') set.gender = s.gender;
    return set;
  });
  const validator = typeof TeamValidator.get === 'function'
    ? TeamValidator.get(formatid) : new TeamValidator(formatid);
  const errors = validator.validateTeam(team);
  reply(errors && errors.length ? 'illegal' : 'legal', errors || []);
} catch (_) {
  // Não envia stack trace, caminho local ou segredos ao cliente.
  reply('unavailable', ['Validador Showdown indisponível; requer conferência manual']);
}
