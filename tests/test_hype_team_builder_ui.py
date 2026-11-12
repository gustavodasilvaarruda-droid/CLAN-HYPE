"""Regressões do Team Builder: formatos, itens e privacidade do torneio."""
import ast
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from modules.arena_private_teams import validar_equipe_basica
from modules.hype_tournament_formats import obter_formato, obter_regras_especie_showdown

ROOT = Path(__file__).resolve().parents[1]


class TestHypeTeamBuilderUX(unittest.TestCase):
    def test_builder_route_parses_and_locks_tournament_format(self):
        source = (ROOT / 'modules/expansion_features.py').read_text(encoding='utf-8')
        ast.parse(source)
        self.assertIn('for preset in formatos_disponiveis():', source)
        self.assertIn("codigo_formato_do_torneio(torneio.get('regras'))", source)
        self.assertIn('formato_codigo = torneio_formato_codigo or', source)
        self.assertIn('torneio_formato_codigo=torneio_formato_codigo', source)

    def test_template_compiles_and_shows_visual_search(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=True)
        self.assertIsNotNone(env.get_template('team_builder.html'))
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        for marker in ('id="itemSelectedIcon"', 'id="itemOptions"',
                       'id="pokemonOptions"', 'role="combobox"',
                       'id="formatSelect"', 'name="torneio_id"'):
            self.assertIn(marker, template)
        self.assertNotIn("fetch('https://pokeapi.co/api/v2/item?limit=2500')", template)
        self.assertIn('hype_team_builder_modern.css', template)
        for marker in ('id="showAllItems"', 'showAllHeldItems=false',
                       'function allowedHeldItems()', 'recommendations.includes(code)'):
            self.assertIn(marker, template)
        self.assertIn('disabled aria-label="Formato fixo do torneio"', template)
        # Exportação em texto Showdown, sem afirmar aprovação automática.
        for marker in ('id="exportShowdownBtn"', 'id="showdownExportText"',
                       'exportShowdownText()', "rows.push('EVs: '+ev)",
                       'A exportação não comprova a legalidade da equipe'):
            self.assertIn(marker, template)
        for marker in ('evRemaining', 'limitEvInput', 'selectableItems', 'data-edit-build', 'data-preview-build', 'data-duplicate-build', 'id="teraEnabled"', 'recommendedItems', 'teamSize', 'refreshMegaDisplay'):
            self.assertIn(marker, template)

    def test_build_actions_are_grouped_and_all_existing_controls_remain(self):
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        css = (ROOT / 'static/hype_team_builder_modern.css').read_text(encoding='utf-8')
        self.assertIn('id="hypeBuildManagementTitle">Builds salvas', template)
        self.assertIn('id="hypeTeamActionsTitle">Ações do time', template)
        self.assertIn('id="builderValidation"', template)
        self.assertIn('hype_team_builder_modern.css', template)
        for action in ('savedBuildSelect', 'loadBuildBtn', 'hypeBuildSelect',
                       'loadHypeBuildBtn', 'duplicateSlotBtn', 'saveBuildBtn',
                       'newBuildBtn', 'reviewTeamBtn', 'importShowdownBtn',
                       'exportShowdownBtn'):
            self.assertEqual(template.count(f'id="{action}"'), 1, action)
        self.assertIn('hype-build-source-grid', css)
        self.assertIn('hype-team-action-grid', css)
        self.assertIn('@media (max-width:680px)', css)

    def test_format_change_filters_roster_and_sets_level_defaults(self):
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        for marker in (
                'function changeBuilderFormat()', 'previousFormatCode',
                'const invalid=slots.map', 'speciesRestriction(s.pokemon)',
                "if(!confirm('Mudar para '", 'invalid.forEach(x=>slots[x.i]=emptySlot())',
                'slots.forEach(x=>{x.level=level;})',
                'if(f.little_cup)return 5', 'formatDefaultLevel(selectedFormat())',
                'pokemonNames.filter(n=>!speciesRestriction(n))',
                'slots.filter(s=>s.pokemon).forEach(loadShowdownMovesForSlot)',
                "if(!f)return ''", 'id="levelFormatHelp"'):
            self.assertIn(marker, template)
        self.assertIn("field.value=previousFormatCode;renderEditor();renderTabs();return;", template)

    def test_move_selection_is_bilingual_legal_and_responsive(self):
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        css = (ROOT / 'static/hype_team_builder_modern.css').read_text(encoding='utf-8')
        for marker in (
                'id="abilityHelp"', 'hype-move-type-indicator', 'hype-move-details-toggle',
                'hype-move-options', 'function renderMoveChoices(input)',
                'function showMoveDetails(input)', 'function updateSelectedMoveVisuals()',
                'function moveLearningMethod(move)', 'const moveEffectsPT=',
                "leafstorm:'Causa dano", "amnesia:'Aumenta", 
                "const abilityEffectsPT=", "drizzle:'Invoca chuva",
                'methodSources={}', 'move_methods=Object.fromEntries',
                'function allowedMoves(list)', 'moveDisplayName(move)',
                "fetch('https://play.pokemonshowdown.com/data/moves.json')"):
            self.assertIn(marker, template)
        for marker in ('.hype-move-grid', '.hype-move-info', '.hype-move-options',
                       '.hype-move-option-type', 'max-width:720px', '.hype-ability-help'):
            self.assertIn(marker, css)
        # Os quatro campos são renderizados pelo laço Jinja original.
        self.assertIn('{% for i in range(1,5) %}', template)

    def test_saved_teams_rehydrate_learnsets_on_open(self):
        template=(ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        self.assertIn('slots.filter(s=>s.pokemon).forEach(loadShowdownMovesForSlot);', template)
        self.assertIn('if(current().pokemon&&!current().abilities?.length)loadPokemonDetails(current().pokemon);', template)
        self.assertIn('if(!current().abilities?.length)loadPokemonDetails(current().pokemon);else loadShowdownMovesForSlot(current());', template)

    def test_species_rules_and_ability_preview_are_integrated(self):
        from modules.hype_tournament_formats import obter_regras_especie_showdown
        self.assertIn('Chlorophyll', obter_regras_especie_showdown('Bulbasaur')['abilities'])
        self.assertIn('Buginium Z', obter_regras_especie_showdown('Arceus-Bug')['requiredItems'])
        template=(ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        routes=(ROOT / 'modules/expansion_features.py').read_text(encoding='utf-8')
        for marker in ('function bootSpeciesRules()', "function allowedSpeciesAbilities(pokemon,item='',mechanic='')",
                       'function requiredFormHeldItems(pokemon)',
                       'Habilidades que não pertencem ao Pokémon:',
                       'requiredFormHeldItems(s.pokemon)',
                       'bootSpeciesRules();'):
            self.assertIn(marker, template)
        self.assertIn('def team_builder_species_rules_snapshot():', routes)

    def test_inline_javascript_parses_in_node_when_available(self):
        if not shutil.which('node'):
            self.skipTest('Node indisponível neste ambiente')
        template=(ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        js=template.split('<script>',1)[1].split('</script>',1)[0]
        js=re.sub(r'{{[^{}]*}}', 'null', js)
        result=subprocess.run(['node','--check'], input=js, text=True,
                              capture_output=True, timeout=12)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_import_showdown_two_charizards_and_invalid_evs(self):
        template = (ROOT / 'templates/team_builder.html').read_text(encoding='utf-8')
        for marker in ('id="importShowdownBtn"', 'id="importShowdownSidebarBtn"', 'id="showdownImportDialog"',
                       'id="showdownImportText"', 'id="showdownImportPreview"',
                       'id="confirmShowdownImport"', 'function parseShowdownTeam(raw)'):
            self.assertIn(marker, template)
        if not shutil.which('node'):
            self.skipTest('Node indisponível neste ambiente')
        parser = ('function parseShowdownTeam(raw) {' +
                  template.split('  function parseShowdownTeam(raw) {', 1)[1]
                  .split('\n  function previewShowdownImport()', 1)[0])
        harness = r"""
const types=['Fire','Water','Grass'];
const natures=['Jolly','Timid','Adamant'];
const emptySlot=()=>({level:100,pokemon:'',pokemon_id:null,tipos:[],sprite:'',
item:'',ability:'',nature:'',papel:'',mecanica:'nenhuma',tera_ativa:false,tera_type:'',
moves:['','','',''],evs:{hp:0,atk:0,def:0,spa:0,spd:0,spe:0},
ivs:{hp:31,atk:31,def:31,spa:31,spd:31,spe:31}});
const speciesMeta=name=>{
  const key=String(name||'').toLowerCase().replace(/[^a-z0-9]/g,'');
  const data={
    charizard:{n:'Charizard',num:6,types:['Fire','Flying']},
    charizardmegax:{n:'Charizard-Mega-X',base:'charizard',num:6,types:['Fire','Dragon']},
    charizardmegay:{n:'Charizard-Mega-Y',base:'charizard',num:6,types:['Fire','Flying']},
    mewtwo:{n:'Mewtwo',num:150,types:['Psychic']},
    mewtwomegay:{n:'Mewtwo-Mega-Y',base:'mewtwo',num:150,types:['Psychic']},
    pidgeot:{n:'Pidgeot',num:18,types:['Normal','Flying']},
    pidgeotmega:{n:'Pidgeot-Mega',base:'pidgeot',num:18,types:['Normal','Flying']},
    rayquaza:{n:'Rayquaza',num:384,types:['Dragon','Flying']},
    rayquazamega:{n:'Rayquaza-Mega',base:'rayquaza',num:384,types:['Dragon','Flying']}
  };
  return data[key]||null;
};
const slug=v=>String(v||'').toLowerCase().trim().replaceAll(' ','-').replace(/[^a-z0-9-]/g,'');
const megaStoneOwner={'charizardite-x':'charizard','charizardite-y':'charizard',
  'mewtwonite-y':'mewtwo','pidgeotite':'pidgeot'};
const selectedFormat=()=>({permite_mega:true,little_cup:false});
const showdownReady=true;
const speciesKey=value=>String(value||'').toLowerCase().replace(/[^a-z0-9]/g,'');
function megaVariantForSet(pokemon,item,mechanic='') {
  const base=speciesKey(speciesMeta(pokemon)?.base||pokemon),stone=slug(item);
  if(megaStoneOwner[stone]===base)
    return base+'-Mega'+(stone.endsWith('-x')?'-X':stone.endsWith('-y')?'-Y':'');
  return base==='rayquaza'&&mechanic==='mega'?'Rayquaza-Mega':'';
}
"""
        checks = r"""
const source=[
'Charizard @ Charizardite X',
'Ability: Blaze',
'EVs: 252 Atk / 4 SpD / 252 Spe',
'Jolly Nature',
'- Dragon Dance',
'- Flare Blitz',
'- Dragon Claw',
'- Earthquake',
'Charizard @ Charizardite Y',
'Ability: Blaze',
'EVs: 252 SpA / 4 SpD / 252 Spe',
'IVs: 0 Atk',
'Timid Nature',
'- Flamethrower',
'- Solar Beam',
'- Focus Blast',
'- Roost'
].join('\n');
const result=parseShowdownTeam(source);
if(result.errors.length)throw Error(JSON.stringify(result.errors));
if(result.parsed.length!==2)throw Error('Não reconheceu os dois Pokémon.');
if(result.parsed[0].item!=='Charizardite X')throw Error('Perdeu a Mega Stone X.');
if(result.parsed[1].item!=='Charizardite Y')throw Error('Perdeu a Mega Stone Y.');
if(result.parsed[0].mecanica!=='mega'||result.parsed[1].mecanica!=='mega')throw Error('Mega não reconhecida.');
if(result.parsed[0].evs.atk!==252||result.parsed[1].evs.spa!==252)throw Error('EVs incorretos.');
if(result.parsed[1].ivs.atk!==0||result.parsed[1].nature!=='Timid')throw Error('IV ou Nature incorretos.');
if(result.parsed[1].moves[3]!=='Roost')throw Error('Quarto golpe perdido.');
if(parseShowdownTeam(source.replace('252 SpA','300 SpA')).errors.length===0)throw Error('EV inválido não foi rejeitado.');
if(parseShowdownTeam('Charizard @ <img src=x>').errors.length===0)throw Error('Item inseguro não foi rejeitado.');
const megaY=source.split('Charizard @ Charizardite Y')[1];
const exact='Charizard-Mega-Y @ Charizardite Y'+megaY.replace('- Focus Blast','- Scorching Sands');
const alias=parseShowdownTeam(exact);
if(alias.errors.length||alias.parsed.length!==1)throw Error('Forma Mega-Y recusada: '+JSON.stringify(alias.errors));
const resultY=alias.parsed[0];
if(resultY.pokemon!=='Charizard'||resultY.item!=='Charizardite Y'||resultY.mecanica!=='mega')throw Error('Forma Mega-Y não normalizada.');
if(resultY.moves[2]!=='Scorching Sands'||resultY.ability!=='Blaze'||resultY.ivs.atk!==0||resultY.evs.spa!==252)
  throw Error('O importador apagou dados da forma Mega.');
const variant=exact.replace('Ability: Blaze','Ability: Drought');
if(parseShowdownTeam(variant).parsed[0].ability!=='Drought')throw Error('Habilidade Mega perdida.');
if(!parseShowdownTeam(variant.replace('Charizardite Y','Charizardite X')).errors.some(e=>e.includes('não corresponde')))
  throw Error('Mega Stone X não foi rejeitada na forma Y.');
if(!parseShowdownTeam(variant.replace('Charizardite Y','Leftovers')).errors.length)
  throw Error('Mega sem pedra não foi rejeitada.');
for(const text of ['Mewtwo-Mega-Y @ Mewtwonite Y','Pidgeot-Mega @ Pidgeotite']){
  const set=parseShowdownTeam(text+'\nAbility: Insomnia\nTimid Nature\n- Protect');
  if(set.errors.length||set.parsed[0].mecanica!=='mega')throw Error('Forma Mega adicional: '+text+': '+JSON.stringify(set.errors));
}
const dragon='Rayquaza-Mega @ Life Orb\nAbility: Delta Stream\nJolly Nature\n- Dragon Ascent';
if(parseShowdownTeam(dragon).errors.length||parseShowdownTeam(dragon).parsed[0].mecanica!=='mega')
  throw Error('Mega Rayquaza sem stone não reconhecido.');
if(!parseShowdownTeam(dragon.replace('Dragon Ascent','Protect')).errors.length)
  throw Error('Mega Rayquaza sem Dragon Ascent foi aceito.');
"""
        result = subprocess.run(['node', '-'], input=harness+parser+checks, text=True,
                                capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tournament_format_is_frozen_after_private_team(self):
        app=(ROOT / 'app.py').read_text(encoding='utf-8')
        self.assertIn("'formato_codigo': preset['codigo'] if preset else", app)
        bloco=app[app.index('def editar_torneio('):app.index('def participantes_torneio(',app.index('def editar_torneio('))]
        self.assertIn("preset_atual = codigo_formato_do_torneio",bloco)
        self.assertIn("_safe_table('arena_torneio_equipes', 'id', torneio_id=item_id)",bloco)
        self.assertIn("if not estrutura_bloqueada and not preset_atual:",bloco)

    def test_capture_balls_denied_and_legitimate_items_left_alone(self):
        data = []
        for p in ('Dialga', 'Palkia', 'Kyogre', 'Groudon', 'Lugia', 'Ho-Oh'):
            data.append({
                'pokemon': p, 'ability': obter_regras_especie_showdown(p)['abilities'][0], 'nature': 'Timid',
                'item': 'Leftovers',
                'moves': ['Recover', 'Protect', 'Rest', 'Sleep Talk'],
                'evs': {k: 0 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')},
                'ivs': {k: 31 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')}
            })
        self.assertIsNotNone(obter_formato('gen9nationaldexubers'))
        self.assertEqual(validar_equipe_basica(data, 'gen9nationaldexubers'), [])
        data[0]['item'] = 'Master Ball'
        errors = validar_equipe_basica(data, 'gen9nationaldexubers')
        self.assertTrue(any('Master Ball' in error for error in errors))
        data[0]['item'] = 'Ultra Ball'
        self.assertTrue(any('Ultra Ball' in e for e in validar_equipe_basica(data, 'gen9nationaldexubers')))
        data[0]['item'] = 'Light Ball'
        self.assertEqual(validar_equipe_basica(data, 'gen9nationaldexubers'), [])


    def test_post_mega_abilities_are_validated_for_the_matching_stone(self):
        slots = []
        for name, item, ability, mechanic in (
            ('Charizard', 'Charizardite Y', 'Drought', 'mega'),
            ('Mewtwo', 'Mewtwonite Y', 'Insomnia', 'mega'),
            ('Pidgeot', 'Pidgeotite', 'No Guard', 'mega'),
            ('Dialga', 'Leftovers', 'Pressure', 'nenhuma'),
            ('Palkia', 'Leftovers', 'Pressure', 'nenhuma'),
            ('Lugia', 'Leftovers', 'Pressure', 'nenhuma'),
        ):
            slots.append({
                'pokemon': name, 'item': item, 'ability': ability,
                'mecanica': mechanic, 'nature': 'Timid',
                'moves': ['Protect', 'Rest', 'Sleep Talk', 'Recover'],
                'evs': {k: 0 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')},
                'ivs': {k: 31 for k in ('hp', 'atk', 'def', 'spa', 'spd', 'spe')},
            })
        errors = validar_equipe_basica(slots, 'gen9nationaldexubers')
        self.assertEqual(errors, [], errors)
        slots[0]['ability'] = 'Wonder Guard'
        self.assertTrue(any('não pertence' in e for e in validar_equipe_basica(slots, 'gen9nationaldexubers')))
        slots[0]['ability'] = 'Drought'
        slots[0]['item'] = 'Charizardite X'
        self.assertTrue(any('não pertence' in e for e in validar_equipe_basica(slots, 'gen9nationaldexubers')))



class TestHypeMobileAdmin(unittest.TestCase):
    def test_dashboard_and_leader_navigation(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / 'templates')), autoescape=True)
        env.filters['preco'] = lambda value: value  # filtro registrado na aplicação Flask
        for name in ('admin_dashboard_geral.html', 'hype_app_base.html',
                     'builders_base.html', 'admin_v29_nav.html', 'admin_economia.html'):
            self.assertIsNotNone(env.get_template(name))
        dashboard = (ROOT / 'templates/admin_dashboard_geral.html').read_text(encoding='utf-8')
        self.assertIn('id="admin2MobileToggle"', dashboard)
        self.assertIn('id="admin2Sidebar"', dashboard)
        self.assertIn('hype_admin_mobile_v40.js', dashboard)
        app_base = (ROOT / 'templates/hype_app_base.html').read_text(encoding='utf-8')
        tools_base = (ROOT / 'templates/builders_base.html').read_text(encoding='utf-8')
        for source in (app_base, tools_base):
            self.assertIn("hype_permissoes.get('pode_gerenciar_cargos')", source)
            self.assertIn("url_for('expansion.admin_dashboard')", source)
        nav = (ROOT / 'templates/admin_v29_nav.html').read_text(encoding='utf-8')
        self.assertIn('admin-v29-mobile-toggle', nav)
        self.assertIn('aria-expanded', nav)

    def test_mobile_controls_and_small_screen_styles(self):
        css = (ROOT / 'static/hype_admin_mobile_v40.css').read_text(encoding='utf-8')
        js = (ROOT / 'static/hype_admin_mobile_v40.js').read_text(encoding='utf-8')
        common_css = (ROOT / 'static/admin_v29.css').read_text(encoding='utf-8')
        for marker in ('.admin2-side.is-open', '.admin2-mobile-toolbar',
                       '.admin2-metrics', '.admin2-table-wrap', 'max-width:400px'):
            self.assertIn(marker, css)
        for marker in ("'Escape'", 'aria-expanded', 'previousFocus', 'admin2MobileBackdrop'):
            self.assertIn(marker, js)
        self.assertIn('.admin-v29-nav[data-mobile-ready="1"].is-open', common_css)

if __name__ == '__main__':
    unittest.main()
