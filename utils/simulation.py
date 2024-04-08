import asyncio
import time
import traceback

from nextcord import Interaction, ui, File

import config
import db_query
from globals import CustomEmbed
from utils import translate
from utils.checks import get_type_emoji


def save_items(result, zerpmonWinrate):
    try:
        for key in ['playerAZerpmons', 'playerBZerpmons']:
            for equipped in result[key]:
                zerp, eq = equipped['zerpmon'], equipped['equipment']
                if eq:
                    zerpmonWinrate[zerp['name']]['eq'] = eq
                zerpmonWinrate[zerp['name']]['emj'] = ', '.join([config.TYPE_MAPPING[i.title()] for i in zerp['zerpmonType']])
                zerpmonWinrate[zerp['name']]['level'] = zerp['level']
    except:
        print(traceback.format_exc())


async def simulation_callback(interaction: Interaction, battle_count: int, playerA: dict, playerB: dict):
    embed = CustomEmbed(title=f"Simulation Results", color=0x430f58)
    uid = await db_query.make_sim_battle_req(playerA, playerB, cnt=battle_count)
    file_path = f'./sim/{interaction.user.id}-{int(time.time())}.txt'
    matches_won = 0
    if len(playerA['zerpmons']) == 0 or len(playerA['zerpmons']) == 0:
        await interaction.send(content="**Failed**, please select at least 1 Zerpmon for both teams")
    zerpmonWinrate = {
        **{i: {'t': 0, 'w': 0} for i in playerA['zerpmons'] if i},
        **{i: {'t': 0, 'w': 0} for i in playerB['zerpmons'] if i},
    }
    setup_done = False
    with open(file_path, 'w', encoding='utf-8') as file:
        for i in range(10):
            try:
                await asyncio.sleep(battle_count / 20)
                buffer = ''
                for idx in range(battle_count):
                    cur_uid = uid + f'{idx}'
                    result = config.battle_results[cur_uid]
                    print(f"Simulation time taken: {result['timeTaken']}")
                    del config.battle_results[cur_uid]
                    if result:
                        buffer += f'\n\n\n\nMatch #{idx + 1}\n\n'
                        if not setup_done:
                            save_items(result, zerpmonWinrate)
                            setup_done = True
                        if result['winner'] == 'A':
                            matches_won += 1
                        firstRoundLog = result['roundLogs'][0]
                        if firstRoundLog['zerpmonAImmunitiesGranted']:
                            buffer += f"{firstRoundLog['zerpmonA']} is immune to\n" + '\n '.join(
                                [i.title() for i in firstRoundLog['zerpmonAImmunitiesGranted']]) + '\n\n'
                        if firstRoundLog['zerpmonBImmunitiesGranted']:
                            buffer += f"{firstRoundLog['zerpmonB']} is immune to\n" + '\n '.join(
                                [i.title() for i in firstRoundLog['zerpmonBImmunitiesGranted']]) + '\n\n'
                        for round_messages in result['roundLogs']:
                            msgs = translate.translate_message(interaction.locale.split('-')[0],
                                                               round_messages['messages'])
                            msg = ''
                            for i in msgs:
                                msg += i + '\n'
                            buffer += f'{msg}\n\n'
                        for round_stat in [*result['roundStatsA'], *result['roundStatsB']]:
                            name = round_stat['name']
                            obj = zerpmonWinrate[name]
                            obj['t'] += len(round_stat['rounds'])
                            obj['w'] += round_stat['rounds'].count(1)
                file.write(buffer)
                break
            except:
                pass
    file = File(file_path, filename='simulation_result.txt')
    embed.add_field(name=f"Total Matches **{battle_count}**",
                    value=f"\u200B",
                    inline=False)
    embed.add_field(name="\u200B",
                    value="\u200B",
                    inline=False)
    embed.add_field(name="Matches Won",
                    value=f"> PlayerA: **`{matches_won}`**\n"
                          f"> PlayerB: **`{battle_count - matches_won}`**",
                    inline=False)
    embed.add_field(name="Winrate",
                    value=f"> PlayerA: **`{round(matches_won * 100 / max(1, battle_count), 1)}`**\n"
                          f"> PlayerB: **`{round((1 - matches_won/ max(1, battle_count)) * 100 , 1)}`**",
                    inline=False)
    embed.add_field(name="\u200B",
                    value="\u200B",
                    inline=False)
    idx = 1
    print(zerpmonWinrate)
    for zerp, obj in zerpmonWinrate.items():
        embed.add_field(name=f"{zerp} ({obj['emj']})  ->  Level {obj['level'] if obj['level'] else 1}",
                        value=f"> Total rounds: **`{obj['t']}`**\n"
                              f"> Cumulative **WR: `{round(obj['w'] * 100 / max(obj['t'], 1), 1)}`**\n" +
                              (
                                  f"> **Equipment: \n"
                                  f"> {obj['eq']['name']} ({config.TYPE_MAPPING[obj['eq']['type']]})**\n" if 'eq' in obj else ''),
                        inline=False)
        embed.add_field(name="\u200B",
                        value="\u200B",
                        inline=False)
        idx += 1
    await interaction.send(embeds=[embed], files=[file])
