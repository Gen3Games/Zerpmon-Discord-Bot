import asyncio
import json
import logging
import os
import random
import re
import time
import traceback

from utils.battle_effect import apply_status_effects, update_next_atk, update_next_dmg, update_purple_stars, update_dmg
import nextcord
import requests
from PIL import Image

import config
import db_query
from utils import xrpl_ws, checks


class CustomEmbed(nextcord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_footer(text='Zerpmon',
                        icon_url=config.ICON_URL)


def get_val(effect):
    match = re.search(r'\b(\d+(\.\d+)?)\b', effect)
    val = int(float(match.group()))
    return val


with open("./TypingMultipliers.json", 'r') as file:
    file = json.load(file)
    type_mapping = dict(file)


def check_battle_happening(channel_id):
    battles_in_channel = [i for msg, i in config.battle_dict.items() if i['channel_id'] == channel_id]
    wager_battles_in_channel = [i for msg, i in config.wager_battles.items() if i['channel_id'] == channel_id]
    free_br_channels = [i for i in config.free_br_channels if i == channel_id]

    return battles_in_channel == [] and wager_battles_in_channel == [] and free_br_channels == []


async def send_global_message(guild, text, image):
    try:
        channel = nextcord.utils.get(guild.channels, name='🤖│zerpmon-caught')
        await channel.send(content=text + '\n' + image)
    except Exception as e:
        logging.error(f'ERROR: {traceback.format_exc()}')


def gen_image(_id, url1, url2, path1, path2, path3, gym_bg=False):
    if gym_bg and gym_bg is not None:
        bg_img = Image.open(gym_bg)
    else:
        randomImage = f'BattleBackground{random.randint(1, 68)}.png'
        # Load the background image and resize it
        bg_img = Image.open(f'./static/bgs/{randomImage}')
    bg_img = bg_img.resize((2560, 1600))  # desired size

    # Load the three images
    download_image(url1, path1)
    download_image(url2, path3)
    img1 = Image.open(path1)
    img2 = Image.open(path2)
    img3 = Image.open(path3)

    img1 = img1.resize((1200, 1200))
    img3 = img3.resize((1200, 1200))

    # Create a new RGBA image with the size of the background image
    combined_img = Image.new('RGBA', bg_img.size, (0, 0, 0, 0))

    # Paste the background image onto the new image
    combined_img.paste(bg_img, (0, 0))

    # Paste the three images onto the new image
    combined_img.paste(img1, (50, 100), mask=img1)  # adjust the coordinates as needed
    combined_img.paste(img2, (1150, 200), mask=img2)
    combined_img.paste(img3, (1350, 100), mask=img3)

    # Resize the combined image to be 50% of its original size
    new_width = int(combined_img.width * 0.5)
    new_height = int(combined_img.height * 0.5)
    smaller_img = combined_img.resize((new_width, new_height))

    # Save the final image
    smaller_img.save(f'{_id}.png', quality=50)


def battle_zerpmons(zerpmon1_name, zerpmon2_name, types, status_affects, buffed_types, p1=None, p2=None, p1_temp=None,
                    p2_temp=None):
    z1 = db_query.get_zerpmon(zerpmon1_name)
    print(p1, p2, p1_temp, p2_temp)
    # Trainer buff
    buffed1 = [i for i in buffed_types[0] if i in types[0]]
    if len(buffed1) > 0:
        for i, move in enumerate(z1['moves']):
            if 'dmg' in move and move['dmg'] != "":
                z1['moves'][i]['dmg'] = round(1.1 * int(move['dmg']))
    # print(z1['moves'])
    percentages1 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
                    z1['moves']] if p1 is None else p1
    if p1_temp is None:
        p1_temp = percentages1

    # print(f'Percentages1: {percentages1}')
    z2 = db_query.get_zerpmon(zerpmon2_name)

    dmg_mul = 1
    for buffed_type in buffed_types[1]:
        buffed2 = buffed_type in types[1]
        if buffed2:
            dmg_mul += 0.1
    for i, move in enumerate(z2['moves']):
        if 'dmg' in move and move['dmg'] != "":
            z2['moves'][i]['dmg'] = round(dmg_mul * int(move['dmg']))
    percentages2 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
                    z2['moves']] if p2 is None else p2
    if p2_temp is None:
        p2_temp = percentages2
    # print(f'Percentages2: {percentages2}')

    percentages1, percentages2, m1, m2 = \
        apply_status_effects(percentages1, percentages2, status_affects if status_affects is not None else [[], []])

    # Select the random move based on Percentage weight

    indexes = list(range(len(percentages1)))

    chosen_index1 = random.choices(indexes, weights=[(0 if i is None else i) for i in p1_temp])[0]
    move1 = z1['moves'][chosen_index1]
    p1_temp = percentages1
    # print(move1)

    chosen_index2 = random.choices(indexes, weights=[(0 if i is None else i) for i in p2_temp])[0]
    move2 = z2['moves'][chosen_index2]
    p2_temp = percentages2
    # print(move2)

    winner = {
        'move1': {'name': move1['name'], 'color': move1['color'], 'dmg': "" if 'dmg' not in move1 else move1['dmg'],
                  'stars': "" if 'stars' not in move1 else len(move1['stars']),
                  'percent': round(float(p1_temp[chosen_index1])), 'msg': m1,
                  'type': '' if 'type' not in move1 else move1['type'],
                  'mul': ''},
        'move2': {'name': move2['name'], 'color': move2['color'], 'dmg': "" if 'dmg' not in move2 else move2['dmg'],
                  'stars': "" if 'stars' not in move2 else len(move2['stars']),
                  'percent': round(float(p2_temp[chosen_index2])), 'msg': m2,
                  'type': '' if 'type' not in move2 else move2['type'],
                  'mul': ''},
        'winner': ""

    }

    # p1_temp, p2_temp, status_affects[0] = update_next_atk(percentages1, percentages2, chosen_index1, chosen_index2,
    #                                                       status_affect_solo=status_affects[0])
    # p2_temp, p1_temp, status_affects[1] = update_next_atk(p2_temp, p1_temp, chosen_index2, chosen_index1,
    #                                                       status_affect_solo=status_affects[1])

    print(p1, p2, p1_temp, p2_temp)
    if move1['color'] == 'purple':
        winner['move1']['stars'], status_affects[1] = update_purple_stars(len(move1['stars']), status_affects[1])
    if move2['color'] == 'purple':
        winner['move2']['stars'], status_affects[0] = update_purple_stars(len(move2['stars']), status_affects[0])
    if 'dmg' in move1:
        d1m = 1.0
        # print(types[1], types[0])

        _t1 = move1['type'].lower().replace(" ", "")
        for _t2 in types[1]:
            _t2 = _t2.lower().replace(" ", "")
            d1m = d1m * type_mapping[_t1][_t2]
            d1m = int(d1m) if float(d1m).is_integer() else d1m
        # print(d1m)
        d1m_t, status_affects[1] = update_next_dmg(status_affect_solo=status_affects[1])

        move1['dmg'] = round(d1m * int(move1['dmg']) * d1m_t)
        winner['move1']['dmg'] = round(move1['dmg'])
        winner['move1']['mul'] = "x½" if d1m == 0.5 else f'x{d1m}'
        r_int = random.randint(1, 20)
        if r_int == 1:
            move1['dmg'] = round(2 * int(move1['dmg']))
            winner['move1']['dmg'] = round(move1['dmg'])
            winner['move1']['mul'] += " 🎯"

    if 'dmg' in move2:
        d2m = 1.0

        _t1 = move2['type'].lower().replace(" ", "")
        for _t2 in types[0]:
            _t2 = _t2.lower().replace(" ", "")
            d2m = d2m * type_mapping[_t1][_t2]
            d2m = int(d2m) if float(d2m).is_integer() else d2m

        d2m_t, status_affects[0] = update_next_dmg(status_affect_solo=status_affects[0])
        # print(d2m)
        move2['dmg'] = round(d2m * int(move2['dmg']) * d2m_t)
        winner['move2']['dmg'] = round(move2['dmg'])
        winner['move2']['mul'] = "x½" if d2m == 0.5 else f'x{d2m}'
        r_int = random.randint(1, 20)
        if r_int == 1:
            move2['dmg'] = round(2 * int(move2['dmg']))
            winner['move2']['dmg'] = round(move2['dmg'])
            winner['move2']['mul'] += " 🎯"

    old_dmg1, old_dmg2 = winner['move1']['dmg'], winner['move2']['dmg']
    winner['move1']['dmg'], winner['move2']['dmg'], status_affects[0] = update_dmg(old_dmg1, old_dmg2,
                                                                                   status_affects[0])
    winner['move2']['dmg'], winner['move1']['dmg'], status_affects[1] = update_dmg(winner['move2']['dmg'],
                                                                                   winner['move1']['dmg'],
                                                                                   status_affects[1])

    if winner['move1']['dmg'] != old_dmg1:
        winner['dmg_str1'] = f"({old_dmg1} x{winner['move1']['dmg'] / old_dmg1:.1f})={winner['move1']['dmg']} ❤️‍🩹 "
    if winner['move2']['dmg'] != old_dmg2:
        winner['dmg_str2'] = f"({old_dmg2} x{winner['move2']['dmg'] / old_dmg2:.1f})={winner['move2']['dmg']} ❤️‍🩹 "
    # Check Color of both moves
    match (move1['color'], move2['color']):
        case ("white", "white") | ("white", "gold") | ("gold", "white") | ("gold", "gold"):

            d1 = float(winner['move1']['dmg'])
            d2 = float(winner['move2']['dmg'])

            if d1 > d2:
                winner['winner'] = '1'

            elif d1 == d2:
                winner['winner'] = ""
            else:
                winner['winner'] = '2'

        case ("white", "purple") | ("miss", "purple"):
            if winner['move2']['stars'] > 0:
                m2 = db_query.get_move(move2['name'])
                note = m2['notes'].lower()
                percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2, [[], [note]])
                winner['winner'] = '2'
                winner['status_effect'] = note
                winner['move2']['msg'] = _m2
            else:
                winner['winner'] = ""

        case ("purple", "white") | ("purple", "miss"):
            if winner['move1']['stars'] > 0:
                m1 = db_query.get_move(move1['name'])
                note = m1['notes'].lower()
                percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2, [[note], []])

                winner['winner'] = '1'
                winner['status_effect'] = note
                winner['move1']['msg'] = _m1
            else:
                winner['winner'] = ""

        case ("blue", "white") | ("blue", "gold") | ("blue", "purple") | ("blue", "miss") | ("white", "blue") | ("gold",
                                                                                                                 "blue") | (
                 "purple", "blue") | ("miss", "blue") | ("blue", "blue"):

            winner['winner'] = ""

        case ("white", "miss") | ("gold", "miss"):
            if winner['move1']['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '1'

        case ("miss", "white") | ("miss", "gold"):
            if winner['move2']['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '2'

        case ("gold", "purple"):
            m2 = db_query.get_move(move2['name'])
            note = m2['notes'].lower()
            if 'knock' in note and 'against' in note and 'gold' in note:
                winner['winner'] = '2'
            elif winner['move1']['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '1'

        case ("purple", "gold"):
            m1 = db_query.get_move(move1['name'])
            note = m1['notes'].lower()
            if 'knock' in note and 'against' in note and 'gold' in note:
                winner['winner'] = '1'
            elif winner['move2']['dmg'] == 0:
                winner['winner'] = ""
            else:
                winner['winner'] = '2'

        case ("purple", "purple"):
            s1 = winner['move1']['stars']
            s2 = winner['move2']['stars']
            if s1 > s2:
                m1 = db_query.get_move(move1['name'])
                percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2,
                                                                            [[m1['notes']], []])

                winner['winner'] = '1'
                winner['status_effect'] = m1['notes'].lower()
                winner['move1']['msg'] = _m1

            elif s1 == s2:
                winner["winner"] = ""  # DRAW
            else:
                m2 = db_query.get_move(move2['name'])
                percentages1, percentages2, _m1, _m2 = apply_status_effects(percentages1, percentages2,
                                                                            [[], [m2['notes']]])

                winner['winner'] = '2'
                winner['status_effect'] = m2['notes'].lower()
                winner['move2']['msg'] = _m2

        case ("miss", "miss"):
            winner['winner'] = ""

        case _:
            print(f"IDK what this is {move1}, {move2}")

    return winner, percentages1, percentages2, status_affects, p1_temp, p2_temp


bt = battle_zerpmons("Fiepion", "Elapix", [["fire"], ["Bug", "Steel"]], [[], []], ["Dark", "Dark"])
print(json.dumps(bt, indent=2))


def download_image(url, path_to_file):
    if os.path.isfile(path_to_file):
        # print(f"{path_to_file} already exists, skipping download.")
        pass
    else:
        response = requests.get(url)
        with open(path_to_file, 'wb') as f:
            f.write(response.content)
        print(f"Downloaded {path_to_file}.")


async def proceed_gym_battle(interaction: nextcord.Interaction, gym_type):
    _data1 = db_query.get_owned(interaction.user.id)
    u_flair = f' | {_data1.get("flair", [])[0]}' if len(
        _data1.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    leader = db_query.get_gym_leader(gym_type)
    gym_won = {} if 'gym' not in _data1 else _data1['gym']['won']
    stage = 1 if gym_type not in gym_won else gym_won[gym_type]['stage']
    leader_name = config.LEADER_NAMES[gym_type]
    trainer_embed = CustomEmbed(title=f"Gym Battle",
                                description=f"({user_mention} VS {leader_name} {config.TYPE_MAPPING[gym_type]})",
                                color=0xf23557)

    user1_zerpmons = _data1['zerpmons']
    tc1 = list(_data1['trainer_cards'].values())[0] if ('gym_deck' not in _data1) or (
            '0' in _data1['gym_deck'] and ('trainer' not in _data1['gym_deck']['0'])) else \
        _data1['trainer_cards'][_data1['gym_deck']['0']['trainer']]
    tc1i = tc1['image']
    buffed_type1 = [i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

    user2_zerpmons = leader['zerpmons']
    random.shuffle(user2_zerpmons)
    tc2i = leader['image']

    path1 = f"./static/images/{tc1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = tc2i

    url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
    trainer_embed.add_field(
        name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
        value="\u200B", inline=True)

    trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

    trainer_embed.add_field(
        name=f"{leader_name} (Stage {stage})",
        value="\u200B", inline=True)

    gen_image(str(interaction.id) + '0', url1, '', path1, path2, path3, leader['bg'])

    file2 = nextcord.File(f"{interaction.id}0.png", filename="image0.png")
    trainer_embed.set_image(url=f'attachment://image0.png')

    low_z = max(len(user1_zerpmons), len(user2_zerpmons))
    b_type = 5
    if b_type <= low_z:
        low_z = b_type

    # Sanity check
    if 'gym_deck' in _data1 and (
            len(_data1['gym_deck']) == 0 or ('0' in _data1['gym_deck'] and len(_data1['gym_deck']['0']) == 0)):
        await interaction.send(content=f"**{_data1['username']}** please check your gym battle deck, it's empty.")
    # Proceed

    print("Start")
    try:
        del _data1['gym_deck']['0']['trainer']
    except:
        pass

    if 'gym_deck' not in _data1 or (
            len(_data1['gym_deck']) == 0 or ('0' in _data1['gym_deck'] and len(_data1['gym_deck']['0']) == 0)):
        user1_zerpmons = list(user1_zerpmons.values())[:low_z if len(user1_zerpmons) > low_z else len(user1_zerpmons)]
    else:
        user1_z = []
        i = 0
        while len(user1_z) != len(_data1['gym_deck']['0']):
            try:
                user1_z.append(user1_zerpmons[_data1['gym_deck']['0'][str(i)]])
            except:
                pass
            i += 1
        user1_z.reverse()
        user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]

    # print(user1_zerpmons[-1], '\n', user2_zerpmons[-1], '\n', user1_zerpmons, '\n', user2_zerpmons, )
    for _i, zerp in enumerate(user2_zerpmons):
        lvl_inc = 3 if (stage - 1) > 3 else (stage - 1)
        user2_zerpmons[_i]['level'] = 10
        for _c in range(lvl_inc):
            user2_zerpmons[_i] = db_query.update_moves(user2_zerpmons[_i], save_z=False)
    msg_hook = None
    status_stack = [[], []]
    p1 = None
    p2 = None
    p1_temp = None
    p2_temp = None
    battle_log = {'teamA': {'trainer': tc1, 'zerpmons': []}, 'teamB': {'trainer': {'name': leader_name}, 'zerpmons': []}, 'battle_type': 'Gym Battle'}
    for zerp in user1_zerpmons:
        zerp['rounds'] = []
    for zerp in user2_zerpmons:
        zerp['rounds'] = []
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1]
        z1_moves = db_query.get_zerpmon(z1['name'])['moves']
        zimg1 = z1['image']
        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp = ''
        for i in z1_type:
            if i in buffed_type1:
                buffed_zerp = i

        z2 = user2_zerpmons[-1]
        z2_moves = z2['moves']
        zimg2 = z2['image']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']

        if p2 is None:
            p2 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
                  z2['moves']]

        main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x35bcbf)
        path1 = f"./static/images/{z1['name']}.png"
        path2 = f"./static/images/vs.png"
        path3 = f"./static/images/{z2['name']}.png"

        url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
        main_embed.add_field(name=f"{z1['name']} ({', '.join(z1_type)})",
                             value=f"{config.TYPE_MAPPING[buffed_zerp]} Trainer buff" if buffed_zerp != '' else "\u200B",
                             inline=False)

        for i, move in enumerate(z1_moves):
            if move['name'] == "":
                continue
            notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

            main_embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent'] if p1 is None else p1[i]}%\n",
                inline=True)
        main_embed.add_field(name="\u200B", value="\u200B", inline=False)
        main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
        main_embed.add_field(name="\u200B", value="\u200B", inline=False)

        url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
        main_embed.add_field(name=f"{z2['name']} ({', '.join(z2_type)})",
                             value=f"{config.TYPE_MAPPING[gym_type]} Trainer buff" if stage > 4 else "\u200B",
                             inline=False)

        for i, move in enumerate(z2_moves):
            if move['name'] == "":
                continue
            notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''
            main_embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent'] if p2 is None else p2[i]}%\n",
                inline=True)

        gen_image(interaction.id, url1, url2, path1, path2, path3, leader['bg'])

        file = nextcord.File(f"{interaction.id}.png", filename="image.png")
        main_embed.set_image(url=f'attachment://image.png')

        if msg_hook is None:
            msg_hook = interaction
            await interaction.send(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file],
                                   ephemeral=True)
        else:
            await msg_hook.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)

        buffed_type2 = [gym_type] * (stage - 4)
        eliminate = ""
        move_counter = 0
        while eliminate == "":
            await asyncio.sleep(3)
            # If battle lasts long then end it
            if move_counter == 20:
                r_int = random.randint(1, 2)
                rand_loser = z2['name'] if r_int == 2 else z1['name']
                await msg_hook.send(
                    content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!",
                    ephemeral=True)
                eliminate = (r_int, rand_loser)
                if r_int == 2:
                    p2 = None
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                    db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                elif r_int == 1:
                    p1 = None
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                    db_query.save_zerpmon_winrate(z2['name'], z1['name'])

            result, p1, p2, status_stack, p1_temp, p2_temp = battle_zerpmons(z1['name'], z2['name'], [z1_type, z2_type],
                                                                             status_stack,
                                                                             [buffed_type1, buffed_type2], p1, p2,
                                                                             p1_temp, p2_temp)
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"

            atk_msg = f"**{z1['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                      f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n" \
                      f"**{z2['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                      f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n" \
                      "Calculating Battle results..."

            await msg_hook.send(content=atk_msg, ephemeral=True)
            if result['winner'] != '1' or '0 damage' not in result.get('status_effect', ''):
                for i, effect in enumerate(status_stack[0].copy()):
                    if '0 damage' in effect:
                        status_stack[0].remove(effect)
                        break
            if result['winner'] != '2' or '0 damage' not in result.get('status_effect', ''):
                for i, effect in enumerate(status_stack[1].copy()):
                    if '0 damage' in effect:
                        status_stack[1].remove(effect)
                        break

            print(result)

            # purple attacks
            if 'status_effect' in result:
                effect = result['status_effect']
                if result['winner'] == '1':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[0].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[0].count(effect)
                            new_m = f"**{z2['name'] if 'decrease' in effect else z1['name']}**'s damage is {'reduced' if 'decrease' in effect else 'increased'} by ({p_x}%) for the next {'' if count_x <= 1 else '**' + str(count_x) + '** '}{'attack' if count_x <= 1 else 'attacks'}!"
                            await msg_hook.send(
                                content=new_m, ephemeral=True)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[0].append(effect)
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=new_m, ephemeral=True)
                            else:
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=new_m, ephemeral=True)

                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '1'
                        else:
                            if result['move2']['color'] in effect:
                                result['winner'] = '1'
                            else:
                                new_m = f"{result['move1']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=new_m, ephemeral=True)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[0].append(effect)
                        new_m = f"{z2['name']} has had their purple moves reduced by 1 star!"
                        await msg_hook.send(
                            content=new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    else:
                        new_m = result['move1']['msg'][:-1]
                        i = int(result['move1']['msg'][-1])

                        new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                            config.COLOR_MAPPING[z2_moves[i]['color']], '')
                        new_m = new_m.replace("@me", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                            "@op", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ')
                        new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(int(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p1[i]))) if p1[i] is not None else 0)}%)"
                        await msg_hook.send(
                            content=new_m, ephemeral=True)
                        move_counter += 1
                        continue
                else:
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[1].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[1].count(effect)
                            new_m = f"**{z1['name'] if 'decrease' in effect else z2['name']}**'s damage is {'reduced' if 'decrease' in effect else 'increased'} by ({p_x}%) for the next {'' if count_x <= 1 else '**' + str(count_x) + '** '}{'attack' if count_x <= 1 else 'attacks'}!"
                            await msg_hook.send(
                                content=new_m, ephemeral=True)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[1].append(effect)
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=new_m, ephemeral=True)
                            else:
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.send(
                                    content=new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '2'
                        else:
                            if result['move1']['color'] in effect:
                                result['winner'] = '2'
                            else:
                                new_m = f"{result['move2']['name']} was ineffective! Draw!"
                                await msg_hook.send(
                                    content=new_m, ephemeral=True)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[1].append(effect)
                        new_m = f"{z1['name']} has had their purple moves reduced by 1 star!"
                        await msg_hook.send(
                            content=new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    else:

                        new_m = result['move2']['msg'][:-1]
                        i = int(result['move2']['msg'][-1])

                        new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                            config.COLOR_MAPPING[z2_moves[i]['color']], '')
                        new_m = new_m.replace("@me", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                            "@op", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ')
                        new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(int(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p2[i]))) if p2[i] is not None else 0)}%)"

                        await msg_hook.send(
                            content=new_m, ephemeral=True)
                        move_counter += 1
                        continue

            # DRAW
            if result['winner'] == "":
                await msg_hook.send(content=f"**DRAW**", ephemeral=True)
                move_counter += 1
                continue

            if result['winner'] == '1':
                await msg_hook.send(
                    content=f"{z1['name']} **knocked out** 💀 {z2['name']} 💀!" if '🎯' not in result['move1'][
                        'mul'] else f"**{z2['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}", ephemeral=True)
                eliminate = (2, z2['name'])
                p2 = None
                status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                move_counter += 1

            elif result['winner'] == '2':
                await msg_hook.send(
                    content=f"{z2['name']} **knocked out** 💀 {z1['name']} 💀!" if '🎯' not in result['move2'][
                        'mul'] else f"**{z1['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}", ephemeral=True)
                eliminate = (1, z1['name'])
                p1 = None
                status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                move_counter += 1

        if eliminate[0] == 1:
            z1['rounds'].append(0)
            z2['rounds'].append(1)
            battle_log['teamA']['zerpmons'].append({'name': z1['name'], 'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[result['move2']['type']], 'rounds': z1['rounds'].copy()})
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p1 = None
            p1_temp = None
        elif eliminate[0] == 2:
            z1['rounds'].append(1)
            z2['rounds'].append(0)
            battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[result['move1']['type']], 'rounds': z2['rounds'].copy()})
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]
            p2 = None
            p2_temp = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{msg_hook.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    file2.close()
    for i in range(3):
        try:
            os.remove(f"{msg_hook.id}0.png")
            break
        except Exception as e:
            print(f"Delete failed retrying {e}")

    total_gp = 0 if "gym" not in _data1 else _data1["gym"]["gp"] + stage
    if len(user1_zerpmons) == 0:
        await interaction.send(
            f"Sorry you **LOST** 💀 \nYou can try battling **{leader_name}** again tomorrow",
            ephemeral=True)
        battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'rounds': z2['rounds']})
        db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name, battle_log['teamA'], battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
        # Save user's match
        db_query.reset_gym(_data1['discord_id'], _data1['gym'] if 'gym' in _data1 else {}, gym_type, lost=True)
        return 2
    elif len(user2_zerpmons) == 0:
        # Add GP to user
        battle_log['teamA']['zerpmons'].append(
            {'name': z1['name'], 'rounds': z1['rounds']})
        db_query.update_battle_log(interaction.user.id, None, interaction.user.name, leader_name, battle_log['teamA'],
                                   battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])

        db_query.add_gp(_data1['discord_id'], _data1['gym'] if 'gym' in _data1 else {}, gym_type, stage)
        embed = CustomEmbed(title="Match Result", colour=0xa4fbe3,
                            description=f"{user_mention} vs {leader_name} {config.TYPE_MAPPING[gym_type]}")

        embed.add_field(name='\u200B', value='\u200B')
        embed.add_field(name='🏆 WINNER 🏆',
                        value=user_mention,
                        inline=False)
        embed.add_field(
            name=f"GP",
            value=f"{stage}  ⬆",
            inline=False)
        embed.add_field(name=f'Total', value=total_gp,
                        inline=False)
        response, qty, reward = await xrpl_ws.reward_gym(_data1['discord_id'], stage)
        if reward == "ZRP":
            embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
        await msg_hook.send(
            f"**WINNER**   👑**{user_mention}**👑", embed=embed, ephemeral=True)
        if not response:

            await interaction.send(
                f"**Failed**, something went wrong.",
                ephemeral=True)
        else:
            await interaction.send(
                f"**Successfully** sent `{qty}` {reward}",
                ephemeral=True)
        return 1


async def proceed_battle(message: nextcord.Message, battle_instance, b_type=5, battle_name='Friendly Battle'):
    _data1 = db_query.get_owned(battle_instance["challenger"])
    _data2 = db_query.get_owned(battle_instance["challenged"])
    user1_zerpmons = _data1['zerpmons']
    user2_zerpmons = _data2['zerpmons']

    if battle_instance['type'] != 'free_br':
        trainer_embed = CustomEmbed(title=f"Trainers Battle",
                                    description=f"({battle_instance['username1']} VS {battle_instance['username2']})",
                                    color=0xf23557)
        tc1 = list(_data1['trainer_cards'].values())[0] if ('battle_deck' not in _data1) or (
                '0' in _data1['battle_deck'] and ('trainer' not in _data1['battle_deck']['0'])) else \
            _data1['trainer_cards'][_data1['battle_deck']['0']['trainer']]
        tc1i = tc1['image']
        buffed_type1 = [i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

        tc2 = list(_data2['trainer_cards'].values())[0] if ('battle_deck' not in _data2) or (
                '0' in _data2['battle_deck'] and ('trainer' not in _data2['battle_deck']['0'])) else \
            _data2['trainer_cards'][_data2['battle_deck']['0']['trainer']]
        tc2i = tc2['image']
        buffed_type2 = [i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type']

        path1 = f"./static/images/{tc1['name']}.png"
        path2 = f"./static/images/vs.png"
        path3 = f"./static/images/{tc2['name']}.png"

        url1 = tc1i if "https:/" in tc1i else 'https://cloudflare-ipfs.com/ipfs/' + tc1i.replace("ipfs://", "")
        trainer_embed.add_field(
            name=f"{tc1['name']} ({', '.join([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
            value="\u200B", inline=True)

        trainer_embed.add_field(name=f"🆚", value="\u200B", inline=True)

        url2 = tc2i if "https:/" in tc2i else 'https://cloudflare-ipfs.com/ipfs/' + tc2i.replace("ipfs://", "")
        trainer_embed.add_field(
            name=f"{tc2['name']} ({', '.join([i['value'] for i in tc2['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type' or i['trait_type'] == 'Status'])})",
            value="\u200B", inline=True)

        bg_img1 = _data1.get('bg', [None])
        bg_img2 = _data2.get('bg', [None])
        bg_img = None
        if bg_img1[0] is not None and bg_img2[0] is not None:
            bg_img = random.choice([bg_img1[0], bg_img2[0]])
        else:
            bg_img = bg_img1[0] if bg_img1[0] is not None else bg_img2[0]
        gen_image(str(message.id) + '0', url1, url2, path1, path2, path3, gym_bg=bg_img)

        file2 = nextcord.File(f"{message.id}0.png", filename="image0.png")
        trainer_embed.set_image(url=f'attachment://image0.png')

        low_z = max(len(user1_zerpmons), len(user2_zerpmons))
        if b_type <= low_z:
            low_z = b_type

        # Sanity check
        if 'battle_deck' in _data1 and (
                len(_data1['battle_deck']) == 0 or (
                '0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
            await message.reply(content=f"**{_data1['username']}** please check your battle deck, it's empty.")
        elif 'battle_deck' in _data2 and (
                len(_data2['battle_deck']) == 0 or (
                '0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
            await message.reply(content=f"**{_data2['username']}** please check your battle deck, it's empty.")
        # Proceed

        print("Start")
        try:
            del _data1['battle_deck']['0']['trainer']
        except:
            pass
        try:
            del _data2['battle_deck']['0']['trainer']
        except:
            pass
        if 'battle_deck' not in _data1 or (
                len(_data1['battle_deck']) == 0 or (
                '0' in _data1['battle_deck'] and len(_data1['battle_deck']['0']) == 0)):
            user1_zerpmons = list(user1_zerpmons.values())[
                             :low_z if len(user1_zerpmons) > low_z else len(user1_zerpmons)]
        else:
            user1_z = []
            i = 0
            while len(user1_z) != len(_data1['battle_deck']['0']):
                try:
                    user1_z.append(user1_zerpmons[_data1['battle_deck']['0'][str(i)]])
                except:
                    pass
                i += 1
            user1_z.reverse()
            user1_zerpmons = user1_z if len(user1_z) <= low_z else user1_z[-low_z:]
        if 'battle_deck' not in _data2 or (
                len(_data2['battle_deck']) == 0 or (
                '0' in _data2['battle_deck'] and len(_data2['battle_deck']['0']) == 0)):
            user2_zerpmons = list(user2_zerpmons.values())[
                             :low_z if len(user2_zerpmons) > low_z else len(user2_zerpmons)]
        else:
            user2_z = []
            i = 0
            while len(user2_z) != len(_data2['battle_deck']['0']):
                try:
                    user2_z.append(user2_zerpmons[_data2['battle_deck']['0'][str(i)]])
                except:
                    pass
                i += 1
            user2_z.reverse()
            user2_zerpmons = user2_z if len(user2_z) <= low_z else user2_z[-low_z:]
        battle_log = {'teamA': {'trainer': tc1, 'zerpmons': []},
                      'teamB': {'trainer': tc2, 'zerpmons': []}, 'battle_type': battle_name}

    else:
        user1_zerpmons = [user1_zerpmons[battle_instance['z1']]] if type(battle_instance['z1']) is str else [battle_instance['z1']]
        user2_zerpmons = [user2_zerpmons[battle_instance['z2']]] if type(battle_instance['z2']) is str else [battle_instance['z2']]
        battle_log = {'teamA': {'trainer': None, 'zerpmons': []},
                      'teamB': {'trainer': None, 'zerpmons': []}, 'battle_type': battle_name}
        buffed_type1 = []
        buffed_type2 = []
        bg_img = None
    # print(user1_zerpmons[-1], '\n', user2_zerpmons[-1], '\n', user1_zerpmons, '\n', user2_zerpmons, )
    for zerp in user1_zerpmons:
        zerp['rounds'] = []
    for zerp in user2_zerpmons:
        zerp['rounds'] = []
    msg_hook = message

    status_stack = [[], []]
    p1 = None
    p2 = None
    p1_temp = None
    p2_temp = None
    while len(user1_zerpmons) != 0 and len(user2_zerpmons) != 0:
        z1 = user1_zerpmons[-1]
        z1_moves = db_query.get_zerpmon(z1['name'])['moves']
        zimg1 = z1['image']
        z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp1 = ''
        for i in z1_type:
            if i in buffed_type1:
                buffed_zerp1 = i

        z2 = user2_zerpmons[-1]
        z2_moves = db_query.get_zerpmon(z2['name'])['moves']
        zimg2 = z2['image']
        z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']
        buffed_zerp2 = ''
        for i in z2_type:
            if i in buffed_type2:
                buffed_zerp2 = i

        main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x35bcbf)
        if battle_instance['type'] == 'free_br':
            main_embed.description = f'{battle_instance["username1"]} vs {battle_instance["username2"]}'
        path1 = f"./static/images/{z1['name']}.png"
        path2 = f"./static/images/vs.png"
        path3 = f"./static/images/{z2['name']}.png"

        url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
        main_embed.add_field(name=f"{z1['name']} ({', '.join(z1_type)})",
                             value=f"{config.TYPE_MAPPING[buffed_zerp1]} Trainer buff" if buffed_zerp1 != '' else "\u200B",
                             inline=False)

        for i, move in enumerate(z1_moves):
            if move['name'] == "":
                continue
            notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

            main_embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent'] if p1 is None else p1[i]}%\n",
                inline=True)
        main_embed.add_field(name="\u200B", value="\u200B", inline=False)
        main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
        main_embed.add_field(name="\u200B", value="\u200B", inline=False)

        url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
        main_embed.add_field(name=f"{z2['name']} ({', '.join(z2_type)})",
                             value=f"{config.TYPE_MAPPING[buffed_zerp2]} Trainer buff" if buffed_zerp2 != '' else "\u200B",
                             inline=False)

        for i, move in enumerate(z2_moves):
            if move['name'] == "":
                continue
            notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''
            main_embed.add_field(
                name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
                value=f"> **{move['name']}** \n" + \
                      (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                      (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                      (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                      (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                      f"> Percentage: {move['percent'] if p2 is None else p2[i]}%\n",
                inline=True)

        gen_image(message.id, url1, url2, path1, path2, path3, gym_bg=bg_img)

        file = nextcord.File(f"{message.id}.png", filename="image.png")
        main_embed.set_image(url=f'attachment://image.png')

        if message.id == msg_hook.id and battle_instance['type'] != 'free_br':
            msg_hook = await msg_hook.reply(content="\u200B", embeds=[trainer_embed, main_embed], files=[file2, file])
        else:
            msg_hook = await msg_hook.reply(content="\u200B", embed=main_embed, file=file)

        eliminate = ""
        move_counter = 0
        while eliminate == "":
            await asyncio.sleep(3)
            # If battle lasts long then end it
            if move_counter == 20:
                r_int = random.randint(1, 2)
                rand_loser = z2['name'] if r_int == 2 else z1['name']
                await msg_hook.channel.send(
                    content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!")
                eliminate = (r_int, rand_loser)
                if r_int == 2:
                    p2 = None
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                    db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                elif r_int == 1:
                    p1 = None
                    status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                    status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                    db_query.save_zerpmon_winrate(z2['name'], z1['name'])

            result, p1, p2, status_stack, p1_temp, p2_temp = battle_zerpmons(z1['name'], z2['name'], [z1_type, z2_type],
                                                                             status_stack,
                                                                             [buffed_type1, buffed_type2], p1, p2,
                                                                             p1_temp, p2_temp)
            t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
            t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
            t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
            t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

            dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
                result['move1']['stars'] != '' \
                else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

            dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
                result['move2']['stars'] != '' \
                else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"

            atk_msg = f"**{z1['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                      f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n" \
                      f"**{z2['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                      f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n" \
                      "Calculating Battle results..."

            await msg_hook.reply(content=atk_msg)
            if result['winner'] != '1' or '0 damage' not in result.get('status_effect', ''):
                for i, effect in enumerate(status_stack[0].copy()):
                    if '0 damage' in effect:
                        status_stack[0].remove(effect)
                        break
            if result['winner'] != '2' or '0 damage' not in result.get('status_effect', ''):
                for i, effect in enumerate(status_stack[1].copy()):
                    if '0 damage' in effect:
                        status_stack[1].remove(effect)
                        break

            print(result)

            # purple attacks
            if 'status_effect' in result:
                effect = result['status_effect']
                if result['winner'] == '1':
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[0].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[0].count(effect)
                            new_m = f"**{z2['name'] if 'decrease' in effect else z1['name']}**'s damage is {'reduced' if 'decrease' in effect else 'increased'} by ({p_x}%) for the next {'' if count_x <= 1 else '**' + str(count_x) + '** '}{'attack' if count_x <= 1 else 'attacks'}!"
                            await msg_hook.channel.send(
                                content=new_m)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[0].append(effect)
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.channel.send(
                                    content=new_m)
                            else:
                                status_stack[0].append(effect)
                                count_x = status_stack[0].count(effect)
                                new_m = f"**{z2['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.channel.send(
                                    content=new_m)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '1'
                        else:
                            if result['move2']['color'] in effect:
                                result['winner'] = '1'
                            else:
                                new_m = f"{result['move1']['name']} was ineffective! Draw!"
                                await  msg_hook.channel.send(
                                    content=new_m)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[0].append(effect)
                        new_m = f"{z2['name']} has had their purple moves reduced by 1 star!"
                        await msg_hook.channel.send(
                            content=new_m)
                        move_counter += 1
                        continue
                    else:
                        new_m = result['move1']['msg'][:-1]
                        i = int(result['move1']['msg'][-1])

                        new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                            config.COLOR_MAPPING[z2_moves[i]['color']], '')
                        new_m = new_m.replace("@me", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                            "@op", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ')
                        new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(int(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p1[i]))) if p1[i] is not None else 0)}%)"
                        await msg_hook.channel.send(
                            content=new_m)
                        move_counter += 1
                        continue
                else:
                    if 'next' in effect:
                        if 'next attack' in effect:
                            status_stack[1].append(effect)
                            p_x = get_val(effect)
                            count_x = status_stack[1].count(effect)
                            new_m = f"**{z1['name'] if 'decrease' in effect else z2['name']}**'s damage is {'reduced' if 'decrease' in effect else 'increased'} by ({p_x}%) for the next {'' if count_x <= 1 else '**' + str(count_x) + '** '}{'attack' if count_x <= 1 else 'attacks'}!"
                            await  msg_hook.channel.send(
                                content=new_m)
                            move_counter += 1
                            continue
                        elif '0 damage' in effect:
                            if '2' in effect:
                                status_stack[1].append(effect)
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.channel.send(
                                    content=new_m)
                            else:
                                status_stack[1].append(effect)
                                count_x = status_stack[1].count(effect)
                                new_m = f"**{z1['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                                await msg_hook.channel.send(
                                    content=new_m)
                        move_counter += 1
                        continue
                    elif 'knock' in effect:
                        if 'against' not in effect:
                            result['winner'] = '2'
                        else:
                            if result['move1']['color'] in effect:
                                result['winner'] = '2'
                            else:
                                new_m = f"{result['move2']['name']} was ineffective! Draw!"
                                await  msg_hook.channel.send(
                                    content=new_m)
                                move_counter += 1
                                continue
                    elif 'reduce' in effect and 'star' in effect:
                        status_stack[1].append(effect)
                        new_m = f"{z1['name']} has had their purple moves reduced by 1 star!"
                        await  msg_hook.channel.send(
                            content=new_m)
                        move_counter += 1
                        continue
                    else:

                        new_m = result['move2']['msg'][:-1]
                        i = int(result['move2']['msg'][-1])

                        new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                            config.COLOR_MAPPING[z2_moves[i]['color']], '')
                        new_m = new_m.replace("@me", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                            "@op", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ')
                        new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(int(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p2[i]))) if p2[i] is not None else 0)}%)"

                        await msg_hook.channel.send(
                            content=new_m)
                        move_counter += 1
                        continue

            # DRAW
            if result['winner'] == "":
                await msg_hook.channel.send(content=f"**DRAW**")
                move_counter += 1
                continue

            if result['winner'] == '1':
                await msg_hook.channel.send(
                    content=f"{z1['name']} **knocked out** 💀 {z2['name']} 💀!" if '🎯' not in result['move1'][
                        'mul'] else f"**{z2['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}")
                eliminate = (2, z2['name'])
                p2 = None
                status_stack[0] = [i for i in status_stack[0] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[1] = [i for i in status_stack[1] if ('oppo' in i) or ('enemy' in i)]
                db_query.save_zerpmon_winrate(z1['name'], z2['name'])
                move_counter += 1

            elif result['winner'] == '2':
                await msg_hook.channel.send(
                    content=f"{z2['name']} **knocked out** 💀 {z1['name']} 💀!" if '🎯' not in result['move2'][
                        'mul'] else f"**{z1['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}")
                eliminate = (1, z1['name'])
                p1 = None
                status_stack[1] = [i for i in status_stack[1] if ('oppo' not in i) and ('enemy' not in i)]
                status_stack[0] = [i for i in status_stack[0] if ('oppo' in i) or ('enemy' in i)]
                db_query.save_zerpmon_winrate(z2['name'], z1['name'])
                move_counter += 1

        if eliminate[0] == 1:
            z1['rounds'].append(0)
            z2['rounds'].append(1)
            battle_log['teamA']['zerpmons'].append({'name': z1['name'], 'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[result['move2']['type']], 'rounds': z1['rounds'].copy()})
            user1_zerpmons = [i for i in user1_zerpmons if i['name'] != eliminate[1]]
            p1 = None
            p1_temp = None
        elif eliminate[0] == 2:
            z1['rounds'].append(1)
            z2['rounds'].append(0)
            battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[result['move1']['type']], 'rounds': z2['rounds'].copy()})
            user2_zerpmons = [i for i in user2_zerpmons if i['name'] != eliminate[1]]
            p2 = None
            p2_temp = None
        file.close()
        for i in range(3):
            try:
                os.remove(f"{message.id}.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    if battle_instance['type'] != 'free_br':
        file2.close()
        for i in range(3):
            try:
                os.remove(f"{message.id}0.png")
                break
            except Exception as e:
                print(f"Delete failed retrying {e}")

    if len(user1_zerpmons) == 0:
        await msg_hook.channel.send(
            f"**WINNER**   👑**{battle_instance['username2']}**👑")
        battle_log['teamB']['zerpmons'].append({'name': z2['name'], 'rounds': z2['rounds']})
        db_query.update_battle_log(_data1['discord_id'], _data2['discord_id'], _data1['username'], _data2['username'], battle_log['teamA'],
                                   battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])

        db_query.update_pvp_user_wr(_data1['discord_id'], 0)
        db_query.update_pvp_user_wr(_data2['discord_id'], 1)
        return 2
    elif len(user2_zerpmons) == 0:
        await msg_hook.channel.send(
            f"**WINNER**   👑**{battle_instance['username1']}**👑")
        battle_log['teamA']['zerpmons'].append({'name': z1['name'], 'rounds': z1['rounds']})
        db_query.update_battle_log(_data1['discord_id'], _data2['discord_id'], _data1['username'], _data2['username'],
                                   battle_log['teamA'],
                                   battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])
        db_query.update_pvp_user_wr(_data1['discord_id'], 1)
        db_query.update_pvp_user_wr(_data2['discord_id'], 0)
        return 1


async def proceed_mission(interaction: nextcord.Interaction, user_id, active_zerpmon, old_num):
    serial, z1 = active_zerpmon
    z1_moves = db_query.get_zerpmon(z1['name'])
    z1_level = z1_moves['level'] if 'level' in z1_moves else 1
    z1_moves = z1_moves['moves']

    zimg1 = z1['image']
    _data1 = db_query.get_owned(user_id)
    u_flair = f' | {_data1.get("flair", [])[0]}' if len(
        _data1.get("flair", [])) > 0 else ''
    user_mention = interaction.user.mention + u_flair

    z1_type = [i['value'] for i in z1['attributes'] if i['trait_type'] == 'Type']
    buffed_type1 = []
    if len(_data1['trainer_cards']) > 0:
        for key, tc1 in _data1['trainer_cards'].items():
            buffed_type1.extend([i['value'] for i in tc1['attributes'] if i['trait_type'] == 'Affinity' or i['trait_type'] == 'Type'])

    buffed_zerp = ''
    for i in z1_type:
        if i in buffed_type1:
            buffed_zerp = i

    z2 = db_query.get_rand_zerpmon(level=z1_level)
    while z2['name'] == z1['name']:
        z2 = db_query.get_rand_zerpmon(level=z1_level)
    z2_moves = z2['moves']
    zimg2 = z2['image']
    z2_type = [i['value'] for i in z2['attributes'] if i['trait_type'] == 'Type']

    main_embed = CustomEmbed(title="Zerpmon rolling attacks...", color=0x8971d0)

    path1 = f"./static/images/{z1['name']}.png"
    path2 = f"./static/images/vs.png"
    path3 = f"./static/images/{z2['name']}.png"

    url1 = zimg1 if "https:/" in zimg1 else 'https://cloudflare-ipfs.com/ipfs/' + zimg1.replace("ipfs://", "")
    main_embed.add_field(name=f"{z1['name']} ({', '.join(z1_type)})",
                         value=f"{config.TYPE_MAPPING[buffed_zerp]} Trainer buff" if buffed_zerp != '' else "\u200B",
                         inline=False)

    for i, move in enumerate(z1_moves):
        if move['name'] == "":
            continue
        notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                  (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {move['percent']}%\n",
            inline=True)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)
    main_embed.add_field(name=f"🆚", value="\u200B", inline=False)
    main_embed.add_field(name="\u200B", value="\u200B", inline=False)

    url2 = zimg2 if "https:/" in zimg2 else 'https://cloudflare-ipfs.com/ipfs/' + zimg2.replace("ipfs://", "")
    main_embed.add_field(name=f"{z2['name']} ({', '.join(z2_type)})",
                         value="\u200B", inline=False)

    for i, move in enumerate(z2_moves):
        if move['name'] == "":
            continue
        notes = f"{db_query.get_move(move['name'])['notes']}" if move['color'] == 'purple' else ''

        main_embed.add_field(
            name=f"**{config.COLOR_MAPPING[move['color']]} Move:**",
            value=f"> **{move['name']}** \n" + \
                  (f"> Status Affect: `{notes}`\n" if notes != '' else "") + \
                  (f"> DMG: {move['dmg']}\n" if 'dmg' in move else "") + \
                  (f"> Stars: {len(move['stars']) * '★'}\n" if 'stars' in move else "") + \
                  (f"> Type: {config.TYPE_MAPPING[move['type'].replace(' ', '')]}\n" if 'type' in move else "") + \
                  f"> Percentage: {move['percent']}%\n",
            inline=True)
    gen_image(interaction.id, url1, url2, path1, path2, path3, _data1.get('bg', [None])[0])

    file = nextcord.File(f"{interaction.id}.png", filename="image.png")
    main_embed.set_image(url=f'attachment://image.png')

    await interaction.send(content="\u200B", embed=main_embed, file=file, ephemeral=True)

    eliminate = ""
    status_stack = [[], []]
    p1 = None
    p2 = [(float(p['percent']) if p['percent'] not in ["0.00", "0", ""] else None) for p in
          z2['moves']]
    p1_temp = None
    p2_temp = None
    move_counter = 0
    lost = 0
    battle_log = {'teamA': {'trainer': None, 'zerpmons': []},
                  'teamB': {'trainer': None, 'zerpmons': []}, 'battle_type': 'Mission Battle'}
    while eliminate == "":
        await asyncio.sleep(4)
        result, p1, p2, status_stack, p1_temp, p2_temp = battle_zerpmons(z1['name'], z2['name'], [z1_type, z2_type],
                                                                         status_stack,
                                                                         [buffed_type1, []], p1, p2, p1_temp,
                                                                         p2_temp)
        t_info1 = config.TYPE_MAPPING[result['move1']['type'].replace(" ", '')] + ' ' + result['move1']['mul']
        t_info2 = config.TYPE_MAPPING[result['move2']['type'].replace(" ", '')] + ' ' + result['move2']['mul']
        t_info1 = f'({t_info1})' if t_info1 not in ["", " "] else t_info1
        t_info2 = f'({t_info2})' if t_info2 not in ["", " "] else t_info2

        dmg1_str = f"{result['move1']['name']} {result['move1']['stars'] * '★'} (__{result['move1']['percent']}%__)" if \
            result['move1']['stars'] != '' \
            else f"{result['move1']['name']}{'ed' if result['move1']['color'] == 'miss' else f' {t_info1} ' + str(result['move1']['dmg']) if 'dmg_str1' not in result else result['dmg_str1']} (__{result['move1']['percent']}%__)"

        dmg2_str = f"{result['move2']['name']} {result['move2']['stars'] * '★'} (__{result['move2']['percent']}%__)" if \
            result['move2']['stars'] != '' \
            else f"{result['move2']['name']}{'ed' if result['move2']['color'] == 'miss' else f' {t_info2} ' + str(result['move2']['dmg']) if 'dmg_str2' not in result else result['dmg_str2']} (__{result['move2']['percent']}%__)"

        atk_msg = f"**{z1['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z1_type])})\t{' used' if result['move1']['color'] != 'miss' else ''} " \
                  f"{config.COLOR_MAPPING[result['move1']['color']]}  {dmg1_str}\n" \
                  f"**{z2['name']}**\t({', '.join([config.TYPE_MAPPING[i] for i in z2_type])})\t{' used' if result['move2']['color'] != 'miss' else ''} " \
                  f"{config.COLOR_MAPPING[result['move2']['color']]}  {dmg2_str}\n" \
                  "Calculating Battle results..."

        await interaction.send(content=atk_msg, ephemeral=True)
        if result['winner'] != '1' or '0 damage' not in result.get('status_effect', ''):
            for i, effect in enumerate(status_stack[0].copy()):
                if '0 damage' in effect:
                    status_stack[0].remove(effect)
                    break
        if result['winner'] != '2' or '0 damage' not in result.get('status_effect', ''):
            for i, effect in enumerate(status_stack[1].copy()):
                if '0 damage' in effect:
                    status_stack[1].remove(effect)
                    break

        print(result)

        # If battle lasts long then end it
        if move_counter == 20:
            r_int = random.randint(1, 2)
            rand_loser = z2['name'] if r_int == 2 else z1['name']
            await interaction.send(
                content=f"Out of nowhere, a giant **meteor** lands right on top of 💀 {rand_loser} 💀!", ephemeral=True)
            lost = r_int

        # purple attacks
        if 'status_effect' in result:
            effect = result['status_effect']
            if result['winner'] == '1':
                if 'next' in effect:
                    if 'next attack' in effect:
                        status_stack[0].append(effect)
                        p_x = get_val(effect)
                        count_x = status_stack[0].count(effect)
                        new_m = f"**{z2['name'] if 'decrease' in effect else z1['name']}**'s damage is {'reduced' if 'decrease' in effect else 'increased'} by ({p_x}%) for the next {'' if count_x <= 1 else '**' + str(count_x) + '** '}{'attack' if count_x <= 1 else 'attacks'}!"
                        await interaction.send(
                            content=new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif '0 damage' in effect:
                        if '2' in effect:
                            status_stack[0].append(effect)
                            status_stack[0].append(effect)
                            count_x = status_stack[0].count(effect)
                            new_m = f"**{z2['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=new_m, ephemeral=True)
                        else:
                            status_stack[0].append(effect)
                            count_x = status_stack[0].count(effect)
                            new_m = f"**{z2['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=new_m, ephemeral=True)
                    move_counter += 1
                    continue
                elif 'knock' in effect:
                    if 'against' not in effect:
                        result['winner'] = '1'
                    else:
                        if result['move2']['color'] in effect:
                            result['winner'] = '1'
                        else:
                            new_m = f"{result['move1']['name']} was ineffective! Draw!"
                            await interaction.send(
                                content=new_m, ephemeral=True)
                            move_counter += 1
                            continue
                elif 'reduce' in effect and 'star' in effect:
                    status_stack[0].append(effect)
                    new_m = f"{z2['name']} has had their purple moves reduced by 1 star!"
                    await interaction.send(
                        content=new_m, ephemeral=True)
                    move_counter += 1
                    continue
                else:
                    new_m = result['move1']['msg'][:-1]
                    i = int(result['move1']['msg'][-1])

                    new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                        config.COLOR_MAPPING[z2_moves[i]['color']], '')
                    new_m = new_m.replace("@me", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ').replace(
                        "@op", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ')
                    new_m += f" ({str(z1_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z1_moves[i] and z1_moves[i]['dmg'] != '' else ''}{(str(int(float(p2[i]))) if p2[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p1[i]))) if p1[i] is not None else 0)}%)"
                    await interaction.send(
                        content=new_m, ephemeral=True)
                    move_counter += 1
                    continue
            else:
                if 'next' in effect:
                    if 'next attack' in effect:
                        status_stack[1].append(effect)
                        p_x = get_val(effect)
                        count_x = status_stack[1].count(effect)
                        new_m = f"**{z1['name'] if 'decrease' in effect else z2['name']}**'s damage is {'reduced' if 'decrease' in effect else 'increased'} by ({p_x}%) for the next {'' if count_x <= 1 else '**' + str(count_x) + '** '}{'attack' if count_x <= 1 else 'attacks'}!"
                        await interaction.send(
                            content=new_m, ephemeral=True)
                        move_counter += 1
                        continue
                    elif '0 damage' in effect:
                        if '2' in effect:
                            status_stack[1].append(effect)
                            status_stack[1].append(effect)
                            count_x = status_stack[1].count(effect)
                            new_m = f"**{z1['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=new_m, ephemeral=True)
                        else:
                            status_stack[1].append(effect)
                            count_x = status_stack[1].count(effect)
                            new_m = f"**{z1['name']}**'s damage reduced to 0 for **{count_x}** {'turns' if count_x > 1 else 'turn'}!"
                            await interaction.send(
                                content=new_m, ephemeral=True)
                    move_counter += 1
                    continue
                elif 'knock' in effect:
                    if 'against' not in effect:
                        result['winner'] = '2'
                    else:
                        if result['move1']['color'] in effect:
                            result['winner'] = '2'
                        else:
                            new_m = f"{result['move1']['name']} was ineffective! Draw!"
                            await interaction.send(
                                content=new_m, ephemeral=True)
                            move_counter += 1
                            continue
                elif 'reduce' in effect and 'star' in effect:
                    status_stack[1].append(effect)
                    new_m = f"{z1['name']} has had their purple moves reduced by 1 star!"
                    await interaction.send(
                        content=new_m, ephemeral=True)
                    move_counter += 1
                    continue
                else:

                    new_m = result['move2']['msg'][:-1]
                    i = int(result['move2']['msg'][-1])

                    new_m = new_m.replace(config.COLOR_MAPPING[z1_moves[i]['color']], '').replace(
                        config.COLOR_MAPPING[z2_moves[i]['color']], '')
                    new_m = new_m.replace("@me", ' ' + z2['name'] + '\'s ' + z2_moves[i]['name'] + '  ').replace(
                        "@op", ' ' + z1['name'] + '\'s ' + z1_moves[i]['name'] + '  ')
                    new_m += f" ({str(z2_moves[i]['dmg']) + 'dmg, ' if 'dmg' in z2_moves[i] and z2_moves[i]['dmg'] != '' else ''}{(str(int(float(p1[i]))) if p1[i] is not None else 0) if 'opposing' in result['status_effect'] else (str(int(float(p2[i]))) if p2[i] is not None else 0)}%)"

                    await interaction.send(
                        content=new_m, ephemeral=True)
                    move_counter += 1
                    continue

        # Check if status effect has stacked upto 3 then knock the Zerpmon

        # DRAW
        if result['winner'] == "" and lost == 0:
            await interaction.send(content=f"**DRAW**", ephemeral=True)
            move_counter += 1
            continue

        if (result['winner'] == '1' and lost == 0) or lost == 2:
            if lost == 0:
                await interaction.send(
                    content=f"{z1['name']} **knocked out** {z2['name']}!" if '🎯' not in result['move1'][
                        'mul'] else f"**{z2['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}", ephemeral=True)
            eliminate = (2, z2['name'])
            await interaction.send(
                f"**WINNER**   👑**{user_mention}**👑",
                ephemeral=True)
            db_query.save_zerpmon_winrate(z1['name'], z2['name'])
            db_query.update_user_wr(user_id, 1)
            battle_log['teamA']['zerpmons'].append(
                {'name': z1['name'], 'rounds': [1]})
            battle_log['teamB']['zerpmons'].append(
                {'name': z2['name'], 'ko_move': result['move1']['name'] + ' ' + config.TYPE_MAPPING[result['move1']['type']], 'rounds': [0]})
            db_query.update_battle_log(interaction.user.id, None, interaction.user.name, 'Mission',
                                       battle_log['teamA'],
                                       battle_log['teamB'], winner=1, battle_type=battle_log['battle_type'])
            db_query.update_battle_count(user_id, old_num)
            # Reward user on a Win
            double_xp = 'double_xp' in _data1 and _data1['double_xp'] > time.time()
            responses = await xrpl_ws.reward_user(user_id, z1['name'], double_xp=double_xp)
            embed = CustomEmbed(title=f"🏆 Mission Victory 🏆",
                                color=0x8ef6e4)
            embed.add_field(name="XP", value=10 if not double_xp else 20, inline=True)
            private = True
            for res in responses:
                response, reward, qty, token_id = res
                if reward is None:
                    continue
                if reward == "XRP":
                    embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
                else:
                    embed.add_field(name=f"{reward}" + ' Won', value=qty, inline=True)
                if reward == "NFT":
                    embed.add_field(name=f"NFT", value=token_id[0], inline=True)
                    embed.description = f'🔥 🔥 Congratulations {user_mention} just caught **{token_id[0]}**!! 🔥 🔥\n@everyone'
                    embed.set_thumbnail(token_id[1])
                    private = False
                    await send_global_message(guild=interaction.guild, text=embed.description, image=token_id[1])

            await interaction.send(
                embed=embed,
                ephemeral=private)
            if responses[0][1] in ["XRP", "NFT"]:
                if not responses[0][0]:

                    await interaction.send(
                        f"**Failed**, something went wrong.",
                        ephemeral=True)
                else:
                    await interaction.send(
                        f"**Successfully** sent `{responses[0][2]}` {responses[0][1]}",
                        ephemeral=True)
            move_counter += 1

        elif (result['winner'] == '2' and lost == 0) or lost == 1:
            if lost == 0:
                await interaction.send(
                    content=f"{z2['name']} **knocked out** {z1['name']}!" if '🎯' not in result['move1'][
                        'mul'] else f"**{z1['name']}**{random.sample(config.CRIT_STATEMENTS, 1)[0]}", ephemeral=True)
            eliminate = (1, z1['name'])
            await interaction.send(
                f"Sorry you **LOST** 💀",
                ephemeral=True)
            battle_log['teamA']['zerpmons'].append(
                {'name': z1['name'], 'ko_move': result['move2']['name'] + ' ' + config.TYPE_MAPPING[result['move2']['type']], 'rounds': [0]})
            battle_log['teamB']['zerpmons'].append(
                {'name': z2['name'], 'rounds': [1]})
            db_query.update_battle_log(interaction.user.id, None, interaction.user.name, 'Mission',
                                       battle_log['teamA'],
                                       battle_log['teamB'], winner=2, battle_type=battle_log['battle_type'])
            z1['active_t'] = checks.get_next_ts()

            db_query.update_zerpmon_alive(z1, serial, user_id)
            db_query.update_user_wr(user_id, 0)
            db_query.save_zerpmon_winrate(z2['name'], z1['name'])
            db_query.update_battle_count(user_id, old_num)
            move_counter += 1

        file.close()
        for i in range(3):
            try:
                os.remove(f"{interaction.id}.png")
                break
            except Exception as e:
                print("Delete failed retrying: ", e)

    return eliminate[0]
